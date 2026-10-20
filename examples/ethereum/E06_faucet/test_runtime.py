#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shlex
import time
from typing import Dict, Optional

from chainseed.testing import EthereumRuntimeTest


WEI_PER_ETH = 10**18
BUILD_TIME_FUNDS = (
    ("0x72943017a1fa5f255fc0f06625aec22319fcd5b3", 2),
    ("0x5449ba5c5f185e9694146d60cfe72681e2158499", 5),
)
JSON_REQUEST_RECIPIENT = "0x1000000000000000000000000000000000000020"
FORM_REQUEST_RECIPIENT = "0x1000000000000000000000000000000000000021"
FAUCET_USER_RECIPIENT = "0x1000000000000000000000000000000000000022"
INVALID_RECIPIENT = "0xnot-an-ethereum-address"


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


def get_balance_wei(test: EthereumRuntimeTest, geth_service: object, address: str) -> int:
    result = test.geth_eval(geth_service, 'eth.getBalance("{}").toString(10)'.format(address), timeout=60)
    if result["exit"] != 0:
        raise RuntimeError(result["stderr"] or result["stdout"] or "geth balance query failed")
    return int_from_geth_output(result["stdout"])


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
    return last_balance


def wait_for_balance_increase(
    test: EthereumRuntimeTest,
    name: str,
    geth_service: object,
    address: str,
    before_wei: int,
    delta_wei: int,
) -> None:
    wait_for_balance_at_least(
        test,
        name,
        geth_service,
        address,
        before_wei + delta_wei,
        retries=60,
        interval=5,
    )


def faucet_request_command(url: str, address: str, amount: int, mode: str, expected_status: int, expect_text: str) -> str:
    script = '''
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

url = __URL__
address = __ADDRESS__
amount = __AMOUNT__
mode = __MODE__
expected_status = __EXPECTED_STATUS__
expect_text = __EXPECT_TEXT__.lower()

headers = {}
if mode == "json":
    body = json.dumps({"address": address, "amount": amount}).encode("utf-8")
    headers["Content-Type"] = "application/json"
elif mode == "form":
    body = urllib.parse.urlencode({"address": address, "amount": amount}).encode("utf-8")
    headers["Content-Type"] = "application/x-www-form-urlencoded"
else:
    raise SystemExit("unknown request mode: {}".format(mode))

request = urllib.request.Request(url, data=body, headers=headers, method="POST")
try:
    with urllib.request.urlopen(request, timeout=360) as response:
        status = response.status
        text = response.read().decode("utf-8", errors="replace")
except urllib.error.HTTPError as exc:
    status = exc.code
    text = exc.read().decode("utf-8", errors="replace")

print("status={}".format(status))
print(text)
if status != expected_status:
    raise SystemExit(1)
if expect_text and expect_text not in text.lower():
    raise SystemExit(1)
'''.strip()
    replacements = {
        "__URL__": json.dumps(url),
        "__ADDRESS__": json.dumps(address),
        "__AMOUNT__": str(int(amount)),
        "__MODE__": json.dumps(mode),
        "__EXPECTED_STATUS__": str(int(expected_status)),
        "__EXPECT_TEXT__": json.dumps(expect_text),
    }
    for old, new in replacements.items():
        script = script.replace(old, new)
    return "python3 -c {}".format(shlex.quote(script))


def send_faucet_request(
    test: EthereumRuntimeTest,
    name: str,
    requester_service: object,
    faucet_url: str,
    address: str,
    amount: int,
    *,
    mode: str,
    expected_status: int = 200,
    expect_text: str = "success",
) -> Dict[str, object]:
    command = faucet_request_command(faucet_url, address, amount, mode, expected_status, expect_text)
    result = test.exec(requester_service, command, timeout=420)
    ok = result["exit"] == 0
    return record(test, name, requester_service, command, ok, str(result["stdout"]), str(result["stderr"]))


def run_faucet_user_script(
    test: EthereumRuntimeTest,
    faucet_user_service: object,
    address: str,
) -> Dict[str, object]:
    command = "python3 faucet_user/fundme.py {}".format(shlex.quote(address))
    result = test.exec(faucet_user_service, command, timeout=420)
    ok = result["exit"] == 0
    return record(
        test,
        "E06 FaucetUserService script can request runtime funds",
        faucet_user_service,
        command,
        ok,
        str(result["stdout"]),
        str(result["stderr"]),
    )


def main() -> int:
    test = EthereumRuntimeTest(__file__)

    geth_nodes = test.require_ethereum_services(
        "E06 has POS Geth nodes for balance checks",
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
    faucet_user_services = test.require_ethereum_services(
        "E06 has one FaucetUser service",
        expected_count=1,
        class_contains="FaucetUserService",
    )
    test.require_ethereum_services(
        "E06 has one Utility service",
        expected_count=1,
        class_contains="EthUtilityServer",
    )

    if not geth_nodes or not faucet_services or not faucet_user_services:
        test.write_summary("e06-faucet-runtime-test.json")
        return test.exit_code()

    geth = geth_nodes[0]
    faucet = faucet_services[0]
    faucet_user = faucet_user_services[0]
    faucet_fund_url = "http://{}:80/fundme".format(faucet.address)

    for address, amount_eth in BUILD_TIME_FUNDS:
        wait_for_balance_at_least(
            test,
            "E06 build-time Faucet funding reaches {} ETH for {}".format(amount_eth, address),
            geth,
            address,
            amount_eth * WEI_PER_ETH,
            retries=90,
            interval=5,
        )

    before_json = get_balance_wei(test, geth, JSON_REQUEST_RECIPIENT)
    json_result = send_faucet_request(
        test,
        "E06 Faucet JSON /fundme request succeeds",
        faucet_user,
        faucet_fund_url,
        JSON_REQUEST_RECIPIENT,
        1,
        mode="json",
    )
    if json_result["status"] == "passed":
        wait_for_balance_increase(
            test,
            "E06 Faucet JSON /fundme transfers 1 ETH",
            geth,
            JSON_REQUEST_RECIPIENT,
            before_json,
            WEI_PER_ETH,
        )

    before_form = get_balance_wei(test, geth, FORM_REQUEST_RECIPIENT)
    form_result = send_faucet_request(
        test,
        "E06 Faucet form /fundme request succeeds",
        faucet_user,
        faucet_fund_url,
        FORM_REQUEST_RECIPIENT,
        1,
        mode="form",
    )
    if form_result["status"] == "passed":
        wait_for_balance_increase(
            test,
            "E06 Faucet form /fundme transfers 1 ETH",
            geth,
            FORM_REQUEST_RECIPIENT,
            before_form,
            WEI_PER_ETH,
        )

    before_user = get_balance_wei(test, geth, FAUCET_USER_RECIPIENT)
    user_result = run_faucet_user_script(test, faucet_user, FAUCET_USER_RECIPIENT)
    if user_result["status"] == "passed":
        wait_for_balance_increase(
            test,
            "E06 FaucetUserService runtime script transfers 10 ETH",
            geth,
            FAUCET_USER_RECIPIENT,
            before_user,
            10 * WEI_PER_ETH,
        )

    send_faucet_request(
        test,
        "E06 Faucet rejects invalid Ethereum address",
        faucet_user,
        faucet_fund_url,
        INVALID_RECIPIENT,
        1,
        mode="json",
        expected_status=500,
        expect_text="invalid ethereum address",
    )
    send_faucet_request(
        test,
        "E06 Faucet rejects requests above max_fund_amount",
        faucet_user,
        faucet_fund_url,
        JSON_REQUEST_RECIPIENT,
        11,
        mode="json",
        expected_status=500,
        expect_text="max_fund_amount",
    )

    test.write_summary("e06-faucet-runtime-test.json")
    return test.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
