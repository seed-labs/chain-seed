#!/usr/bin/env python3
# encoding: utf-8

import argparse
import sys
import time

import requests


def _get_head_epoch(base_url: str, timeout: float) -> int:
    resp = requests.get("{}/eth/v1/beacon/headers/head".format(base_url), timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    slot_str = (
        payload.get("data", {})
        .get("header", {})
        .get("message", {})
        .get("slot", "0")
    )
    slot = int(slot_str)
    return slot // 32


def _get_validators(base_url: str, timeout: float) -> list[dict]:
    resp = requests.get("{}/eth/v1/beacon/states/head/validators".format(base_url), timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []
    return data


def run_monitor(
    base_url: str,
    rank: int,
    timeout_secs: int,
    interval_secs: int,
    http_timeout_secs: int,
) -> int:
    start_time = time.time()
    pending_seen = False
    active_seen = False
    watched_index = None
    last_status = None
    last_epoch_printed = None

    while True:
        elapsed = int(time.time() - start_time)
        if elapsed > timeout_secs:
            print("TIMEOUT after {} sec".format(timeout_secs))
            return 2

        try:
            epoch = _get_head_epoch(base_url, timeout=http_timeout_secs)
            validators = _get_validators(base_url, timeout=http_timeout_secs)
            validators_sorted = sorted(validators, key=lambda v: int(v.get("index", 0)))
            count = len(validators_sorted)

            if count < rank:
                if epoch != last_epoch_printed:
                    print("t={}s epoch={} validators={} waiting_for_validator_at_running_active rank={}".format(elapsed, epoch, count, rank))
                    last_epoch_printed = epoch
                time.sleep(interval_secs)
                continue

            entry = validators_sorted[rank - 1]
            index = int(entry.get("index"))
            status = str(entry.get("status", "")).lower()

            if watched_index is None:
                watched_index = index
            if index != watched_index:
                print("t={}s epoch={} rank={} index_changed {} -> {}".format(elapsed, epoch, rank, watched_index, index))
                watched_index = index

            if last_status != status:
                print("t={}s epoch={} validator_index={} status {} -> {}".format(elapsed, epoch, watched_index, last_status, status))
                last_status = status
            else:
                if epoch != last_epoch_printed:
                    print("t={}s epoch={} validator_index={} status={}".format(elapsed, epoch, watched_index, status))
                    last_epoch_printed = epoch

            if status.startswith("pending"):
                pending_seen = True
            if status.startswith("active"):
                active_seen = True

            if pending_seen and active_seen:
                print("OK: validator_index={} transitioned pending -> active".format(watched_index))
                return 0

        except Exception as e:
            print("t={}s error: {}".format(elapsed, e))

        time.sleep(interval_secs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beacon-api", default="http://10.151.0.72:8000")
    parser.add_argument("--rank", type=int, default=10)
    parser.add_argument("--timeout-secs", type=int, default=7200)
    parser.add_argument("--interval-secs", type=int, default=12)
    parser.add_argument("--http-timeout-secs", type=int, default=10)
    args = parser.parse_args()

    return run_monitor(
        base_url=args.beacon_api,
        rank=args.rank,
        timeout_secs=args.timeout_secs,
        interval_secs=args.interval_secs,
        http_timeout_secs=args.http_timeout_secs,
    )


if __name__ == "__main__":
    sys.exit(main())
