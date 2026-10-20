#!/usr/bin/env python3
"""Collect block-production and transaction-count samples for E10 experiments."""

from __future__ import annotations

import argparse
import csv
import json
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "transaction_generator"))
from compose_endpoints import discover_beacon_api_url, discover_execution_rpc_url


SCRIPT_DIR = Path(__file__).resolve().parent
ETHEREUM_DIR = SCRIPT_DIR.parent
DEFAULT_COMPOSE_FILE = ETHEREUM_DIR / "output" / "docker-compose.yml"

CSV_FIELDS = [
    "sample",
    "timestamp",
    "elapsed_sec",
    "new_block",
    "block_number",
    "block_hash",
    "parent_hash",
    "block_time_unix",
    "tx_count",
    "gas_used",
    "gas_limit",
    "gas_used_percent",
    "block_size_bytes",
    "base_fee_per_gas",
    "head_slot",
    "justified_epoch",
    "finalized_epoch",
    "error",
]

NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Poll Geth/Beacon APIs and write block tx-count samples."
    )
    parser.add_argument("-f", "--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--rpc-url", help="Execution JSON-RPC URL.")
    parser.add_argument("--beacon-url", help="Beacon HTTP API URL.")
    parser.add_argument("-i", "--interval", type=int, default=12)
    parser.add_argument("--duration", type=int, default=0, help="0 means run until stopped.")
    parser.add_argument("-n", "--samples", type=int, default=0, help="0 means run until stopped.")
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument(
        "--max-consecutive-errors",
        type=int,
        default=0,
        help="Exit non-zero after N consecutive RPC failures; 0 disables the limit.",
    )
    parser.add_argument(
        "--require-success",
        action="store_true",
        help="Exit non-zero if no successful execution-layer sample was collected.",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hex_to_int(value: Optional[str]) -> int:
    if not value:
        return 0
    return int(value, 16)


def post_json(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with NO_PROXY_OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str, timeout: int) -> Dict[str, Any]:
    with NO_PROXY_OPENER.open(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def rpc_call(rpc_url: str, method: str, params: list[Any], timeout: int) -> Any:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    response = post_json(rpc_url, payload, timeout)
    if "error" in response:
        raise RuntimeError(response["error"])
    return response.get("result")


def discover_rpc_url(compose_file: Path) -> str:
    return discover_execution_rpc_url(compose_file)


def discover_beacon_url(compose_file: Path) -> Optional[str]:
    return discover_beacon_api_url(compose_file)


def beacon_state(beacon_url: Optional[str], timeout: int) -> Dict[str, str]:
    if not beacon_url:
        return {}

    state: Dict[str, str] = {}
    try:
        header = get_json(f"{beacon_url}/eth/v1/beacon/headers/head", timeout)
        state["head_slot"] = str(
            header.get("data", {}).get("header", {}).get("message", {}).get("slot", "")
        )
    except Exception:
        state["head_slot"] = ""

    try:
        finality = get_json(
            f"{beacon_url}/eth/v1/beacon/states/head/finality_checkpoints",
            timeout,
        )
        data = finality.get("data", {})
        state["justified_epoch"] = str(data.get("current_justified", {}).get("epoch", ""))
        state["finalized_epoch"] = str(data.get("finalized", {}).get("epoch", ""))
    except Exception:
        state.setdefault("justified_epoch", "")
        state.setdefault("finalized_epoch", "")

    return state


def block_row(
    sample: int,
    started_at: float,
    block: Optional[Dict[str, Any]],
    new_block: bool,
    beacon: Dict[str, str],
    error: str = "",
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "sample": sample,
        "timestamp": utc_now(),
        "elapsed_sec": f"{time.monotonic() - started_at:.3f}",
        "new_block": int(new_block),
        "block_number": "",
        "block_hash": "",
        "parent_hash": "",
        "block_time_unix": "",
        "tx_count": "",
        "gas_used": "",
        "gas_limit": "",
        "gas_used_percent": "",
        "block_size_bytes": "",
        "base_fee_per_gas": "",
        "head_slot": beacon.get("head_slot", ""),
        "justified_epoch": beacon.get("justified_epoch", ""),
        "finalized_epoch": beacon.get("finalized_epoch", ""),
        "error": error,
    }
    if block:
        gas_used = hex_to_int(block.get("gasUsed"))
        gas_limit = hex_to_int(block.get("gasLimit"))
        row.update(
            {
                "block_number": hex_to_int(block.get("number")),
                "block_hash": block.get("hash", ""),
                "parent_hash": block.get("parentHash", ""),
                "block_time_unix": hex_to_int(block.get("timestamp")),
                "tx_count": len(block.get("transactions") or []),
                "gas_used": gas_used,
                "gas_limit": gas_limit,
                "gas_used_percent": (
                    f"{100.0 * gas_used / gas_limit:.6f}" if gas_limit else ""
                ),
                "block_size_bytes": hex_to_int(block.get("size")),
                "base_fee_per_gas": hex_to_int(block.get("baseFeePerGas")),
            }
        )
    return row


def main() -> int:
    args = parse_args()
    if args.interval < 1:
        print("--interval must be >= 1", file=sys.stderr)
        return 2
    if args.max_consecutive_errors < 0:
        print("--max-consecutive-errors must be >= 0", file=sys.stderr)
        return 2

    rpc_url = args.rpc_url or discover_rpc_url(args.compose_file)
    beacon_url = args.beacon_url or discover_beacon_url(args.compose_file)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    stop = False

    def stop_handler(signum, frame) -> None:  # noqa: ARG001
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    print(f"execution_rpc={rpc_url}")
    print(f"beacon_api={beacon_url or '<none>'}")
    print(f"writing block metrics to {args.output}")

    started_at = time.monotonic()
    sample = 0
    last_seen_block = -1
    successful_samples = 0
    consecutive_errors = 0

    with args.output.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if handle.tell() == 0:
            writer.writeheader()

        while not stop:
            if args.duration and time.monotonic() - started_at >= args.duration:
                break
            if args.samples and sample >= args.samples:
                break

            sample += 1
            rows = []
            try:
                current = hex_to_int(rpc_call(rpc_url, "eth_blockNumber", [], args.timeout))
                beacon = beacon_state(beacon_url, args.timeout)
                if last_seen_block < 0:
                    last_seen_block = max(0, current - 1)
                if current > last_seen_block:
                    for number in range(last_seen_block + 1, current + 1):
                        block = rpc_call(rpc_url, "eth_getBlockByNumber", [hex(number), False], args.timeout)
                        rows.append(block_row(sample, started_at, block, True, beacon))
                    last_seen_block = current
                else:
                    block = rpc_call(rpc_url, "eth_getBlockByNumber", [hex(current), False], args.timeout)
                    rows.append(block_row(sample, started_at, block, False, beacon))
                successful_samples += 1
                consecutive_errors = 0
            except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
                consecutive_errors += 1
                rows.append(block_row(sample, started_at, None, False, {}, str(exc)[:500]))

            writer.writerows(rows)
            handle.flush()
            print(f"sample={sample} rows={len(rows)} timestamp={utc_now()}", flush=True)

            if (
                args.max_consecutive_errors > 0
                and consecutive_errors >= args.max_consecutive_errors
            ):
                print(
                    f"execution RPC failed {consecutive_errors} consecutive samples",
                    file=sys.stderr,
                )
                return 1

            deadline = time.monotonic() + args.interval
            while not stop:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1.0, remaining))

    if args.require_success and successful_samples == 0:
        print("no successful execution-layer samples were collected", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
