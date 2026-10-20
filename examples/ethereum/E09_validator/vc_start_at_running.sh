#!/bin/bash

set -euo pipefail

########################################
# Config
########################################

TESTNET_DIR="/tmp/vc/local-testnet/testnet"
DATADIR="/tmp/vc/local-testnet/testnet"

BEACON_NODE="${E09_BEACON_NODE:-http://10.151.0.72:8000}"
GETH_RPC="${E09_GETH_RPC:-http://10.150.0.72:8545}"

WITHDRAW_ADDRESS_FILE="/tmp/withdraw-address"

WALLET_NAME="seed"
WALLET_PASSWORD_FILE="/tmp/seed.pass"
WALLET_MNEMONIC_FILE="/tmp/validator-at-running-wallet.mnemonic"
VALIDATOR_MNEMONIC_FILE="${E09_VALIDATOR_MNEMONIC_FILE:-/tmp/validator-at-running.mnemonic}"
VALIDATOR_MNEMONIC="${E09_VALIDATOR_MNEMONIC:-abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about}"

NEW_VALIDATOR_DIR="/tmp/new_validators"
VC_HTTP_PORT="5062"
DEPOSIT_RESULT_FILE="/tmp/e09_deposit_result.json"

export GETH_RPC
export KEYSTORE_PASSWORD="${KEYSTORE_PASSWORD:-admin}"

########################################
# Prepare deterministic non-interactive input
########################################

if [ ! -s "${VALIDATOR_MNEMONIC_FILE}" ]; then
    printf '%s\n' "${VALIDATOR_MNEMONIC}" > "${VALIDATOR_MNEMONIC_FILE}"
    chmod 600 "${VALIDATOR_MNEMONIC_FILE}"
fi

########################################
# Get FEE_RECIPIENT from first keystore
########################################

FEE_RECIPIENT=$(
python3 <<'PY'
import glob, json, os
from eth_account import Account
from web3 import Web3

password = os.environ.get("KEYSTORE_PASSWORD", "admin")

keystore_files = sorted(glob.glob("/tmp/keystore/UTC--*"))

if not keystore_files:
    raise SystemExit("no keystore found in /tmp/keystore")

ks_path = keystore_files[0]

ks = json.load(open(ks_path, "r"))
pk = Account.decrypt(ks, password)
acct = Account.from_key(pk)

print(Web3.to_checksum_address(acct.address))
PY
)

echo "[INFO] FEE_RECIPIENT=${FEE_RECIPIENT}"

########################################
# Create wallet if not exists
########################################

if lighthouse account_manager wallet list --testnet-dir "${TESTNET_DIR}" --datadir "${DATADIR}" 2>/dev/null | grep -qx "${WALLET_NAME}"; then
    echo "[INFO] wallet already exists"
else
    echo "[INFO] creating lighthouse wallet..."

    lighthouse account_manager wallet create --testnet-dir "${TESTNET_DIR}" --datadir "${DATADIR}" --name "${WALLET_NAME}" --password-file "${WALLET_PASSWORD_FILE}" --mnemonic-output-path "${WALLET_MNEMONIC_FILE}"
fi

########################################
# Create validator-manager validator
########################################

rm -rf "${NEW_VALIDATOR_DIR}"
mkdir -p "${NEW_VALIDATOR_DIR}"

echo "[INFO] creating validator-manager validator..."

lighthouse validator-manager create   --testnet-dir "${TESTNET_DIR}"   --mnemonic-path "${VALIDATOR_MNEMONIC_FILE}"   --stdin-inputs   --first-index 0   --count 1   --eth1-withdrawal-address "$(cat ${WITHDRAW_ADDRESS_FILE})"   --suggested-fee-recipient "${FEE_RECIPIENT}"   --output-path "${NEW_VALIDATOR_DIR}"

########################################
# Start VC
########################################

echo "[INFO] starting validator client..."

pkill -f "lighthouse.* vc" || true

nohup lighthouse --debug-level info vc   --datadir "${DATADIR}"   --testnet-dir "${TESTNET_DIR}"   --init-slashing-protection   --beacon-nodes "${BEACON_NODE}"   --suggested-fee-recipient "${FEE_RECIPIENT}"   --http   --http-address 0.0.0.0   --http-port "${VC_HTTP_PORT}"   --http-allow-origin "*"   --unencrypted-http-transport   --enable-doppelganger-protection   > /tmp/lighthouse-vc.log 2>&1 &

for i in $(seq 1 60); do
    if [ -s "${DATADIR}/validators/api-token.txt" ] && pgrep -af "lighthouse.* vc" >/dev/null; then
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "[ERROR] validator client did not start or did not create an API token" >&2
        tail -n 80 /tmp/lighthouse-vc.log >&2 || true
        exit 1
    fi
    sleep 2
done

########################################
# Import validators
########################################

echo "[INFO] importing validators into VC..."

for i in $(seq 1 30); do
    if lighthouse validator-manager import --validators-file "${NEW_VALIDATOR_DIR}/validators.json" --vc-url "http://127.0.0.1:${VC_HTTP_PORT}" --vc-token "${DATADIR}/validators/api-token.txt" --ignore-duplicates; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[ERROR] failed to import validator key into validator client" >&2
        tail -n 120 /tmp/lighthouse-vc.log >&2 || true
        exit 1
    fi
    sleep 2
done

########################################
# Generate deposit script
########################################

echo "[INFO] generating deposit python script..."

cat >/tmp/deposit_from_json_web3v7.py <<'PY'
import glob
import json
import os
from eth_account import Account
from web3 import Web3

RPC = os.environ.get("GETH_RPC", "http://10.150.0.72:8545")
KEYSTORE_PASSWORD = os.environ.get("KEYSTORE_PASSWORD", "admin")
RESULT_FILE = "/tmp/e09_deposit_result.json"

DEPOSIT_CONTRACT = Web3.to_checksum_address(
    "0x00000000219ab540356cBB839Cbe05303d7705Fa"
)

KEYS_DIR = "/tmp/new_validators"

def log(title, value=""):
    print(f"[INFO] {title}: {value}", flush=True)

def hb(x):
    x = x.strip()
    if not x.startswith("0x"):
        x = "0x" + x
    return Web3.to_bytes(hexstr=x)

def json_default(obj):
    if isinstance(obj, bytes):
        return Web3.to_hex(obj)
    try:
        return Web3.to_hex(obj)
    except Exception:
        return str(obj)

log("RPC", RPC)
log("deposit contract", DEPOSIT_CONTRACT)
log("deposit json dir", KEYS_DIR)

deposit_files = sorted(glob.glob(os.path.join(KEYS_DIR, "deposit*.json")))

if not deposit_files:
    raise SystemExit(f"deposit json not found in {KEYS_DIR}")

deposit_path = deposit_files[0]

log("selected deposit_json", deposit_path)

data = json.load(open(deposit_path, "r"))
entry = data[0] if isinstance(data, list) else data

pubkey = hb(entry["pubkey"])
withdrawal_credentials = hb(entry["withdrawal_credentials"])
signature = hb(entry["signature"])
deposit_data_root = hb(entry["deposit_data_root"])

log("pubkey", entry["pubkey"])
log("withdrawal_credentials", entry["withdrawal_credentials"])
log("deposit_data_root", entry["deposit_data_root"])

w3 = Web3(Web3.HTTPProvider(RPC))

if not w3.is_connected():
    raise SystemExit(f"cannot connect RPC: {RPC}")

log("connected", True)
log("chain_id", w3.eth.chain_id)
log("latest_block", w3.eth.block_number)
log("gas_price_wei", w3.eth.gas_price)

code = w3.eth.get_code(DEPOSIT_CONTRACT)

if not code or code == b"\x00":
    raise SystemExit(
        f"deposit contract not found at {DEPOSIT_CONTRACT}, eth_getCode is empty"
    )

log("deposit_contract_code_size", len(code))

keystore_files = sorted(glob.glob("/tmp/keystore/UTC--*"))

if not keystore_files:
    raise SystemExit("no keystore found in /tmp/keystore")

ks_path = keystore_files[0]

log("selected payer_keystore", ks_path)

ks = json.load(open(ks_path, "r"))
pk = Account.decrypt(ks, KEYSTORE_PASSWORD)
acct = Account.from_key(pk)

payer_addr = Web3.to_checksum_address(acct.address)
balance_before_block = w3.eth.block_number
balance_before = w3.eth.get_balance(
    payer_addr, block_identifier=balance_before_block
)

log("selected payer", payer_addr)
log("payer_balance_before_wei", balance_before)
log("payer_balance_before_eth", w3.from_wei(balance_before, "ether"))

abi = [{
  "name": "deposit",
  "type": "function",
  "stateMutability": "payable",
  "inputs": [
    {"name": "pubkey", "type": "bytes"},
    {"name": "withdrawal_credentials", "type": "bytes"},
    {"name": "signature", "type": "bytes"},
    {"name": "deposit_data_root", "type": "bytes32"}
  ],
  "outputs": []
}]

contract = w3.eth.contract(address=DEPOSIT_CONTRACT, abi=abi)

value = w3.to_wei(32, "ether")
nonce = w3.eth.get_transaction_count(payer_addr, "pending")
gas_price = w3.eth.gas_price

log("deposit_value_eth", 32)
log("nonce_pending", nonce)

tx = contract.functions.deposit(
    pubkey,
    withdrawal_credentials,
    signature,
    deposit_data_root
).build_transaction({
    "from": payer_addr,
    "value": value,
    "nonce": nonce,
    "chainId": w3.eth.chain_id,
    "gasPrice": gas_price,
})

try:
    estimated_gas = w3.eth.estimate_gas(tx)
    tx["gas"] = estimated_gas
    log("estimated_gas", estimated_gas)
except Exception as e:
    tx["gas"] = 250000
    log("estimate_gas_failed_use_default", f"250000 reason={e}")

max_cost = value + tx["gas"] * gas_price

log("max_total_cost_wei", max_cost)
log("max_total_cost_eth", w3.from_wei(max_cost, "ether"))

if balance_before < max_cost:
    raise SystemExit(
        f"insufficient balance: balance={w3.from_wei(balance_before, 'ether')} ETH, "
        f"need about {w3.from_wei(max_cost, 'ether')} ETH"
    )

signed = w3.eth.account.sign_transaction(tx, pk)
raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction

tx_hash = w3.eth.send_raw_transaction(raw)
tx_hash_hex = w3.to_hex(tx_hash)

log("tx_hash", tx_hash_hex)
log("waiting_receipt", "timeout=180s")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

receipt_block_number = int(receipt["blockNumber"])
transaction = w3.eth.get_transaction(tx_hash)
transaction_to = Web3.to_checksum_address(transaction["to"])
transaction_value = int(transaction["value"])
balance_after = w3.eth.get_balance(
    payer_addr, block_identifier=receipt_block_number
)

gas_used = receipt.get("gasUsed", 0)
effective_gas_price = receipt.get("effectiveGasPrice", gas_price)
fee_paid = gas_used * effective_gas_price
success = receipt.status == 1

print("\n========== DEPOSIT RESULT ==========")
print("deposit_json:", deposit_path)
print("payer:", payer_addr)
print("payer_keystore:", ks_path)
print("tx_hash:", tx_hash_hex)
print("status:", receipt.status)
print("success:", success)

print("\n========== BALANCE ==========")
print("balance_before_wei:", balance_before)
print("balance_before_eth:", w3.from_wei(balance_before, "ether"))
print("balance_after_wei:", balance_after)
print("balance_after_eth:", w3.from_wei(balance_after, "ether"))
print("deposit_value_eth:", w3.from_wei(value, "ether"))
print("gas_used:", gas_used)
print("effective_gas_price:", effective_gas_price)
print("fee_paid_wei:", fee_paid)
print("fee_paid_eth:", w3.from_wei(fee_paid, "ether"))

summary = {
    "deposit_json": deposit_path,
    "payer": payer_addr,
    "payer_keystore": ks_path,
    "pubkey": entry["pubkey"],
    "tx_hash": tx_hash_hex,
    "status": int(receipt.status),
    "success": bool(success),
    "transaction_to": transaction_to,
    "transaction_value_wei": str(transaction_value),
    "balance_before_block": int(balance_before_block),
    "balance_before_wei": str(balance_before),
    "balance_after_block": receipt_block_number,
    "balance_after_wei": str(balance_after),
    "deposit_value_wei": str(value),
    "gas_used": int(gas_used),
    "effective_gas_price": str(effective_gas_price),
    "fee_paid_wei": str(fee_paid),
    "receipt_block_number": receipt_block_number,
}
open(RESULT_FILE, "w").write(json.dumps(summary, indent=2, sort_keys=True) + "\n")

if not success:
    raise SystemExit("deposit transaction failed, status != 1")

print("\n[INFO] deposit success")
PY

########################################
# Execute deposit
########################################

echo "[INFO] sending 32 ETH deposit..."

python3 /tmp/deposit_from_json_web3v7.py

echo
echo "[INFO] ALL DONE"
