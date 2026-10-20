#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shlex
import time
from typing import Any, Callable, Dict, Optional

from chainseed.testing import EthereumRuntimeTest


ORACLE_CONTRACT_NAME = "oracle-contract"
ORACLE_USER_ASN = 164
ORACLE_USER_NODE = "oracle_user"
ORACLE_NODE_ASN = 164
ORACLE_NODE_NODE = "oracle_node"


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


def int_from_geth_output(output: object) -> int:
    matches = re.findall(r"\b\d+\b", str(output))
    if not matches:
        raise RuntimeError("could not parse integer from geth output: {}".format(output))
    return int(matches[-1])


def parse_geth_int(result: Dict[str, object]) -> int:
    for stream_name in ("stdout", "stderr"):
        try:
            return int_from_geth_output(result[stream_name])
        except RuntimeError:
            continue
    raise RuntimeError(
        "could not parse integer from geth output: stdout={} stderr={}".format(
            result["stdout"], result["stderr"]
        )
    )


def parse_geth_code(result: Dict[str, object]) -> str:
    for stream_name in ("stdout", "stderr"):
        lines = [line.strip().strip('"') for line in str(result[stream_name]).splitlines()]
        for line in reversed(lines):
            if not line:
                continue
            if re.fullmatch(r"0x[0-9a-fA-F]*", line):
                return line
            if re.fullmatch(r"[0-9a-fA-F]+", line) and len(line) % 2 == 0:
                return "0x" + line
    raise RuntimeError(
        "could not parse contract code from stdout={} stderr={}".format(
            result["stdout"], result["stderr"]
        )
    )


def get_balance_wei(test: EthereumRuntimeTest, geth_service: object, address: str) -> int:
    result = test.geth_eval(geth_service, 'eth.getBalance("{}").toString(10)'.format(address), timeout=60)
    if result["exit"] != 0:
        raise RuntimeError(result["stderr"] or result["stdout"] or "geth balance query failed")
    return parse_geth_int(result)


def get_transaction_count(test: EthereumRuntimeTest, geth_service: object, address: str) -> int:
    result = test.geth_eval(geth_service, 'eth.getTransactionCount("{}")'.format(address), timeout=60)
    if result["exit"] != 0:
        raise RuntimeError(result["stderr"] or result["stdout"] or "geth nonce query failed")
    return parse_geth_int(result)


def get_contract_code(test: EthereumRuntimeTest, geth_service: object, address: str) -> str:
    result = test.geth_eval(geth_service, 'eth.getCode("{}")'.format(address), timeout=60)
    if result["exit"] != 0:
        raise RuntimeError(result["stderr"] or result["stdout"] or "geth code query failed")
    return parse_geth_code(result)


def wait_for_balance_at_least(
    test: EthereumRuntimeTest,
    name: str,
    geth_service: object,
    address: str,
    minimum_wei: int,
    *,
    retries: int = 60,
    interval: int = 5,
) -> Optional[int]:
    last_balance: Optional[int] = None
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            last_balance = get_balance_wei(test, geth_service, address)
        except Exception as exc:
            last_error = str(exc)
        else:
            if last_balance >= minimum_wei:
                record(
                    test,
                    name,
                    geth_service,
                    "eth.getBalance({}) >= {}".format(address, minimum_wei),
                    True,
                    "balance={} attempts={}".format(last_balance, attempt),
                )
                return last_balance
        if attempt < retries:
            time.sleep(interval)
    record(
        test,
        name,
        geth_service,
        "eth.getBalance({}) >= {}".format(address, minimum_wei),
        False,
        "last_balance={}".format(last_balance),
        last_error,
    )
    return None


def wait_for_nonce_above(
    test: EthereumRuntimeTest,
    name: str,
    geth_service: object,
    address: str,
    previous_nonce: int,
    *,
    retries: int = 90,
    interval: int = 5,
) -> Optional[int]:
    last_nonce: Optional[int] = None
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            last_nonce = get_transaction_count(test, geth_service, address)
        except Exception as exc:
            last_error = str(exc)
        else:
            if last_nonce > previous_nonce:
                record(
                    test,
                    name,
                    geth_service,
                    "eth.getTransactionCount({}) > {}".format(address, previous_nonce),
                    True,
                    "nonce={} attempts={}".format(last_nonce, attempt),
                )
                return last_nonce
        if attempt < retries:
            time.sleep(interval)
    record(
        test,
        name,
        geth_service,
        "eth.getTransactionCount({}) > {}".format(address, previous_nonce),
        False,
        "last_nonce={}".format(last_nonce),
        last_error,
    )
    return None


def wait_for_contract_code(
    test: EthereumRuntimeTest,
    name: str,
    geth_service: object,
    address: str,
    *,
    retries: int = 60,
    interval: int = 5,
) -> Optional[str]:
    last_code = ""
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            last_code = get_contract_code(test, geth_service, address)
        except Exception as exc:
            last_error = str(exc)
        else:
            if last_code != "0x":
                record(
                    test,
                    name,
                    geth_service,
                    "eth.getCode({}) != 0x".format(address),
                    True,
                    "code_bytes={} attempts={}".format((len(last_code) - 2) // 2, attempt),
                )
                return last_code
        if attempt < retries:
            time.sleep(interval)
    record(test, name, geth_service, "eth.getCode({}) != 0x".format(address), False, last_code, last_error)
    return None


def wait_for_json_file(
    test: EthereumRuntimeTest,
    name: str,
    service: object,
    path: str,
    predicate: Optional[Callable[[Any], bool]] = None,
    *,
    retries: int = 120,
    interval: int = 5,
) -> Optional[Any]:
    command = "cat {}".format(shlex.quote(path))
    last_stdout = ""
    last_stderr = ""
    for attempt in range(1, retries + 1):
        result = test.exec(service, command, timeout=30)
        last_stdout = str(result["stdout"])
        last_stderr = str(result["stderr"])
        if result["exit"] == 0:
            try:
                data = json.loads(last_stdout)
            except json.JSONDecodeError as exc:
                last_stderr = str(exc)
            else:
                if predicate is None or predicate(data):
                    record(test, name, service, command, True, "attempts={} data={}".format(attempt, last_stdout))
                    return data
        if attempt < retries:
            time.sleep(interval)
    record(test, name, service, command, False, last_stdout, last_stderr)
    return None


def utility_http_command(path: str, expect_text: Optional[str] = None) -> str:
    code = '''import urllib.error
import urllib.request

url = "http://127.0.0.1:5000{path}"
expect_text = {expect_text!r}
try:
    with urllib.request.urlopen(url, timeout=10) as response:
        status = response.status
        text = response.read().decode("utf-8", errors="replace")
except urllib.error.HTTPError as exc:
    status = exc.code
    text = exc.read().decode("utf-8", errors="replace")
print("status={{}}".format(status))
print(text)
if status != 200:
    raise SystemExit(1)
if expect_text is not None and expect_text.lower() not in text.lower():
    raise SystemExit(1)
'''.format(path=path, expect_text=expect_text)
    return "python3 -c {}".format(shlex.quote(code))


def run_utility_http_check(
    test: EthereumRuntimeTest,
    name: str,
    utility_service: object,
    path: str,
    *,
    expect_text: Optional[str] = None,
) -> Dict[str, object]:
    command = utility_http_command(path, expect_text=expect_text)
    result = test.exec(utility_service, command, timeout=30)
    return record(
        test,
        name,
        utility_service,
        command,
        result["exit"] == 0,
        str(result["stdout"]),
        str(result["stderr"]),
    )


def run_exec_check(
    test: EthereumRuntimeTest,
    name: str,
    service: object,
    command: str,
    *,
    retries: int = 1,
    interval: int = 3,
    timeout: int = 45,
) -> Dict[str, object]:
    last_result: Dict[str, object] = {}
    for attempt in range(1, retries + 1):
        last_result = test.exec(service, command, timeout=timeout)
        if last_result["exit"] == 0:
            break
        if attempt < retries:
            time.sleep(interval)
    return record(
        test,
        name,
        service,
        command,
        last_result.get("exit") == 0,
        "attempts={}\n{}".format(attempt, last_result.get("stdout", "")),
        str(last_result.get("stderr", "")),
    )


def run_user_get_price(test: EthereumRuntimeTest, oracle_user: object) -> Dict[str, object]:
    command = "cd /oracle && timeout 60 python3 -u user_get_price.py"
    result = test.exec(oracle_user, command, timeout=75)
    stdout = str(result["stdout"])
    stderr = str(result["stderr"])
    combined = (stdout + "\n" + stderr).lower()
    ok = result["exit"] in (0, 124) and "successfully invoke updateprice" in combined and "price " in combined
    return record(
        test,
        "E06 oracle_user script invokes updatePrice() and reads prices",
        oracle_user,
        command,
        ok,
        stdout,
        stderr,
    )


def read_price_command(contract_address: str) -> str:
    code = '''import json
import socket
from web3 import Web3

contract_address = {contract_address!r}
ip = socket.gethostbyname("gethnode1.net")
web3 = Web3(Web3.HTTPProvider("http://{{}}:8545".format(ip)))
is_connected = getattr(web3, "is_connected", None) or getattr(web3, "isConnected")
if not is_connected():
    raise SystemExit("web3 is not connected")
with open("/contract/Oracle.abi", "r") as handle:
    abi = handle.read()
contract = web3.eth.contract(address=contract_address, abi=abi)
price = int(contract.functions.getPrice().call())
print(json.dumps({{"price": price}}, sort_keys=True))
if price < 0 or price > 99:
    raise SystemExit(1)
'''.format(contract_address=contract_address)
    return "python3 -c {}".format(shlex.quote(code))


def read_price(test: EthereumRuntimeTest, oracle_user: object, contract_address: str) -> Dict[str, object]:
    command = read_price_command(contract_address)
    result = test.exec(oracle_user, command, timeout=60)
    return record(
        test,
        "E06 oracle_user reads getPrice() from Oracle contract",
        oracle_user,
        command,
        result["exit"] == 0,
        str(result["stdout"]),
        str(result["stderr"]),
    )


def valid_address(value: object) -> bool:
    return re.fullmatch(r"0x[0-9a-fA-F]{40}", str(value)) is not None


def main() -> int:
    test = EthereumRuntimeTest(__file__)

    geth_nodes = test.require_ethereum_services(
        "E06 has POS Geth nodes for oracle checks",
        expected_count=3,
        class_contains="Ethereum-POS-Geth",
        consensus="POS",
    )
    test.require_ethereum_services(
        "E06 has POS Lighthouse beacon nodes",
        expected_count=3,
        class_contains="Ethereum-POS-Beacon",
        consensus="POS",
    )
    test.require_ethereum_services(
        "E06 has POS genesis validator clients",
        expected_count=9,
        class_contains="Ethereum-POS-Validator",
        role="validator_at_genesis",
        consensus="POS",
    )
    faucet_services = test.require_ethereum_services(
        "E06 has one Faucet service",
        expected_count=1,
        class_contains="FaucetService",
    )
    utility_services = test.require_ethereum_services(
        "E06 has one Utility service",
        expected_count=1,
        class_contains="EthUtilityServer",
    )
    oracle_user = test.require_service(ORACLE_USER_ASN, ORACLE_USER_NODE, "E06 oracle_user host is generated")
    oracle_node = test.require_service(ORACLE_NODE_ASN, ORACLE_NODE_NODE, "E06 oracle_node host is generated")

    if not geth_nodes or not faucet_services or not utility_services or oracle_user is None or oracle_node is None:
        test.write_summary("e06-oracle-runtime-test.json")
        return test.exit_code()

    geth = geth_nodes[0]
    utility = utility_services[0]

    run_exec_check(
        test,
        "E06 oracle_user scripts and ABI are installed",
        oracle_user,
        "test -s /contract/Oracle.abi && test -s /oracle/user_create_account.py && test -s /oracle/user_get_price.py",
        retries=3,
        interval=2,
    )
    run_exec_check(
        test,
        "E06 oracle_node scripts and contract artifacts are installed",
        oracle_node,
        "test -s /contract/Oracle.abi && test -s /contract/Oracle.bin && test -s /oracle/deploy_oracle_contract.py && test -s /oracle/oracle_node_set_price.py",
        retries=3,
        interval=2,
    )

    user_account = wait_for_json_file(
        test,
        "E06 oracle_user created and saved an account",
        oracle_user,
        "/oracle/user_account.json",
        lambda data: isinstance(data, dict) and valid_address(data.get("account_address")) and bool(data.get("private_key")),
        retries=120,
        interval=5,
    )
    oracle_account = wait_for_json_file(
        test,
        "E06 oracle_node deployed Oracle contract and saved account data",
        oracle_node,
        "/oracle/oracle_account.json",
        lambda data: isinstance(data, dict)
        and valid_address(data.get("account_address"))
        and valid_address(data.get("oracle_address"))
        and bool(data.get("private_key")),
        retries=120,
        interval=5,
    )

    oracle_account_address = None
    oracle_contract_address = None
    if isinstance(user_account, dict):
        user_address = str(user_account.get("account_address"))
        wait_for_balance_at_least(
            test,
            "E06 oracle_user account is funded by Faucet",
            geth,
            user_address,
            1,
            retries=60,
            interval=5,
        )
    if isinstance(oracle_account, dict):
        oracle_account_address = str(oracle_account.get("account_address"))
        oracle_contract_address = str(oracle_account.get("oracle_address"))
        wait_for_balance_at_least(
            test,
            "E06 oracle_node account is funded by Faucet",
            geth,
            oracle_account_address,
            1,
            retries=60,
            interval=5,
        )

    if oracle_contract_address:
        run_utility_http_check(
            test,
            "E06 Utility returns oracle-contract address by name",
            utility,
            "/contracts_info?name={}".format(ORACLE_CONTRACT_NAME),
            expect_text=oracle_contract_address,
        )
        run_utility_http_check(
            test,
            "E06 Utility /all contains oracle-contract address",
            utility,
            "/all",
            expect_text=oracle_contract_address,
        )
        wait_for_contract_code(
            test,
            "E06 Oracle contract has bytecode on chain",
            geth,
            oracle_contract_address,
            retries=60,
            interval=5,
        )

    run_exec_check(
        test,
        "E06 oracle_node event listener process is running",
        oracle_node,
        "pgrep -af oracle_node_set_price.py >/dev/null",
        retries=60,
        interval=5,
    )

    if oracle_account_address and oracle_contract_address:
        oracle_nonce_before = get_transaction_count(test, geth, oracle_account_address)
        time.sleep(5)
        user_result = run_user_get_price(test, oracle_user)
        if user_result["status"] == "passed":
            nonce_after = wait_for_nonce_above(
                test,
                "E06 oracle_node handles UpdatePriceMessage and sends setPrice()",
                geth,
                oracle_account_address,
                oracle_nonce_before,
                retries=90,
                interval=5,
            )
            if nonce_after is not None:
                read_price(test, oracle_user, oracle_contract_address)

    test.write_summary("e06-oracle-runtime-test.json")
    return test.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
