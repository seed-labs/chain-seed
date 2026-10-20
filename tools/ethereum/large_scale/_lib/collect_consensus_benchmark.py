#!/usr/bin/env python3
"""Collect raw consensus timing data for E10 Ethereum benchmark experiments."""

from __future__ import annotations

import argparse
import csv
import json
import re
import signal
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
ETHEREUM_DIR = SCRIPT_DIR.parent
DEFAULT_COMPOSE_FILE = ETHEREUM_DIR / "output" / "docker-compose.yml"

HEAD_FIELDS = [
    "sample",
    "timestamp",
    "elapsed_sec",
    "beacon_index",
    "beacon_name",
    "asn",
    "url",
    "head_slot",
    "head_root",
    "parent_root",
    "error",
]

FIRST_SEEN_FIELDS = [
    "timestamp",
    "elapsed_sec",
    "beacon_index",
    "beacon_name",
    "asn",
    "head_slot",
    "head_root",
]

FINALITY_FIELDS = [
    "sample",
    "timestamp",
    "elapsed_sec",
    "reference_beacon",
    "head_slot",
    "current_epoch",
    "justified_epoch",
    "finalized_epoch",
    "finality_lag",
    "error",
]

ATTESTATION_FIELDS = [
    "timestamp",
    "elapsed_sec",
    "block_slot",
    "attestation_slot",
    "inclusion_delay_slots",
    "committee_index",
    "source_epoch",
    "target_epoch",
    "attestation_index",
]

SLOT_OBSERVATION_FIELDS = [
    "timestamp",
    "elapsed_sec",
    "slot",
    "root",
    "canonical",
    "error",
]

REORG_FIELDS = [
    "timestamp",
    "elapsed_sec",
    "slot",
    "old_root",
    "new_root",
]

VALIDATOR_LIVENESS_FIELDS = [
    "sample",
    "timestamp",
    "elapsed_sec",
    "epoch",
    "registry_validators",
    "queried_validators",
    "live_validators",
    "missed_validators",
    "participation_percent",
    "error",
]

NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class BeaconNode:
    index: int
    service: str
    name: str
    ip: str
    asn: str

    @property
    def url(self) -> str:
        return f"http://{self.ip}:8000"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-f", "--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("-o", "--output-dir", type=Path, required=True)
    parser.add_argument("-i", "--interval", type=float, default=2.0)
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument("--samples", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--beacon-sample", type=int, default=32)
    parser.add_argument(
        "--beacon-indices-file",
        type=Path,
        default=None,
        help="Optional newline-separated Beacon indices to sample instead of --beacon-sample.",
    )
    parser.add_argument("--reference-beacon-index", type=int, default=0)
    parser.add_argument("--reorg-depth", type=int, default=64)
    parser.add_argument("--reorg-scan-interval", type=float, default=12.0)
    parser.add_argument("--expected-active-validators", type=int, default=0)
    parser.add_argument("--validator-liveness-timeout", type=float, default=10.0)
    parser.add_argument("--validator-liveness-batch-size", type=int, default=1024)
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def append_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerows(rows)


def compose_service_blocks(compose_file: Path) -> dict[str, str]:
    blocks: dict[str, list[str]] = {}
    current: Optional[str] = None
    in_services = False

    for raw_line in compose_file.read_text().splitlines():
        if raw_line == "services:":
            in_services = True
            continue
        if not in_services:
            continue
        if raw_line and not raw_line.startswith(" "):
            break
        match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", raw_line)
        if match:
            current = match.group(1)
            blocks[current] = []
            continue
        if current is not None:
            blocks[current].append(raw_line)

    return {name: "\n".join(lines) for name, lines in blocks.items()}


def discover_beacons(compose_file: Path) -> list[BeaconNode]:
    beacons: list[BeaconNode] = []
    for service, block in compose_service_blocks(compose_file).items():
        if "Ethereum-POS-Beacon-" not in block:
            continue
        display = re.search(r"org\.seedsecuritylabs\.seedemu\.meta\.displayname:\s*(Ethereum-POS-Beacon-(\d+))", block)
        ip = re.search(r"ipv4_address:\s*([0-9.]+)", block)
        asn = re.search(r"org\.seedsecuritylabs\.seedemu\.meta\.asn:\s*'?([0-9]+)'?", block)
        container = re.search(r"container_name:\s*(\S+)", block)
        if not display or not ip:
            continue
        beacons.append(
            BeaconNode(
                index=int(display.group(2)),
                service=service,
                name=container.group(1) if container else display.group(1),
                ip=ip.group(1),
                asn=asn.group(1) if asn else "",
            )
        )
    return sorted(beacons, key=lambda node: node.index)


def choose_sample(nodes: list[BeaconNode], size: int) -> list[BeaconNode]:
    if size <= 0 or size >= len(nodes):
        return nodes
    if size == 1:
        return [nodes[0]]
    positions = sorted({round(i * (len(nodes) - 1) / (size - 1)) for i in range(size)})
    return [nodes[pos] for pos in positions]


def choose_indices(nodes: list[BeaconNode], path: Path) -> list[BeaconNode]:
    requested = {
        int(line.strip())
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    selected = [node for node in nodes if node.index in requested]
    found = {node.index for node in selected}
    missing = sorted(requested - found)
    if missing:
        raise ValueError(f"unknown Beacon indices in {path}: {missing[:10]}")
    if not selected:
        raise ValueError(f"no Beacon indices selected from {path}")
    return selected


def get_json(url: str, timeout: float) -> dict[str, Any]:
    with NO_PROXY_OPENER.open(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: Any, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with NO_PROXY_OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_head(node: BeaconNode, timeout: float) -> dict[str, str]:
    payload = get_json(f"{node.url}/eth/v1/beacon/headers/head", timeout)
    data = payload.get("data", {})
    message = data.get("header", {}).get("message", {})
    return {
        "head_slot": str(message.get("slot", "")),
        "head_root": str(data.get("root", "")),
        "parent_root": str(message.get("parent_root", "")),
    }


def get_finality(node: BeaconNode, timeout: float) -> dict[str, str]:
    payload = get_json(f"{node.url}/eth/v1/beacon/states/head/finality_checkpoints", timeout)
    data = payload.get("data", {})
    return {
        "justified_epoch": str(data.get("current_justified", {}).get("epoch", "")),
        "finalized_epoch": str(data.get("finalized", {}).get("epoch", "")),
    }


def get_active_validator_indices(node: BeaconNode, timeout: float) -> list[str]:
    payload = get_json(
        f"{node.url}/eth/v1/beacon/states/head/validators?status=active_ongoing",
        timeout,
    )
    indices = [
        str(item.get("index"))
        for item in payload.get("data", [])
        if item.get("index") is not None and item.get("status") == "active_ongoing"
    ]
    if not indices:
        raise RuntimeError("Beacon API returned no active validators")
    return indices


def get_validator_liveness(
    node: BeaconNode,
    epoch: int,
    indices: list[str],
    timeout: float,
    batch_size: int,
) -> dict[str, bool]:
    liveness: dict[str, bool] = {}
    for offset in range(0, len(indices), batch_size):
        batch = indices[offset : offset + batch_size]
        payload = post_json(
            f"{node.url}/eth/v1/validator/liveness/{epoch}",
            batch,
            timeout,
        )
        for item in payload.get("data", []):
            index = item.get("index")
            if index is not None:
                liveness[str(index)] = bool(item.get("is_live"))
    return liveness


def get_header_by_slot(node: BeaconNode, slot: int, timeout: float) -> Optional[str]:
    payload = get_json(f"{node.url}/eth/v1/beacon/headers/{slot}", timeout)
    data = payload.get("data")
    if not data:
        return None
    return str(data.get("root", ""))


def get_block_by_slot(node: BeaconNode, slot: int, timeout: float) -> Optional[dict[str, Any]]:
    payload = get_json(f"{node.url}/eth/v2/beacon/blocks/{slot}", timeout)
    data = payload.get("data")
    if not data:
        return None
    return data.get("message")


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def collect_attestations(
    node: BeaconNode,
    slot: int,
    timeout: float,
    elapsed: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        block = get_block_by_slot(node, slot, timeout)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return rows
    if not block:
        return rows

    block_slot = parse_int(str(block.get("slot", slot)), slot)
    attestations = block.get("body", {}).get("attestations", []) or []
    now = utc_now()
    for index, attestation in enumerate(attestations):
        data = attestation.get("data", {})
        att_slot = parse_int(str(data.get("slot", "")), block_slot)
        rows.append(
            {
                "timestamp": now,
                "elapsed_sec": f"{elapsed:.3f}",
                "block_slot": block_slot,
                "attestation_slot": att_slot,
                "inclusion_delay_slots": block_slot - att_slot,
                "committee_index": data.get("index", ""),
                "source_epoch": data.get("source", {}).get("epoch", ""),
                "target_epoch": data.get("target", {}).get("epoch", ""),
                "attestation_index": index,
            }
        )
    return rows


def write_run_info(output_dir: Path, args: argparse.Namespace, status: str, samples: int, sampled: list[BeaconNode]) -> None:
    payload = {
        "status": status,
        "samples": samples,
        "updated_at": utc_now(),
        "interval_sec": args.interval,
        "beacon_sample": args.beacon_sample,
        "beacon_indices_file": str(args.beacon_indices_file) if args.beacon_indices_file else "",
        "expected_active_validators": args.expected_active_validators,
        "validator_liveness_batch_size": args.validator_liveness_batch_size,
        "sampled_beacons": [node.__dict__ for node in sampled],
    }
    (output_dir / "consensus_benchmark_run_info.json").write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    args = parse_args()
    if args.interval <= 0:
        print("--interval must be positive")
        return 2
    if args.reorg_depth < 0:
        print("--reorg-depth must be >= 0")
        return 2
    if args.expected_active_validators < 0:
        print("--expected-active-validators must be >= 0")
        return 2
    if args.validator_liveness_timeout <= 0:
        print("--validator-liveness-timeout must be positive")
        return 2
    if args.validator_liveness_batch_size <= 0:
        print("--validator-liveness-batch-size must be positive")
        return 2

    beacons = discover_beacons(args.compose_file)
    if not beacons:
        print(f"no beacon nodes discovered in {args.compose_file}")
        return 1
    sampled = (
        choose_indices(beacons, args.beacon_indices_file)
        if args.beacon_indices_file is not None
        else choose_sample(beacons, args.beacon_sample)
    )
    reference = next((node for node in beacons if node.index == args.reference_beacon_index), sampled[0])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "sampled_beacons.csv").write_text(
        "index,service,name,ip,asn,url\n"
        + "\n".join(
            f"{node.index},{node.service},{node.name},{node.ip},{node.asn},{node.url}" for node in sampled
        )
        + "\n"
    )

    stop = False

    def stop_handler(signum, frame) -> None:  # noqa: ARG001
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    started = time.monotonic()
    sample = 0
    seen_by_node: set[tuple[str, int]] = set()
    processed_attestation_slots: set[int] = set()
    canonical_roots: dict[int, str] = {}
    last_reorg_scan = 0.0
    last_attestation_slot = -1
    active_validator_indices: Optional[list[str]] = None
    last_liveness_epoch = -1
    next_liveness_retry = 0.0
    write_run_info(args.output_dir, args, "running", sample, sampled)

    try:
        while not stop:
            elapsed = time.monotonic() - started
            if args.duration and elapsed >= args.duration:
                break
            if args.samples and sample >= args.samples:
                break

            sample += 1
            now = utc_now()
            head_rows: list[dict[str, Any]] = []
            first_seen_rows: list[dict[str, Any]] = []
            reference_head_slot = 0

            for node in sampled:
                error = ""
                head = {"head_slot": "", "head_root": "", "parent_root": ""}
                try:
                    head = get_head(node, args.timeout)
                    root = head["head_root"]
                    if root and (root, node.index) not in seen_by_node:
                        seen_by_node.add((root, node.index))
                        first_seen_rows.append(
                            {
                                "timestamp": now,
                                "elapsed_sec": f"{elapsed:.3f}",
                                "beacon_index": node.index,
                                "beacon_name": node.name,
                                "asn": node.asn,
                                "head_slot": head["head_slot"],
                                "head_root": root,
                            }
                        )
                    if node.index == reference.index:
                        reference_head_slot = parse_int(head["head_slot"])
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)[:300]
                head_rows.append(
                    {
                        "sample": sample,
                        "timestamp": now,
                        "elapsed_sec": f"{elapsed:.3f}",
                        "beacon_index": node.index,
                        "beacon_name": node.name,
                        "asn": node.asn,
                        "url": node.url,
                        "head_slot": head["head_slot"],
                        "head_root": head["head_root"],
                        "parent_root": head["parent_root"],
                        "error": error,
                    }
                )

            append_csv(args.output_dir / "beacon_head_samples.csv", HEAD_FIELDS, head_rows)
            append_csv(args.output_dir / "block_first_seen.csv", FIRST_SEEN_FIELDS, first_seen_rows)

            finality_error = ""
            finality = {"justified_epoch": "", "finalized_epoch": ""}
            try:
                if reference_head_slot == 0:
                    reference_head_slot = parse_int(get_head(reference, args.timeout)["head_slot"])
                finality = get_finality(reference, args.timeout)
            except Exception as exc:  # noqa: BLE001
                finality_error = str(exc)[:300]
            current_epoch = reference_head_slot // 32 if reference_head_slot else ""
            finalized_epoch = parse_int(finality.get("finalized_epoch", ""))
            append_csv(
                args.output_dir / "finality_samples.csv",
                FINALITY_FIELDS,
                [
                    {
                        "sample": sample,
                        "timestamp": now,
                        "elapsed_sec": f"{elapsed:.3f}",
                        "reference_beacon": reference.name,
                        "head_slot": reference_head_slot or "",
                        "current_epoch": current_epoch,
                        "justified_epoch": finality.get("justified_epoch", ""),
                        "finalized_epoch": finality.get("finalized_epoch", ""),
                        "finality_lag": (current_epoch - finalized_epoch) if current_epoch != "" else "",
                        "error": finality_error,
                    }
                ],
            )

            if current_epoch != "" and current_epoch > 0:
                liveness_epoch = current_epoch - 1
                if liveness_epoch > last_liveness_epoch and elapsed >= next_liveness_retry:
                    liveness_error = ""
                    registry_validators = 0
                    queried_validators = 0
                    live_validators = 0
                    missed_validators = 0
                    participation_percent: Any = ""
                    try:
                        if active_validator_indices is None:
                            active_validator_indices = get_active_validator_indices(
                                reference,
                                args.validator_liveness_timeout,
                            )
                        registry_validators = len(active_validator_indices)
                        if (
                            args.expected_active_validators
                            and registry_validators != args.expected_active_validators
                        ):
                            raise RuntimeError(
                                "active validator count mismatch: "
                                f"observed={registry_validators}, "
                                f"expected={args.expected_active_validators}"
                            )
                        liveness = get_validator_liveness(
                            reference,
                            liveness_epoch,
                            active_validator_indices,
                            args.validator_liveness_timeout,
                            args.validator_liveness_batch_size,
                        )
                        queried_validators = len(liveness)
                        if queried_validators != registry_validators:
                            raise RuntimeError(
                                "validator liveness response count mismatch: "
                                f"queried={queried_validators}, registry={registry_validators}"
                            )
                        live_validators = sum(1 for is_live in liveness.values() if is_live)
                        missed_validators = registry_validators - live_validators
                        participation_percent = (
                            100.0 * live_validators / registry_validators
                            if registry_validators
                            else 0.0
                        )
                        last_liveness_epoch = liveness_epoch
                    except Exception as exc:  # noqa: BLE001
                        liveness_error = str(exc)[:300]
                        next_liveness_retry = elapsed + 30.0

                    append_csv(
                        args.output_dir / "validator_liveness.csv",
                        VALIDATOR_LIVENESS_FIELDS,
                        [
                            {
                                "sample": sample,
                                "timestamp": now,
                                "elapsed_sec": f"{elapsed:.3f}",
                                "epoch": liveness_epoch,
                                "registry_validators": registry_validators,
                                "queried_validators": queried_validators,
                                "live_validators": live_validators,
                                "missed_validators": missed_validators,
                                "participation_percent": (
                                    f"{participation_percent:.6f}"
                                    if participation_percent != ""
                                    else ""
                                ),
                                "error": liveness_error,
                            }
                        ],
                    )

            if reference_head_slot:
                start_slot = max(last_attestation_slot + 1, reference_head_slot - 4)
                for slot in range(start_slot, reference_head_slot + 1):
                    if slot in processed_attestation_slots:
                        continue
                    attestation_rows = collect_attestations(reference, slot, args.timeout, elapsed)
                    append_csv(args.output_dir / "attestation_inclusions.csv", ATTESTATION_FIELDS, attestation_rows)
                    processed_attestation_slots.add(slot)
                last_attestation_slot = max(last_attestation_slot, reference_head_slot)

            if args.reorg_depth and elapsed - last_reorg_scan >= args.reorg_scan_interval and reference_head_slot:
                last_reorg_scan = elapsed
                slot_rows: list[dict[str, Any]] = []
                reorg_rows: list[dict[str, Any]] = []
                start = max(0, reference_head_slot - args.reorg_depth)
                for slot in range(start, reference_head_slot + 1):
                    root = ""
                    error = ""
                    canonical = 0
                    try:
                        root = get_header_by_slot(reference, slot, args.timeout) or ""
                        canonical = 1 if root else 0
                    except Exception as exc:  # noqa: BLE001
                        error = str(exc)[:300]
                    if root:
                        old_root = canonical_roots.get(slot)
                        if old_root and old_root != root:
                            reorg_rows.append(
                                {
                                    "timestamp": now,
                                    "elapsed_sec": f"{elapsed:.3f}",
                                    "slot": slot,
                                    "old_root": old_root,
                                    "new_root": root,
                                }
                            )
                        canonical_roots[slot] = root
                    slot_rows.append(
                        {
                            "timestamp": now,
                            "elapsed_sec": f"{elapsed:.3f}",
                            "slot": slot,
                            "root": root,
                            "canonical": canonical,
                            "error": error,
                        }
                    )
                append_csv(args.output_dir / "canonical_slot_observations.csv", SLOT_OBSERVATION_FIELDS, slot_rows)
                append_csv(args.output_dir / "reorg_events.csv", REORG_FIELDS, reorg_rows)

            write_run_info(args.output_dir, args, "running", sample, sampled)
            deadline = time.monotonic() + args.interval
            while not stop:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.5, remaining))
    except Exception:
        write_run_info(args.output_dir, args, "failed", sample, sampled)
        raise

    write_run_info(args.output_dir, args, "complete", sample, sampled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
