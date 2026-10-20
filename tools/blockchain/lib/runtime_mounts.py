#!/usr/bin/env python3
"""Convert SEED's per-node Docker builds into runtime-mounted node configs.

SEED's Docker compiler normally creates one Dockerfile and one image per node.
Large deployments can produce thousands of generated images. This tool keeps the
generated node-private files, but mounts each node directory at container start
and copies those files into a shared base image.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - depends on local environment
    raise SystemExit(
        "PyYAML is required. Run with the repository's Python environment, "
        "use the same Python environment as ChainSEED."
    ) from exc


HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_RUNTIME_MOUNT = "/seedemu-node"
DEFAULT_NOFILE_LIMIT = 524288
BOOTSTRAP_NAME = ".seedemu_runtime_bootstrap.sh"
SUMMARY_NAME = "nobuild-mount-summary.json"


class PatchError(RuntimeError):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise PatchError(f"invalid compose file: {path}")
    if not isinstance(data.get("services"), dict):
        raise PatchError(f"compose file has no services mapping: {path}")
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    with path.open("w") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, default_flow_style=False)


def _parse_dummy_images(output_dir: Path) -> dict[str, str]:
    dummies_dir = output_dir / "dummies"
    images: dict[str, str] = {}
    if not dummies_dir.exists():
        return images

    for dockerfile in sorted(p for p in dummies_dir.iterdir() if p.is_file()):
        digest = dockerfile.name
        if not HEX32_RE.match(digest):
            continue
        for raw_line in dockerfile.read_text().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.upper().startswith("FROM "):
                parts = line.split()
                if len(parts) >= 2:
                    images[digest] = parts[1]
                break
    return images


def _build_context_path(build_spec: Any) -> str | None:
    if isinstance(build_spec, str):
        return build_spec
    if isinstance(build_spec, dict):
        context = build_spec.get("context")
        dockerfile = build_spec.get("dockerfile")
        if context == "." and isinstance(dockerfile, str) and dockerfile.startswith("dummies/"):
            return None
        if isinstance(context, str):
            return context
    return None


def _is_safe_runtime_run(command: str) -> bool:
    safe_prefixes = (
        "chmod +x ",
        "mkdir -p ",
        "touch ",
    )
    return command.startswith(safe_prefixes)


def _parse_dockerfile(dockerfile: Path, allow_unsupported_run: bool) -> dict[str, Any]:
    base_image = ""
    copies: list[tuple[str, str]] = []
    runtime_runs: list[str] = []
    unsupported: list[str] = []

    for lineno, raw_line in enumerate(dockerfile.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        keyword, _, rest = line.partition(" ")
        keyword = keyword.upper()
        rest = rest.strip()

        if keyword == "FROM":
            parts = rest.split()
            if not parts:
                unsupported.append(f"{lineno}: empty FROM")
                continue
            base_image = parts[0]
        elif keyword == "COPY":
            try:
                parts = shlex.split(rest)
            except ValueError as exc:
                unsupported.append(f"{lineno}: cannot parse COPY: {exc}")
                continue
            if len(parts) != 2:
                unsupported.append(f"{lineno}: unsupported COPY form: {line}")
                continue
            copies.append((parts[0], parts[1]))
        elif keyword == "RUN":
            if _is_safe_runtime_run(rest):
                runtime_runs.append(rest)
            elif not allow_unsupported_run:
                unsupported.append(f"{lineno}: unsupported RUN: {rest}")
        elif keyword in {"ARG", "CMD"}:
            continue
        else:
            unsupported.append(f"{lineno}: unsupported Dockerfile directive: {line}")

    if not base_image:
        unsupported.append("missing FROM")
    if unsupported:
        raise PatchError(f"cannot convert {dockerfile}:\n  " + "\n  ".join(unsupported))

    return {
        "base_image": base_image,
        "copies": copies,
        "runtime_runs": runtime_runs,
    }


def _shell_quote(value: str) -> str:
    return shlex.quote(value)


def _write_bootstrap(
    node_dir: Path,
    copies: list[tuple[str, str]],
    runtime_runs: list[str],
    runtime_mount: str,
) -> None:
    lines = [
        "#!/usr/bin/env bash",
        "set -Eeuo pipefail",
        "",
        "copy_one() {",
        '    local src="$1"',
        '    local dst="$2"',
        '    mkdir -p "$(dirname "$dst")"',
        f'    cp -f {_shell_quote(runtime_mount)}/"$src" "$dst"',
        "}",
        "",
    ]

    for source, target in copies:
        lines.append(f"copy_one {_shell_quote(source)} {_shell_quote(target)}")

    if runtime_runs:
        lines.append("")
        lines.append("# Runtime equivalents for safe Dockerfile RUN commands.")
        lines.extend(runtime_runs)

    lines.extend(["", "exec /start.sh", ""])

    bootstrap = node_dir / BOOTSTRAP_NAME
    bootstrap.write_text("\n".join(lines))
    mode = bootstrap.stat().st_mode
    bootstrap.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _remove_dummy_depends(service: dict[str, Any], dummy_services: set[str]) -> None:
    depends_on = service.get("depends_on")
    if isinstance(depends_on, list):
        filtered = [dep for dep in depends_on if dep not in dummy_services]
        if filtered:
            service["depends_on"] = filtered
        else:
            service.pop("depends_on", None)
    elif isinstance(depends_on, dict):
        filtered = {key: value for key, value in depends_on.items() if key not in dummy_services}
        if filtered:
            service["depends_on"] = filtered
        else:
            service.pop("depends_on", None)


def _append_runtime_mount(service: dict[str, Any], source: str, runtime_mount: str) -> None:
    mount = {
        "type": "bind",
        "source": source,
        "target": runtime_mount,
        "read_only": True,
    }
    volumes = service.get("volumes")
    if volumes is None:
        service["volumes"] = [mount]
    elif isinstance(volumes, list):
        service["volumes"].append(mount)
    else:
        raise PatchError(f"unsupported service volumes format: {volumes!r}")


def _set_nofile_limit(service: dict[str, Any], limit: int) -> None:
    ulimits = service.get("ulimits")
    if ulimits is None:
        ulimits = {}
        service["ulimits"] = ulimits
    if not isinstance(ulimits, dict):
        raise PatchError(f"unsupported service ulimits format: {ulimits!r}")
    ulimits["nofile"] = {"soft": limit, "hard": limit}


def patch_output(
    output_dir: Path,
    compose_file: Path,
    runtime_mount: str,
    nofile_limit: int,
    allow_unsupported_run: bool,
    backup: bool,
) -> dict[str, Any]:
    data = _read_yaml(compose_file)
    services: dict[str, Any] = data["services"]
    dummy_services = {name for name in services if HEX32_RE.match(name)}
    dummy_images = _parse_dummy_images(output_dir)

    converted = 0
    copy_count = 0
    runtime_run_count = 0
    nofile_services = 0
    images_used: dict[str, int] = {}
    converted_services: list[str] = []

    for service_name in sorted(dummy_services):
        services.pop(service_name, None)

    for service_name, service in list(services.items()):
        if not isinstance(service, dict):
            continue
        labels = service.get("labels", {})
        if isinstance(labels, list):
            labels = dict(item.split("=", 1) for item in labels if "=" in item)
        if labels.get("org.seedsecuritylabs.seedemu.meta.chainseed.component"):
            # Auxiliary applications keep their own Docker build context.
            context = _build_context_path(service.get("build"))
            if context is not None:
                node_dir = (output_dir / context).resolve()
                try:
                    node_dir.relative_to(output_dir.resolve())
                except ValueError as exc:
                    raise PatchError(f"build context escapes output dir: {context}") from exc
                dockerfile = node_dir / "Dockerfile"
                lines = dockerfile.read_text().splitlines()
                for index, line in enumerate(lines):
                    parts = line.split()
                    if len(parts) == 2 and parts[0] == "FROM" and parts[1] in dummy_images:
                        lines[index] = "FROM " + dummy_images[parts[1]]
                dockerfile.write_text("\n".join(lines) + "\n")
            _remove_dummy_depends(service, dummy_services)
            continue
        _set_nofile_limit(service, nofile_limit)
        nofile_services += 1
        build_spec = service.get("build")
        if build_spec is None:
            _remove_dummy_depends(service, dummy_services)
            continue

        context = _build_context_path(build_spec)
        if context is None:
            service.pop("build", None)
            _remove_dummy_depends(service, dummy_services)
            continue

        node_dir = (output_dir / context).resolve()
        try:
            node_dir.relative_to(output_dir.resolve())
        except ValueError as exc:
            raise PatchError(f"build context escapes output dir: {context}") from exc

        dockerfile = node_dir / "Dockerfile"
        if not dockerfile.exists():
            raise PatchError(f"Dockerfile not found for {service_name}: {dockerfile}")

        parsed = _parse_dockerfile(dockerfile, allow_unsupported_run)
        base_ref = parsed["base_image"]
        image = dummy_images.get(base_ref, base_ref)
        if HEX32_RE.match(image):
            raise PatchError(
                f"could not resolve base image digest {image} for service {service_name}; "
                "dummy Dockerfile is missing"
            )

        rel_node_dir = node_dir.relative_to(output_dir.resolve()).as_posix()
        _write_bootstrap(node_dir, parsed["copies"], parsed["runtime_runs"], runtime_mount)

        service.pop("build", None)
        service["image"] = image
        service["entrypoint"] = ["/bin/bash", f"{runtime_mount}/{BOOTSTRAP_NAME}"]
        _remove_dummy_depends(service, dummy_services)
        _append_runtime_mount(service, f"./{rel_node_dir}", runtime_mount)

        converted += 1
        copy_count += len(parsed["copies"])
        runtime_run_count += len(parsed["runtime_runs"])
        images_used[image] = images_used.get(image, 0) + 1
        converted_services.append(service_name)

    if backup:
        backup_path = compose_file.with_name("docker-compose.build.yml")
        if not backup_path.exists():
            backup_path.write_text(compose_file.read_text())

    _write_yaml(compose_file, data)

    summary = {
        "output_dir": str(output_dir),
        "compose_file": str(compose_file),
        "runtime_mount": runtime_mount,
        "dummy_services_removed": len(dummy_services),
        "services_converted": converted,
        "copy_entries": copy_count,
        "runtime_run_entries": runtime_run_count,
        "nofile_limit": nofile_limit,
        "nofile_services": nofile_services,
        "images_used": images_used,
        "converted_services_sample": converted_services[:20],
    }
    (output_dir / SUMMARY_NAME).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch generated large-scale output to avoid per-node Docker builds."
    )
    parser.add_argument("--output", default="./output", help="Generated SEED output directory.")
    parser.add_argument(
        "--compose-file",
        default=None,
        help="Compose file to patch. Default: <output>/docker-compose.yml.",
    )
    parser.add_argument(
        "--runtime-mount",
        default=DEFAULT_RUNTIME_MOUNT,
        help=f"Container mount point for node generated files. Default: {DEFAULT_RUNTIME_MOUNT}.",
    )
    parser.add_argument(
        "--nofile-limit",
        type=int,
        default=DEFAULT_NOFILE_LIMIT,
        help=f"Container nofile soft/hard limit. Default: {DEFAULT_NOFILE_LIMIT}.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not keep docker-compose.build.yml before patching.",
    )
    parser.add_argument(
        "--allow-unsupported-run",
        action="store_true",
        help=(
            "Skip unsupported Dockerfile RUN commands instead of failing. "
            "Use only when you know the base image already contains the effects."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output_dir = Path(args.output).resolve()
    compose_file = Path(args.compose_file).resolve() if args.compose_file else output_dir / "docker-compose.yml"

    if not output_dir.is_dir():
        raise PatchError(f"output directory not found: {output_dir}")
    if not compose_file.exists():
        raise PatchError(f"compose file not found: {compose_file}")
    if args.nofile_limit < 1024:
        raise PatchError("--nofile-limit must be at least 1024")

    summary = patch_output(
        output_dir=output_dir,
        compose_file=compose_file,
        runtime_mount=args.runtime_mount,
        nofile_limit=args.nofile_limit,
        allow_unsupported_run=args.allow_unsupported_run,
        backup=not args.no_backup,
    )
    print(
        "nobuild-mount patch complete: "
        f"converted={summary['services_converted']} "
        f"removed_dummies={summary['dummy_services_removed']} "
        f"copy_entries={summary['copy_entries']} "
        f"runtime_run_entries={summary['runtime_run_entries']} "
        f"nofile_services={summary['nofile_services']} "
        f"nofile_limit={summary['nofile_limit']}"
    )
    for image, count in sorted(summary["images_used"].items()):
        print(f"  image {image}: {count} services")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PatchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
