#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from chainseed.testing import EthereumRuntimeTest


DEPOSIT_CONTRACT = "0x00000000219ab540356cBB839Cbe05303d7705Fa"
VALIDATOR_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
EXPECTED_GENESIS_VALIDATORS = 9
EXPECTED_VALIDATOR_RANK = EXPECTED_GENESIS_VALIDATORS + 1
DEPOSIT_RESULT_FILE = "/tmp/e09_deposit_result.json"


def service_name(service: object) -> str:
    return getattr(service, "name", str(service))


def record(
    test: EthereumRuntimeTest,
    name: str,
    service: object,
    command: str,
    ok: bool,
    stdout: str = "",
    stderr: str = "",
) -> Dict[str, object]:
    result = {
        "name": name,
        "service": service_name(service),
        "command": command,
        "exit": 0 if ok else 1,
        "stdout": stdout[-1000:],
        "stderr": stderr[-1000:],
        "status": "passed" if ok else "failed",
    }
    test.results.append(result)
    return result


def compose_cp(test: EthereumRuntimeTest, name: str, source: Path, service: object, destination: str) -> bool:
    target = "{}:{}".format(service_name(service), destination)
    result = subprocess.run(
        ["docker", "compose", "-f", str(test.compose_file), "cp", str(source), target],
        cwd=str(test.compose_file.parent),
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    record(
        test,
        name,
        service,
        "docker compose cp {} {}".format(source, target),
        result.returncode == 0,
        result.stdout,
        result.stderr,
    )
    return result.returncode == 0


def get_json_file(test: EthereumRuntimeTest, service: object, path: str) -> Optional[Dict[str, Any]]:
    result = test.exec(service, "cat {}".format(shlex.quote(path)), timeout=30)
    if result["exit"] != 0:
        record(test, "E09 deposit result file exists", service, result["command"], False, str(result["stdout"]), str(result["stderr"]))
        return None
    try:
        data = json.loads(str(result["stdout"]))
    except json.JSONDecodeError as exc:
        record(test, "E09 deposit result file is valid JSON", service, result["command"], False, str(result["stdout"]), str(exc))
        return None
    record(test, "E09 deposit result file is valid JSON", service, result["command"], True, json.dumps(data, sort_keys=True))
    return data


def read_optional_json_file(test: EthereumRuntimeTest, service: object, path: str) -> Optional[Dict[str, Any]]:
    result = test.exec(service, "cat {}".format(shlex.quote(path)), timeout=30)
    if result["exit"] != 0:
        return None
    try:
        return json.loads(str(result["stdout"]))
    except json.JSONDecodeError:
        return None


def deposit_result_is_successful(data: Optional[Dict[str, Any]]) -> bool:
    if not data:
        return False
    try:
        deposit_value = int(data.get("deposit_value_wei", "0"))
        fee_paid = int(data.get("fee_paid_wei", "0"))
        balance_before = int(data.get("balance_before_wei", "0"))
        balance_after = int(data.get("balance_after_wei", "0"))
        return (
            data.get("success") is True
            and int(data.get("status", 0)) == 1
            and str(data.get("tx_hash", "")).startswith("0x")
            and str(data.get("transaction_to", "")).lower() == DEPOSIT_CONTRACT.lower()
            and int(data.get("transaction_value_wei", "0")) == 32 * 10**18
            and deposit_value == 32 * 10**18
            and balance_before - balance_after == deposit_value + fee_paid
        )
    except (TypeError, ValueError):
        return False


def validate_deposit_result(test: EthereumRuntimeTest, service: object, data: Optional[Dict[str, Any]]) -> bool:
    ok = deposit_result_is_successful(data)
    record(
        test,
        "E09 32 ETH deposit transaction succeeded",
        service,
        "validate {}".format(DEPOSIT_RESULT_FILE),
        ok,
        json.dumps(data or {}, sort_keys=True),
    )
    return ok


def manifest_ci_test_program_command() -> str:
    manifest = Path(os.environ.get("TEST_RUNNER_MANIFEST", Path(__file__).with_name("example.yaml")))
    try:
        import yaml
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except Exception:
        return "all"
    if not isinstance(data, dict):
        return "all"
    ci_cfg = data.get("ci", {})
    if not isinstance(ci_cfg, dict):
        return "all"
    return str(ci_cfg.get("test_program_command", "all"))


def default_require_activation() -> bool:
    command = os.environ.get("TEST_RUNNER_COMMAND", "")
    if command != "all":
        return False
    if os.environ.get("GITHUB_ACTIONS") == "true" and manifest_ci_test_program_command() == "test":
        return False
    return True


def request_json(url: str, timeout: int = 10) -> Dict[str, Any]:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def head_epoch(base_url: str) -> int:
    payload = request_json("{}/eth/v1/beacon/headers/head".format(base_url))
    slot = int(payload.get("data", {}).get("header", {}).get("message", {}).get("slot", "0"))
    return slot // 32


def validators(base_url: str) -> list[Dict[str, Any]]:
    payload = request_json("{}/eth/v1/beacon/states/head/validators".format(base_url))
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []
    return sorted(data, key=lambda item: int(item.get("index", 0)))


def wait_for_validator_count(
    test: EthereumRuntimeTest,
    name: str,
    beacon_service: object,
    base_url: str,
    minimum: int,
    *,
    retries: int = 60,
    interval: int = 5,
) -> int:
    last_count = 0
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            entries = validators(base_url)
            last_count = len(entries)
            if last_count >= minimum:
                record(
                    test,
                    name,
                    beacon_service,
                    "GET /eth/v1/beacon/states/head/validators",
                    True,
                    "validators={} attempts={}".format(last_count, attempt),
                )
                return last_count
        except Exception as exc:
            last_error = str(exc)
        if attempt < retries:
            time.sleep(interval)
    record(
        test,
        name,
        beacon_service,
        "GET /eth/v1/beacon/states/head/validators",
        False,
        "validators={}".format(last_count),
        last_error,
    )
    return last_count


def wait_for_validator_activation(
    test: EthereumRuntimeTest,
    beacon_service: object,
    base_url: str,
    rank: int,
    timeout_secs: int,
    interval_secs: int,
) -> bool:
    start_time = time.time()
    pending_seen = False
    active_seen = False
    watched_index: Optional[int] = None
    last_status: Optional[str] = None
    last_message = ""
    last_error = ""

    while time.time() - start_time <= timeout_secs:
        elapsed = int(time.time() - start_time)
        try:
            epoch = head_epoch(base_url)
            entries = validators(base_url)
            count = len(entries)
            if count < rank:
                last_message = "t={}s epoch={} validators={} waiting_for_rank={}".format(elapsed, epoch, count, rank)
            else:
                entry = entries[rank - 1]
                watched_index = int(entry.get("index", rank - 1))
                status = str(entry.get("status", "")).lower()
                balance = entry.get("balance")
                if status != last_status:
                    last_message = "t={}s epoch={} validator_index={} status {} -> {} balance={}".format(
                        elapsed,
                        epoch,
                        watched_index,
                        last_status,
                        status,
                        balance,
                    )
                    last_status = status
                else:
                    last_message = "t={}s epoch={} validator_index={} status={} balance={}".format(
                        elapsed,
                        epoch,
                        watched_index,
                        status,
                        balance,
                    )
                if status.startswith("pending"):
                    pending_seen = True
                if status.startswith("active"):
                    active_seen = True
                    record(
                        test,
                        "E09 validator-at-running reached active state",
                        beacon_service,
                        "monitor beacon validator rank {}".format(rank),
                        True,
                        "validator_index={} status={} pending_seen={} active_seen={}".format(
                            watched_index,
                            status,
                            pending_seen,
                            active_seen,
                        ),
                    )
                    return True
        except Exception as exc:
            last_error = str(exc)
            last_message = "error: {}".format(exc)
        time.sleep(interval_secs)

    record(
        test,
        "E09 validator-at-running reached active state",
        beacon_service,
        "monitor beacon validator rank {}".format(rank),
        False,
        "last={} pending_seen={} active_seen={}".format(last_message, pending_seen, active_seen),
        last_error,
    )
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the E09 validator-at-running workflow.")
    parser.add_argument("--registry-timeout-secs", type=int, default=1800)
    parser.add_argument("--activation-timeout-secs", type=int, default=7200)
    parser.add_argument("--activation-interval-secs", type=int, default=12)
    parser.add_argument(
        "--require-activation",
        action="store_true",
        default=default_require_activation(),
        help="also wait for the new validator to enter the beacon registry and become active",
    )
    args = parser.parse_args()
    if args.registry_timeout_secs < 1:
        parser.error("--registry-timeout-secs must be >= 1")
    if args.activation_timeout_secs < 1:
        parser.error("--activation-timeout-secs must be >= 1")
    if args.activation_interval_secs < 1:
        parser.error("--activation-interval-secs must be >= 1")
    return args


def main() -> int:
    args = parse_args()
    test = EthereumRuntimeTest(__file__)

    geth_nodes = test.require_ethereum_services(
        "E09 has POS Geth execution nodes",
        minimum_count=1,
        class_contains="Ethereum-POS-Geth",
        consensus="POS",
    )
    beacon_nodes = test.require_ethereum_services(
        "E09 has POS Lighthouse beacon nodes",
        minimum_count=1,
        class_contains="Ethereum-POS-Beacon",
        consensus="POS",
    )
    test.require_ethereum_services(
        "E09 still has 9 genesis validator clients",
        expected_count=EXPECTED_GENESIS_VALIDATORS,
        class_contains="Ethereum-POS-Validator",
        role="validator_at_genesis",
        consensus="POS",
    )
    validator_nodes = test.require_ethereum_services(
        "E09 has one validator-at-running client node",
        expected_count=1,
        class_contains="Ethereum-POS-Validator-AtRunning",
        role="validator_at_running",
        consensus="POS",
    )

    if not geth_nodes or not beacon_nodes or not validator_nodes:
        test.write_summary("e09-validator-at-running-runtime-test.json")
        return test.exit_code()

    geth = geth_nodes[0]
    beacon = beacon_nodes[0]
    validator_node = validator_nodes[0]
    beacon_api = "http://{}:8000".format(beacon.address)

    test.exec_check(
        "E09 deposit contract exists on execution layer",
        geth,
        'geth attach --exec \'eth.getCode("{}").length > 2\' | grep -q true'.format(DEPOSIT_CONTRACT),
        retries=20,
        interval=3,
        timeout=60,
    )
    test.exec_check(
        "E09 validator-at-running node has bootstrap files",
        validator_node,
        "test -s /tmp/withdraw-address && test -s /tmp/seed.pass && test -s /tmp/vc/local-testnet/testnet/genesis.ssz && ls /tmp/keystore/UTC--* >/dev/null",
        retries=60,
        interval=5,
        timeout=60,
    )
    wait_for_validator_count(
        test,
        "E09 beacon API reports the 9 genesis validators before deposit",
        beacon,
        beacon_api,
        EXPECTED_GENESIS_VALIDATORS,
        retries=60,
        interval=5,
    )

    deposit_data = read_optional_json_file(test, validator_node, DEPOSIT_RESULT_FILE)
    setup_succeeded = deposit_result_is_successful(deposit_data)
    if setup_succeeded:
        record(
            test,
            "E09 setup script skipped because deposit result already exists",
            validator_node,
            "read {}".format(DEPOSIT_RESULT_FILE),
            True,
            json.dumps(deposit_data, sort_keys=True),
        )
    else:
        script_path = Path(__file__).resolve().parent / "vc_start_at_running.sh"
        if compose_cp(test, "E09 setup script copied into validator-at-running node", script_path, validator_node, "/tmp/vc_start_at_running.sh"):
            test.exec_check(
                "E09 setup script is executable",
                validator_node,
                "chmod +x /tmp/vc_start_at_running.sh && test -x /tmp/vc_start_at_running.sh",
                retries=1,
                timeout=30,
            )

        setup_command = "E09_VALIDATOR_MNEMONIC={} bash /tmp/vc_start_at_running.sh".format(
            shlex.quote(VALIDATOR_MNEMONIC)
        )
        setup_result = test.exec(validator_node, setup_command, timeout=900)
        setup_succeeded = setup_result["exit"] == 0
        record(
            test,
            "E09 setup script creates/imports validator and sends deposit",
            validator_node,
            setup_command,
            setup_succeeded,
            str(setup_result["stdout"]),
            str(setup_result["stderr"]),
        )
        if setup_succeeded:
            deposit_data = get_json_file(test, validator_node, DEPOSIT_RESULT_FILE)

    if setup_succeeded:
        validate_deposit_result(test, validator_node, deposit_data)
        test.exec_check(
            "E09 validator-at-running Lighthouse VC process is active",
            validator_node,
            "pgrep -af 'lighthouse.* vc ' >/dev/null",
            retries=20,
            interval=3,
            timeout=30,
        )
        test.exec_check(
            "E09 validator-at-running VC imported validator key",
            validator_node,
            "test -s /tmp/new_validators/validators.json && grep -Eq 'Imported|Enabled validator|Connected to beacon node|Awaiting activation' /tmp/lighthouse-vc.log",
            retries=30,
            interval=5,
            timeout=30,
        )
        if args.require_activation:
            registry_retries = max(1, args.registry_timeout_secs // args.activation_interval_secs)
            wait_for_validator_count(
                test,
                "E09 beacon API reports validator-at-running in registry",
                beacon,
                beacon_api,
                EXPECTED_VALIDATOR_RANK,
                retries=registry_retries,
                interval=args.activation_interval_secs,
            )
            wait_for_validator_activation(
                test,
                beacon,
                beacon_api,
                EXPECTED_VALIDATOR_RANK,
                args.activation_timeout_secs,
                args.activation_interval_secs,
            )
        else:
            record(
                test,
                "E09 activation monitor is optional",
                beacon,
                "skip beacon activation monitor",
                True,
                "deposit succeeded and the validator client is awaiting activation; local all runs the long active-state monitor, while GitHub CI follows example.yaml ci.test_program_command",
            )

    test.write_summary("e09-validator-at-running-runtime-test.json")
    return test.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
