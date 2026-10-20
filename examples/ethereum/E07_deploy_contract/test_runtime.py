#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shlex
import time
from typing import Any, Callable, Dict, Optional

from chainseed.testing import EthereumRuntimeTest


WEI_PER_ETH = 10**18
CONTRACT_NAME = "test"
CONTRACT_FUND_WEI = WEI_PER_ETH
CLAIM_WEI = WEI_PER_ETH // 2
CLAIM_RECIPIENT = "0x1000000000000000000000000000000000000021"
MANUAL_CONTRACT_NAME = "manual_e07"
MANUAL_CONTRACT_ADDRESS = "0xc0ffee254729296a45a3885639AC7E10F9d54979"
CLAIM_FUNDS_SELECTOR = "ed2b40ea"


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
        output = result[stream_name]
        try:
            return int_from_geth_output(output)
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


def extract_geth_json(test: EthereumRuntimeTest, result: Dict[str, object]) -> Dict[str, Any]:
    return test._extract_json("{}\n{}".format(result["stdout"], result["stderr"]))


def get_balance_wei(test: EthereumRuntimeTest, geth_service: object, address: str) -> int:
    result = test.geth_eval(geth_service, 'eth.getBalance("{}").toString(10)'.format(address), timeout=60)
    if result["exit"] != 0:
        raise RuntimeError(result["stderr"] or result["stdout"] or "geth balance query failed")
    return parse_geth_int(result)


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


def get_contract_code(test: EthereumRuntimeTest, geth_service: object, address: str) -> str:
    result = test.geth_eval(geth_service, 'eth.getCode("{}")'.format(address), timeout=60)
    if result["exit"] != 0:
        raise RuntimeError(result["stderr"] or result["stdout"] or "geth code query failed")
    return parse_geth_code(result)


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


def utility_http_command(
    path: str,
    *,
    method: str = "GET",
    payload: Optional[Dict[str, object]] = None,
    expected_status: int = 200,
    expect_text: Optional[str] = None,
) -> str:
    code = '''import json
import urllib.error
import urllib.parse
import urllib.request

url = "http://127.0.0.1:5000{path}"
method = "{method}"
expected_status = {expected_status}
expect_text = {expect_text!r}
payload = {payload}
headers = {{}}
body = None
if payload is not None:
    body = json.dumps(payload).encode("utf-8")
    headers["Content-Type"] = "application/json"
request = urllib.request.Request(url, data=body, headers=headers, method=method)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        status = response.status
        text = response.read().decode("utf-8", errors="replace")
except urllib.error.HTTPError as exc:
    status = exc.code
    text = exc.read().decode("utf-8", errors="replace")
print("status={{}}".format(status))
print(text)
if status != expected_status:
    raise SystemExit(1)
if expect_text is not None and expect_text.lower() not in text.lower():
    raise SystemExit(1)
'''.format(
        path=path,
        method=method,
        expected_status=expected_status,
        expect_text=expect_text,
        payload=json.dumps(payload) if payload is not None else "None",
    )
    return "python3 -c {}".format(shlex.quote(code))


def run_utility_http_check(
    test: EthereumRuntimeTest,
    name: str,
    utility_service: object,
    path: str,
    *,
    method: str = "GET",
    payload: Optional[Dict[str, object]] = None,
    expected_status: int = 200,
    expect_text: Optional[str] = None,
) -> Dict[str, object]:
    command = utility_http_command(
        path,
        method=method,
        payload=payload,
        expected_status=expected_status,
        expect_text=expect_text,
    )
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


def encode_claim_funds(recipient: str, amount_wei: int) -> str:
    recipient_hex = recipient.lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", recipient_hex):
        raise ValueError("invalid recipient address: {}".format(recipient))
    recipient_word = recipient_hex[2:].rjust(64, "0")
    amount_word = hex(amount_wei)[2:].rjust(64, "0")
    return "0x" + CLAIM_FUNDS_SELECTOR + recipient_word + amount_word


def signed_contract_call_raw_transaction(
    test: EthereumRuntimeTest,
    service: object,
    contract_address: str,
    data_hex: str,
    *,
    gas: int = 200000,
    value_wei: int = 0,
    password: str = "admin",
) -> str:
    try:
        from eth_account import Account
    except ImportError as exc:
        raise RuntimeError("eth_account is required to sign contract call transactions") from exc

    state = test._local_account_transaction_state(service)
    sender = str(state["sender"])
    chain_id = test._chain_id_for_service(service)
    private_key = test._private_key_for_local_account(service, sender, password, chain_id=chain_id)
    transaction = {
        "chainId": chain_id,
        "nonce": test._rpc_int(state["nonce"]),
        "gas": gas,
        "gasPrice": test._rpc_int(state["gasPrice"]),
        "to": contract_address,
        "value": int(value_wei),
        "data": bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex),
    }
    signed = Account.sign_transaction(transaction, private_key)
    raw_transaction = getattr(signed, "rawTransaction", None)
    if raw_transaction is None:
        raw_transaction = getattr(signed, "raw_transaction")
    raw_hex = raw_transaction.hex()
    if not raw_hex.startswith("0x"):
        raw_hex = "0x" + raw_hex
    return raw_hex


def claim_funds_script(contract_address: str, recipient: str, raw_transaction: str, receipt_retries: int = 90) -> str:
    script = '''
var contract = __CONTRACT__;
var recipient = __RECIPIENT__;
var contractBefore = eth.getBalance(contract);
var recipientBefore = eth.getBalance(recipient);
var txHash = eth.sendRawTransaction(__RAW_TRANSACTION__);
var receipt = null;
for (var i = 0; i < __RECEIPT_RETRIES__; i++) {
  receipt = eth.getTransactionReceipt(txHash);
  if (receipt !== null && receipt.blockNumber !== null) { break; }
  admin.sleep(1);
}
var contractAfter = eth.getBalance(contract);
var recipientAfter = eth.getBalance(recipient);
JSON.stringify({
  contract: contract,
  recipient: recipient,
  txHash: txHash,
  receiptBlockNumber: receipt === null ? null : receipt.blockNumber.toString(10),
  receiptStatus: receipt === null || receipt.status === null ? null : receipt.status.toString(10),
  contractBefore: contractBefore.toString(10),
  contractAfter: contractAfter.toString(10),
  recipientBefore: recipientBefore.toString(10),
  recipientAfter: recipientAfter.toString(10),
  contractDelta: contractBefore.minus(contractAfter).toString(10),
  recipientDelta: recipientAfter.minus(recipientBefore).toString(10)
})
'''.strip()
    script = script.replace("__CONTRACT__", json.dumps(contract_address))
    script = script.replace("__RECIPIENT__", json.dumps(recipient))
    script = script.replace("__RAW_TRANSACTION__", json.dumps(raw_transaction))
    script = script.replace("__RECEIPT_RETRIES__", str(receipt_retries))
    return script


def send_contract_ether_script(contract_address: str, raw_transaction: str, receipt_retries: int = 90) -> str:
    script = '''
var sender = eth.accounts[0];
var contract = __CONTRACT__;
var senderBefore = eth.getBalance(sender);
var contractBefore = eth.getBalance(contract);
var txHash = eth.sendRawTransaction(__RAW_TRANSACTION__);
var receipt = null;
for (var i = 0; i < __RECEIPT_RETRIES__; i++) {
  receipt = eth.getTransactionReceipt(txHash);
  if (receipt !== null && receipt.blockNumber !== null) { break; }
  admin.sleep(1);
}
var senderAfter = eth.getBalance(sender);
var contractAfter = eth.getBalance(contract);
JSON.stringify({
  sender: sender,
  contract: contract,
  txHash: txHash,
  receiptBlockNumber: receipt === null ? null : receipt.blockNumber.toString(10),
  receiptStatus: receipt === null || receipt.status === null ? null : receipt.status.toString(10),
  senderBefore: senderBefore.toString(10),
  senderAfter: senderAfter.toString(10),
  contractBefore: contractBefore.toString(10),
  contractAfter: contractAfter.toString(10),
  senderDelta: senderBefore.minus(senderAfter).toString(10),
  contractDelta: contractAfter.minus(contractBefore).toString(10)
})
'''.strip()
    script = script.replace("__CONTRACT__", json.dumps(contract_address))
    script = script.replace("__RAW_TRANSACTION__", json.dumps(raw_transaction))
    script = script.replace("__RECEIPT_RETRIES__", str(receipt_retries))
    return script


def send_contract_ether_and_verify(
    test: EthereumRuntimeTest,
    name: str,
    geth_service: object,
    contract_address: str,
    value_wei: int,
) -> Dict[str, object]:
    try:
        raw_transaction = signed_contract_call_raw_transaction(
            test,
            geth_service,
            contract_address,
            "0x",
            gas=100000,
            value_wei=value_wei,
        )
    except Exception as exc:
        return record(test, name, geth_service, "prepare contract receive transaction", False, "", str(exc))

    script = send_contract_ether_script(contract_address, raw_transaction)
    result = test.geth_eval(geth_service, script, timeout=180)
    stdout = str(result["stdout"])
    stderr = str(result["stderr"])
    if result["exit"] != 0:
        return record(test, name, geth_service, "contract receive transaction", False, stdout, stderr)

    try:
        data = extract_geth_json(test, result)
        if not data.get("txHash"):
            raise ValueError("missing transaction hash")
        if data.get("receiptBlockNumber") in (None, ""):
            raise ValueError("transaction was not included in a block")
        if data.get("receiptStatus") not in ("0x1", "1", 1, True, None):
            raise ValueError("transaction receipt status is {}".format(data.get("receiptStatus")))
        contract_delta = int(data["contractDelta"])
        sender_delta = int(data["senderDelta"])
        if contract_delta != value_wei:
            raise ValueError("contract delta {} != {}".format(contract_delta, value_wei))
        if sender_delta < value_wei:
            raise ValueError("sender delta {} is smaller than transfer value {}".format(sender_delta, value_wei))
    except Exception as exc:
        return record(test, name, geth_service, "contract receive transaction", False, stdout, str(exc))

    summary = {
        "sender": data["sender"],
        "contract": data["contract"],
        "tx_hash": data["txHash"],
        "block_number": data["receiptBlockNumber"],
        "sender_delta_wei": data["senderDelta"],
        "contract_delta_wei": data["contractDelta"],
        "value_wei": str(value_wei),
    }
    return record(test, name, geth_service, "contract receive transaction", True, json.dumps(summary, sort_keys=True))


def claim_funds_and_verify(
    test: EthereumRuntimeTest,
    name: str,
    geth_service: object,
    contract_address: str,
    recipient: str,
    amount_wei: int,
) -> Dict[str, object]:
    try:
        data_hex = encode_claim_funds(recipient, amount_wei)
        raw_transaction = signed_contract_call_raw_transaction(test, geth_service, contract_address, data_hex)
    except Exception as exc:
        return record(test, name, geth_service, "prepare claimFunds transaction", False, "", str(exc))

    script = claim_funds_script(contract_address, recipient, raw_transaction)
    result = test.geth_eval(geth_service, script, timeout=180)
    stdout = str(result["stdout"])
    stderr = str(result["stderr"])
    if result["exit"] != 0:
        return record(test, name, geth_service, "claimFunds transaction", False, stdout, stderr)

    try:
        data = extract_geth_json(test, result)
        if not data.get("txHash"):
            raise ValueError("missing transaction hash")
        if data.get("receiptBlockNumber") in (None, ""):
            raise ValueError("transaction was not included in a block")
        if data.get("receiptStatus") not in ("0x1", "1", 1, True, None):
            raise ValueError("transaction receipt status is {}".format(data.get("receiptStatus")))
        recipient_delta = int(data["recipientDelta"])
        contract_delta = int(data["contractDelta"])
        if recipient_delta != amount_wei:
            raise ValueError("recipient delta {} != {}".format(recipient_delta, amount_wei))
        if contract_delta != amount_wei:
            raise ValueError("contract delta {} != {}".format(contract_delta, amount_wei))
    except Exception as exc:
        return record(test, name, geth_service, "claimFunds transaction", False, stdout, str(exc))

    summary = {
        "contract": data["contract"],
        "recipient": data["recipient"],
        "tx_hash": data["txHash"],
        "block_number": data["receiptBlockNumber"],
        "contract_delta_wei": data["contractDelta"],
        "recipient_delta_wei": data["recipientDelta"],
        "value_wei": str(amount_wei),
    }
    return record(test, name, geth_service, "claimFunds transaction", True, json.dumps(summary, sort_keys=True))


def main() -> int:
    test = EthereumRuntimeTest(__file__)

    geth_nodes = test.require_ethereum_services(
        "E07 has POS Geth nodes for deployment checks",
        expected_count=3,
        class_contains="Ethereum-POS-Geth",
        consensus="POS",
    )
    test.require_ethereum_services(
        "E07 has POS Lighthouse beacon nodes",
        expected_count=3,
        class_contains="Ethereum-POS-Beacon",
        consensus="POS",
    )
    test.require_ethereum_services(
        "E07 has POS genesis validator clients",
        expected_count=9,
        class_contains="Ethereum-POS-Validator",
        role="validator_at_genesis",
        consensus="POS",
    )
    utility_services = test.require_ethereum_services(
        "E07 has one Utility service",
        expected_count=1,
        class_contains="EthUtilityServer",
    )
    test.require_ethereum_services(
        "E07 has one Faucet service",
        expected_count=1,
        class_contains="FaucetService",
    )

    if not geth_nodes or not utility_services:
        test.write_summary("e07-deploy-contract-runtime-test.json")
        return test.exit_code()

    geth = geth_nodes[0]
    utility = utility_services[0]

    contract_paths = wait_for_json_file(
        test,
        "E07 Utility registered contract files",
        utility,
        "/utility_server/contracts/contract_file_paths.txt",
        lambda data: isinstance(data, dict) and CONTRACT_NAME in data,
        retries=5,
        interval=1,
    )
    if isinstance(contract_paths, dict):
        command = "test -s /utility_server/contracts/test.abi && test -s /utility_server/contracts/test.bin"
        result = test.exec(utility, command, timeout=30)
        record(
            test,
            "E07 Utility imported contract ABI and bytecode",
            utility,
            command,
            result["exit"] == 0,
            str(result["stdout"]),
            str(result["stderr"]),
        )

    account_data = wait_for_json_file(
        test,
        "E07 Utility created deployer account",
        utility,
        "/utility_server/account.json",
        lambda data: isinstance(data, dict) and str(data.get("address", "")).startswith("0x"),
        retries=120,
        interval=5,
    )
    if isinstance(account_data, dict):
        deployer_address = str(account_data.get("address"))
        wait_for_balance_at_least(
            test,
            "E07 deployer account is funded by Faucet",
            geth,
            deployer_address,
            1,
            retries=60,
            interval=5,
        )

    deployed_contracts = wait_for_json_file(
        test,
        "E07 Utility recorded deployed contract address",
        utility,
        "/utility_server/deployed_contracts/contract_address.txt",
        lambda data: isinstance(data, dict) and re.fullmatch(r"0x[0-9a-fA-F]{40}", str(data.get(CONTRACT_NAME, ""))) is not None,
        retries=120,
        interval=5,
    )
    contract_address = None
    if isinstance(deployed_contracts, dict):
        contract_address = str(deployed_contracts.get(CONTRACT_NAME))

    if contract_address:
        run_utility_http_check(
            test,
            "E07 Utility /contracts_info returns deployed contract",
            utility,
            "/contracts_info",
            expect_text=contract_address,
        )
        run_utility_http_check(
            test,
            "E07 Utility /contracts_info?name=test returns deployed contract",
            utility,
            "/contracts_info?name={}".format(CONTRACT_NAME),
            expect_text=contract_address,
        )
        run_utility_http_check(
            test,
            "E07 Utility /all returns deployed contract",
            utility,
            "/all",
            expect_text=contract_address,
        )
        run_utility_http_check(
            test,
            "E07 Utility can manually register contract metadata",
            utility,
            "/register_contract",
            method="POST",
            payload={"contract_name": MANUAL_CONTRACT_NAME, "contract_address": MANUAL_CONTRACT_ADDRESS},
            expect_text=MANUAL_CONTRACT_ADDRESS,
        )
        run_utility_http_check(
            test,
            "E07 Utility returns manually registered contract metadata",
            utility,
            "/contracts_info?name={}".format(MANUAL_CONTRACT_NAME),
            expect_text=MANUAL_CONTRACT_ADDRESS,
        )

        code = wait_for_contract_code(
            test,
            "E07 deployed contract has bytecode on chain",
            geth,
            contract_address,
            retries=60,
            interval=5,
        )
        if code is not None:
            receive_result = send_contract_ether_and_verify(
                test,
                "E07 Crowdfunding receive() accepts 1 ETH",
                geth,
                contract_address,
                CONTRACT_FUND_WEI,
            )
            if receive_result["status"] == "passed":
                claim_funds_and_verify(
                    test,
                    "E07 Crowdfunding claimFunds() transfers contract balance",
                    geth,
                    contract_address,
                    CLAIM_RECIPIENT,
                    CLAIM_WEI,
                )

    test.write_summary("e07-deploy-contract-runtime-test.json")
    return test.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
