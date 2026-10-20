from web3 import Web3
try:
    from web3.middleware import geth_poa_middleware
except ImportError:
    try:
        from web3.middleware import ExtraDataToPOAMiddleware as geth_poa_middleware
    except ImportError:
        geth_poa_middleware = None
import time
from sys import stderr


class EthereumHelper:

    _web3: Web3
    _chain_id: int
    _max_fee: float
    _max_priority_fee: float

    def __init__(self, chain_id: int = 1337):
        self._chain_id = chain_id
        self._max_fee = 3.0
        self._max_priority_fee = 2.0

    def __log(self, message: str):
        print("== EthereumHelper: " + message, file=stderr)

    @staticmethod
    def _is_connected(web3: Web3) -> bool:
        method = getattr(web3, "is_connected", None) or getattr(web3, "isConnected")
        return bool(method())

    @staticmethod
    def _to_wei(amount, unit: str) -> int:
        method = getattr(Web3, "to_wei", None) or getattr(Web3, "toWei")
        return int(method(amount, unit))

    @staticmethod
    def _raw_transaction(signed_tx):
        return getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction")

    @staticmethod
    def _private_key_hex(account) -> str:
        key = getattr(account, "key", None) or getattr(account, "privateKey")
        key_hex = key.hex()
        if not key_hex.startswith("0x"):
            key_hex = "0x" + key_hex
        return key_hex

    def _block_number(self) -> int:
        value = getattr(self._web3.eth, "block_number", None)
        if value is not None:
            return int(value)
        return int(self._web3.eth.blockNumber)

    def _get_transaction_count(self, address: str) -> int:
        method = getattr(self._web3.eth, "get_transaction_count", None) or getattr(
            self._web3.eth, "getTransactionCount"
        )
        return int(method(address))

    def _send_raw_transaction(self, raw_transaction):
        method = getattr(self._web3.eth, "send_raw_transaction", None) or getattr(
            self._web3.eth, "sendRawTransaction"
        )
        return method(raw_transaction)

    @staticmethod
    def _build_transaction(function, transaction_info):
        method = getattr(function, "build_transaction", None) or getattr(function, "buildTransaction")
        return method(transaction_info)

    def create_account(self):
        account = self._web3.eth.account.create()
        address = account.address
        key = self._private_key_hex(account)
        return address, key

    def connect_to_blockchain(self, url: str, isPOA=False, wait=True):
        self._url = url

        while True:
            self._web3 = Web3(Web3.HTTPProvider(url))
            if isPOA and geth_poa_middleware is not None:
                self._web3.middleware_onion.inject(geth_poa_middleware, layer=0)

            if self._is_connected(self._web3):
                self.__log("Successfully connected to {}".format(url))
                break
            if wait:
                self.__log("Failed to connect to {}, retrying ...".format(url))
                time.sleep(10)
            else:
                break

        return self._web3

    def wait_for_blocknumber(self, block_number=5):
        block_now = self._block_number()
        while block_now < block_number:
            self.__log(
                "Waiting for the block number to reach {} (current: {})".format(block_number, block_now)
            )
            time.sleep(10)
            block_now = self._block_number()

    def deploy_contract(self, contract_file, sender_address, sender_key, amount=0, gas=3000000, wait=True):
        with open(contract_file) as contract:
            data = contract.read().strip()
        if data and not data.startswith("0x"):
            data = "0x" + data

        tx_hash = self.send_raw_transaction(None, sender_address, sender_key, amount=amount, data=data, gas=gas)
        tx_receipt = None
        if wait:
            tx_receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

        return tx_hash, tx_receipt

    def transfer_fund(self, receiver_address, sender_address, sender_key, amount=0, gas=3000000, wait=True):
        tx_hash = self.send_raw_transaction(receiver_address, sender_address, sender_key, amount=amount, gas=gas)
        tx_receipt = None
        if wait:
            tx_receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

        return tx_hash, tx_receipt

    def send_raw_transaction(self, recipient, sender_address, sender_key, data: str = "", amount=0, gas=300000):
        transaction = {
            "nonce": self._get_transaction_count(sender_address),
            "from": sender_address,
            "value": self._to_wei(amount, "ether"),
            "chainId": self._chain_id,
            "gas": gas,
            "maxFeePerGas": self._to_wei(self._max_fee, "gwei"),
            "maxPriorityFeePerGas": self._to_wei(self._max_priority_fee, "gwei"),
            "data": data,
        }
        if recipient is not None:
            transaction["to"] = recipient

        signed_tx = self._web3.eth.account.sign_transaction(transaction, sender_key)
        tx_hash = self._send_raw_transaction(self._raw_transaction(signed_tx))

        return tx_hash

    def invoke_contract_function(self, function, sender_address, sender_key, amount=0, gas=3000000, wait=True):
        assert self._web3 is not None
        assert function is not None

        transaction_info = {
            "nonce": self._get_transaction_count(sender_address),
            "from": sender_address,
            "value": self._to_wei(amount, "ether"),
            "chainId": self._chain_id,
            "gas": gas,
            "maxFeePerGas": self._to_wei(self._max_fee, "gwei"),
            "maxPriorityFeePerGas": self._to_wei(self._max_priority_fee, "gwei"),
        }

        transaction = self._build_transaction(function, transaction_info)
        signed_tx = self._web3.eth.account.sign_transaction(transaction, sender_key)
        tx_hash = self._send_raw_transaction(self._raw_transaction(signed_tx))

        tx_receipt = None
        if wait:
            tx_receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

        return tx_hash, tx_receipt
