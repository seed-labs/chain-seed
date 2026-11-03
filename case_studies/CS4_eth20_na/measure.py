#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "results"


def write_json(path: Path | str, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 30, check: bool = False) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout)
    out = {
        "cmd": cmd,
        "cwd": str(cwd) if cwd else None,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    if check and proc.returncode:
        raise RuntimeError(json.dumps(out, indent=2))
    return out


def dexec(container: str, *args: str, timeout: int = 20, check: bool = False) -> dict[str, Any]:
    return run(["docker", "exec", container, *args], timeout=timeout, check=check)


def http_get_json(container: str, url: str, timeout_seconds: int = 4) -> Any:
    result = dexec(container, "curl", "--max-time", str(timeout_seconds), "-s", url, timeout=timeout_seconds + 3)
    if result["returncode"]:
        raise RuntimeError(result["stderr"] or result["stdout"])
    return json.loads(result["stdout"])


def http_get_text(container: str, url: str, timeout_seconds: int = 4) -> str:
    result = dexec(container, "curl", "--max-time", str(timeout_seconds), "-s", url, timeout=timeout_seconds + 3)
    if result["returncode"]:
        raise RuntimeError(result["stderr"] or result["stdout"])
    return result["stdout"]


def wait_for_beacons(beacons: list[dict[str, Any]], max_seconds: int) -> dict[str, Any]:
    deadline = time.time() + max_seconds
    observations: list[dict[str, Any]] = []
    last_all_slots: dict[str, int] = {}
    while time.time() < deadline:
        row: dict[str, Any] = {"t": round(time.time(), 3), "beacons": {}}
        ready = 0
        advancing = 0
        for beacon in beacons:
            name = beacon["container"]
            try:
                health = dexec(name, "curl", "--max-time", "3", "-s", "-o", "/tmp/health.out", "-w", "%{http_code}", f"{beacon['api']}/eth/v1/node/health", timeout=8)
                health_code = int((health["stdout"] or "0").strip() or "0")
                head = http_get_json(name, f"{beacon['api']}/eth/v1/beacon/headers/head", timeout_seconds=3)
                slot = int(head["data"]["header"]["message"]["slot"])
                peers = http_get_json(name, f"{beacon['api']}/eth/v1/node/peers", timeout_seconds=3)
                peer_count = len(peers.get("data", []))
                prev = last_all_slots.get(name, -1)
                if slot > prev:
                    advancing += 1
                if health_code in (200, 206) and slot > 0:
                    ready += 1
                last_all_slots[name] = slot
                row["beacons"][name] = {"health": health_code, "slot": slot, "peers": peer_count}
            except Exception as exc:
                row["beacons"][name] = {"error": str(exc)[:240]}
        observations.append(row)
        if ready == len(beacons) and advancing >= max(1, len(beacons) // 2):
            time.sleep(14)
            # Check that all nodes continue to answer and most are near the same head.
            slots = []
            for beacon in beacons:
                try:
                    head = http_get_json(beacon["container"], f"{beacon['api']}/eth/v1/beacon/headers/head", timeout_seconds=3)
                    slots.append(int(head["data"]["header"]["message"]["slot"]))
                except Exception:
                    pass
            if len(slots) == len(beacons) and max(slots) - min(slots) <= 2 and max(slots) > 0:
                return {"ready": True, "observations": observations, "slots": slots}
        time.sleep(6)
    return {"ready": False, "observations": observations, "last_slots": last_all_slots}


def read_network_bytes(container: str) -> dict[str, int]:
    script = """python3 - <<'PY'\nfrom pathlib import Path\nrx=tx=0\nfor iface in Path('/sys/class/net').iterdir():\n    if iface.name == 'lo':\n        continue\n    try:\n        rx += int((iface/'statistics'/'rx_bytes').read_text().strip())\n        tx += int((iface/'statistics'/'tx_bytes').read_text().strip())\n    except Exception:\n        pass\nprint(f'{rx} {tx}')\nPY"""
    result = dexec(container, "sh", "-lc", script, timeout=10, check=True)
    a, b = result["stdout"].strip().split()[-2:]
    return {"rx_bytes": int(a), "tx_bytes": int(b)}


def collect_peer_counts(beacons: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for beacon in beacons:
        name = beacon["container"]
        try:
            peers = http_get_json(name, f"{beacon['api']}/eth/v1/node/peers", timeout_seconds=5).get("data", [])
            states = {}
            for peer in peers:
                states[peer.get("state", "unknown")] = states.get(peer.get("state", "unknown"), 0) + 1
            out[name] = {"count": len(peers), "states": states}
        except Exception as exc:
            out[name] = {"error": str(exc)[:240]}
    return out


def scrape_selected_metrics(beacons: list[dict[str, Any]]) -> dict[str, Any]:
    wanted_fragments = [
        "libp2p",
        "gossip",
        "beacon_processor",
        "block_delay",
        "sync_eth2",
        "network",
        "peer",
    ]
    out = {}
    for beacon in beacons:
        name = beacon["container"]
        try:
            text = http_get_text(name, beacon["metrics"], timeout_seconds=5)
            selected = []
            for line in text.splitlines():
                if line.startswith("#"):
                    continue
                low = line.lower()
                if any(fragment in low for fragment in wanted_fragments):
                    selected.append(line)
                if len(selected) >= 80:
                    break
            out[name] = {"available": True, "selected_lines": selected}
        except Exception as exc:
            out[name] = {"available": False, "error": str(exc)[:240]}
    return out


def sample_heads(beacons: list[dict[str, Any]], duration_seconds: int, interval_seconds: float) -> list[dict[str, Any]]:
    started = time.time()
    samples = []
    while time.time() - started < duration_seconds:
        now = time.time()
        row = {"t": round(now, 3), "dt": round(now - started, 3), "slots": {}}
        for beacon in beacons:
            name = beacon["container"]
            try:
                head = http_get_json(name, f"{beacon['api']}/eth/v1/beacon/headers/head", timeout_seconds=3)
                slot = int(head["data"]["header"]["message"]["slot"])
                root = head["data"].get("root")
                row["slots"][name] = {"slot": slot, "root": root}
            except Exception as exc:
                row["slots"][name] = {"error": str(exc)[:160]}
        samples.append(row)
        sleep_for = interval_seconds - (time.time() - now)
        if sleep_for > 0:
            time.sleep(sleep_for)
    return samples


def summarize_samples(samples: list[dict[str, Any]], beacons: list[dict[str, Any]]) -> dict[str, Any]:
    first_seen: dict[int, dict[str, float]] = {}
    errors = 0
    for row in samples:
        t = float(row["t"])
        for name, data in row["slots"].items():
            if "error" in data:
                errors += 1
                continue
            slot = int(data["slot"])
            first_seen.setdefault(slot, {})
            first_seen[slot].setdefault(name, t)
    spreads = []
    complete_slots = []
    for slot, seen in sorted(first_seen.items()):
        if len(seen) == len(beacons):
            values = list(seen.values())
            spread = max(values) - min(values)
            if slot > 0:
                spreads.append(spread)
                complete_slots.append(slot)
    def safe_mean(xs: list[float]) -> float | None:
        return round(statistics.mean(xs), 4) if xs else None
    def safe_median(xs: list[float]) -> float | None:
        return round(statistics.median(xs), 4) if xs else None
    def safe_p95(xs: list[float]) -> float | None:
        if not xs:
            return None
        ordered = sorted(xs)
        idx = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
        return round(ordered[idx], 4)
    latest_slots = []
    if samples:
        for data in samples[-1]["slots"].values():
            if "slot" in data:
                latest_slots.append(int(data["slot"]))
    return {
        "sample_count": len(samples),
        "errors": errors,
        "complete_slot_count": len(complete_slots),
        "complete_slots": complete_slots[:20],
        "propagation_spread_seconds": {
            "mean": safe_mean(spreads),
            "median": safe_median(spreads),
            "p95": safe_p95(spreads),
            "max": round(max(spreads), 4) if spreads else None,
        },
        "latest_slot_min": min(latest_slots) if latest_slots else None,
        "latest_slot_max": max(latest_slots) if latest_slots else None,
    }


def run_one(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest or RESULTS_DIR / f"scenario_manifest_tp{args.target_peers}.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["target_peers"] != args.target_peers:
        raise ValueError("manifest target_peers does not match --target-peers")
    beacons = manifest["beacons"]
    wait = wait_for_beacons(beacons, args.ready_timeout)
    if not wait.get("ready"):
        result = {"target_peers": args.target_peers, "ready": False, "wait": wait}
        write_json(RESULTS_DIR / f"eth20_na_tp{args.target_peers}_failed.json", result)
        return result
    before_bytes = {b["container"]: read_network_bytes(b["container"]) for b in beacons}
    before_peers = collect_peer_counts(beacons)
    before_metrics = scrape_selected_metrics(beacons)
    samples = sample_heads(beacons, args.measure_seconds, args.sample_interval)
    after_bytes = {b["container"]: read_network_bytes(b["container"]) for b in beacons}
    after_peers = collect_peer_counts(beacons)
    after_metrics = scrape_selected_metrics(beacons)
    per_beacon_bytes = {}
    for beacon in beacons:
        name = beacon["container"]
        per_beacon_bytes[name] = {
            "rx_delta": after_bytes[name]["rx_bytes"] - before_bytes[name]["rx_bytes"],
            "tx_delta": after_bytes[name]["tx_bytes"] - before_bytes[name]["tx_bytes"],
            "total_delta": (after_bytes[name]["rx_bytes"] - before_bytes[name]["rx_bytes"]) + (after_bytes[name]["tx_bytes"] - before_bytes[name]["tx_bytes"]),
        }
    total_network_delta = sum(row["total_delta"] for row in per_beacon_bytes.values())
    result = {
        "experiment": "eth20_na",
        "target_peers": args.target_peers,
        "ready": True,
        "manifest": manifest,
        "wait": wait,
        "measurement": {
            "duration_seconds": args.measure_seconds,
            "sample_interval_seconds": args.sample_interval,
            "summary": summarize_samples(samples, beacons),
            "peer_counts_before": before_peers,
            "peer_counts_after": after_peers,
            "network_bytes_before": before_bytes,
            "network_bytes_after": after_bytes,
            "network_byte_deltas": per_beacon_bytes,
            "aggregate_beacon_network_bytes_delta": total_network_delta,
            "aggregate_beacon_rx_bytes_delta": sum(row["rx_delta"] for row in per_beacon_bytes.values()),
            "aggregate_beacon_tx_bytes_delta": sum(row["tx_delta"] for row in per_beacon_bytes.values()),
            "selected_metrics_before": before_metrics,
            "selected_metrics_after": after_metrics,
        },
        "raw_samples": samples,
    }
    write_json(RESULTS_DIR / f"eth20_na_tp{args.target_peers}.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure traffic and sampled head spread across Beacon clients.")
    parser.add_argument("--target-peers", type=int, required=True)
    parser.add_argument("--manifest", help="Manifest written by build.py")
    parser.add_argument("--ready-timeout", type=int, default=600)
    parser.add_argument("--measure-seconds", type=int, default=180)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_one(args)
    print(json.dumps({
        "target_peers": result.get("target_peers"),
        "ready": result.get("ready"),
        "summary": result.get("measurement", {}).get("summary"),
        "aggregate_beacon_network_bytes_delta": result.get("measurement", {}).get("aggregate_beacon_network_bytes_delta"),
        "result_file": str((RESULTS_DIR / (f"eth20_na_tp{args.target_peers}.json" if result.get("ready") else f"eth20_na_tp{args.target_peers}_failed.json")).resolve()),
    }, indent=2, sort_keys=True))
    return 0 if result.get("ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
