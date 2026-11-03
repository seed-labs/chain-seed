#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Dict, Iterable, List

SCRIPT_DIR = Path(__file__).resolve().parent
AUTHOR_REPO = "https://github.com/taro-tsuchiya/BlockchainAmplification"

TESTS = {
    "basis": {
        "tree": "modified",
        "package": "eth/block-validation",
        "run": "TestAmplificationBasis",
        "csv": None,
        "description": "author sanity test for the amplification transaction behavior",
    },
    "amplification": {
        "tree": "modified",
        "package": "eth/block-validation",
        "run": "TestAmplificationEvictsMempoolChangeNumAddr",
        "csv": "amplification_change_addr.csv",
        "description": "Amplification curve: vary attack accounts from 40 to 2000",
    },
    "baseline": {
        "tree": "unmodified",
        "package": "eth/block-validation",
        "run": "TestBasicEvictsMempoolChangeNumAddr",
        "csv": "baseline_change_addr.csv",
        "description": "Baseline curve: valid costly attack transactions",
    },
    "mempurge": {
        "tree": "unmodified",
        "package": "eth/block-validation",
        "run": "TestMemPurgeEvictsMempoolChangeNumAddr",
        "csv": "mempurge_change_addr.csv",
        "description": "MemPurge curve: future-transaction attack",
    },
}


def write_json(path: str | Path, payload) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_command(command: List[str], cwd: Path | None = None, env: Dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(command), f"(cwd={cwd})" if cwd else "")
    return subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, text=True, check=True)


def ensure_artifact(args) -> Path:
    artifact_dir = Path(args.artifact_dir).expanduser().resolve()
    if artifact_dir.exists():
        return artifact_dir
    if not args.clone_if_missing:
        raise FileNotFoundError(
            f"artifact directory does not exist: {artifact_dir}. "
            "Clone the author artifact first or pass --clone-if-missing."
        )
    run_command(["git", "clone", "--depth", "1", "--filter=blob:none", args.repo_url, str(artifact_dir)])
    run_command(["git", "-C", str(artifact_dir), "checkout", "-f", "HEAD"])
    return artifact_dir


def resolve_go(go_bin: str | None) -> str:
    candidates: List[str] = []
    if go_bin:
        candidates.append(go_bin)
    env_go = os.environ.get("GO_BIN")
    if env_go:
        candidates.append(env_go)
    candidates.extend(["/tmp/go/bin/go", "go"])
    for candidate in candidates:
        path = shutil.which(candidate) if os.path.basename(candidate) == candidate else candidate
        if path and Path(path).exists():
            return path
    raise FileNotFoundError("Go was not found. Install Go 1.20-1.22 or pass --go-bin /path/to/go.")


def git_commit(artifact_dir: Path) -> str | None:
    try:
        cp = subprocess.run(
            ["git", "-C", str(artifact_dir), "rev-parse", "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return cp.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def go_version(go_bin: str) -> str:
    cp = subprocess.run([go_bin, "version"], text=True, stdout=subprocess.PIPE, check=True)
    return cp.stdout.strip()


def go_env(go_bin: str) -> Dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{str(Path(go_bin).parent)}:{env.get('PATH', '')}"
    env.setdefault("GOCACHE", str(Path("/tmp/go-cache").resolve()))
    env.setdefault("GOMODCACHE", str(Path("/tmp/go-mod-cache").resolve()))
    return env


def build_modified_geth(artifact_dir: Path, go_bin: str) -> str:
    modified_dir = artifact_dir / "modified"
    run_command(["make", "geth"], cwd=modified_dir, env=go_env(go_bin))
    binary = modified_dir / "build" / "bin" / "geth"
    if not binary.exists():
        raise FileNotFoundError(f"modified geth binary was not produced: {binary}")
    return str(binary)


def selected_tests(value: str) -> List[str]:
    if value == "all":
        return ["basis", "amplification", "baseline", "mempurge"]
    out = [chunk.strip() for chunk in value.split(",") if chunk.strip()]
    unknown = [name for name in out if name not in TESTS]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown test(s): {', '.join(unknown)}")
    return out


def read_rows(path: Path) -> List[Dict[str, int]]:
    rows: List[Dict[str, int]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append({key: int(value) for key, value in row.items()})
    return rows


def monotone_nonincreasing(values: Iterable[int]) -> bool:
    vals = list(values)
    return all(a >= b for a, b in zip(vals, vals[1:]))


def summarize_csv(name: str, source: Path, copied: Path) -> Dict[str, object]:
    rows = read_rows(source)
    summary: Dict[str, object] = {
        "source_csv": str(source),
        "copied_csv": str(copied),
        "row_count": len(rows),
        "first_row": rows[0] if rows else None,
        "last_row": rows[-1] if rows else None,
        "sample_rows": [row for row in rows if row.get("x") in {40, 80, 160, 320, 1000, 2000}],
    }
    if rows and name == "amplification":
        honest_pending = [row["honestPendingCounts"] for row in rows]
        honest_block = [row["honestBlockTxsCounts"] for row in rows]
        attacker_block = [row["attackerBlockTxsCounts"] for row in rows]
        summary["checks"] = {
            "honest_pending_nonincreasing": monotone_nonincreasing(honest_pending),
            "honest_block_nonincreasing": monotone_nonincreasing(honest_block),
            "attacker_block_always_zero": all(value == 0 for value in attacker_block),
            "final_honest_pending": honest_pending[-1],
            "final_honest_block": honest_block[-1],
        }
    return summary


def assert_success(payload: Dict[str, object]) -> None:
    failures: List[str] = []
    tests = payload.get("tests", {})
    if not isinstance(tests, dict):
        raise AssertionError("missing tests payload")
    amp = tests.get("amplification")
    if isinstance(amp, dict) and amp.get("csv_summary"):
        checks = amp["csv_summary"].get("checks", {})
        if not checks.get("honest_pending_nonincreasing"):
            failures.append("amplification honest pending count is not non-increasing")
        if not checks.get("honest_block_nonincreasing"):
            failures.append("amplification honest block count is not non-increasing")
        if not checks.get("attacker_block_always_zero"):
            failures.append("amplification attacker transactions were included in a block")
        if checks.get("final_honest_pending") != 0:
            failures.append("final amplification point did not evict all honest pending transactions")
        if checks.get("final_honest_block") != 0:
            failures.append("final amplification point did not remove honest transactions from the block")
    if failures:
        raise AssertionError("; ".join(failures))


def run_go_tests(args, artifact_dir: Path, go_bin: str, names: List[str]) -> Dict[str, object]:
    env = go_env(go_bin)

    results_dir = Path(args.results_dir).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    tests: Dict[str, object] = {}
    for name in names:
        spec = TESTS[name]
        workdir = artifact_dir / spec["tree"] / spec["package"]
        csv_name = spec["csv"]
        if csv_name and not args.skip_go_test:
            old_csv = workdir / csv_name
            if old_csv.exists():
                old_csv.unlink()

        if not args.skip_go_test:
            run_command([go_bin, "test", "-count=1", "-v", f"-run={spec['run']}", "-timeout=0s"], cwd=workdir, env=env)

        test_payload: Dict[str, object] = {
            "description": spec["description"],
            "tree": spec["tree"],
            "package": spec["package"],
            "go_test": spec["run"],
            "status": "not-run-skip-go-test" if args.skip_go_test else "passed",
        }
        if args.csv_provenance:
            test_payload["csv_provenance"] = args.csv_provenance
        if csv_name:
            source = workdir / csv_name
            copied = results_dir / f"author_{csv_name}"
            if source.exists():
                shutil.copy2(source, copied)
                test_payload["csv_summary"] = summarize_csv(name, source, copied)
            elif args.skip_go_test and copied.exists():
                test_payload["status"] = "summarized-existing-result-csv"
                test_payload["csv_summary"] = summarize_csv(name, copied, copied)
            else:
                raise FileNotFoundError(f"expected CSV was not produced: {source}")
        tests[name] = test_payload
    return tests


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Blockchain Amplification authors' modified-geth artifact tests.")
    parser.add_argument("--artifact-dir", default="/tmp/BlockchainAmplification")
    parser.add_argument("--repo-url", default=AUTHOR_REPO)
    parser.add_argument("--clone-if-missing", action="store_true")
    parser.add_argument("--go-bin")
    parser.add_argument("--tests", type=selected_tests, default=selected_tests("basis,amplification"))
    parser.add_argument("--skip-go-test", action="store_true", help="Only summarize already generated CSV files.")
    parser.add_argument("--build-modified-geth", action="store_true", help="Compile modified/build/bin/geth for use with SEED --custom-geth.")
    parser.add_argument("--csv-provenance", help="Optional note explaining where an existing result CSV came from.")
    parser.add_argument("--results-dir", default=str(SCRIPT_DIR / "results"))
    parser.add_argument("--output", default=str(SCRIPT_DIR / "results" / "author_modified_geth_results.json"))
    parser.add_argument("--assert-success", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    artifact_dir = ensure_artifact(args)
    go_bin = resolve_go(args.go_bin)
    payload: Dict[str, object] = {
        "reference": "Blockchain Amplification Attack",
        "reference_url": "https://doi.org/10.1145/3711697",
        "artifact_url": AUTHOR_REPO,
        "artifact_dir": str(artifact_dir),
        "artifact_commit": git_commit(artifact_dir),
        "go_version": go_version(go_bin),
        "experiment_description": "Modified Geth txpool and block-validation tests",
        "workload_parameters": {
            "validator_count": 1,
            "honest_accounts": 80,
            "honest_transactions_per_account": 64,
            "honest_transactions_total": 5120,
            "attack_accounts": "40..2000 step 40",
            "attack_transactions_per_account": 32,
            "txpool_global_slots": 5120,
            "txpool_global_queue": 1024,
        },
    }
    if args.build_modified_geth:
        payload["modified_geth_binary"] = build_modified_geth(artifact_dir, go_bin)
    payload["tests"] = run_go_tests(args, artifact_dir, go_bin, args.tests)
    if args.assert_success:
        assert_success(payload)
        payload["assert_success"] = True
    write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
