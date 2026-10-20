# Oracle

This example demonstrates how a blockchain application can use an
oracle to access data from outside the blockchain. Smart contracts run
inside the blockchain and cannot directly fetch external data, such as
prices, weather, exchange rates, or web API results. An oracle bridges
this gap by running an external program that fetches or generates data
and writes it back to a smart contract through a transaction.

This example uses either a PoA blockchain based on
[E00_ethereum_poa](../E00_ethereum_poa) or a PoS blockchain based on
[E01_ethereum_pos](../E01_ethereum_pos). It adds two application nodes:
an `oracle_node` and an `oracle_user`.


## Table of Content

- [How to Run](#how-to-run)
- [Why Oracle Is Needed](#why-oracle-is-needed)
- [Example Architecture](#example-architecture)
- [The Oracle Contract](#the-oracle-contract)
- [Oracle Node](#oracle-node)
- [User Node](#user-node)
- [How the Oracle Workflow Works](#how-the-oracle-workflow-works)
- [Observe the Oracle Workflow](#observe-the-oracle-workflow)
- [Important Notes](#important-notes)


## How to Run

Run the following commands from this example directory:

```bash
python simple_oracle.py [poa|pos] [amd|arm]
cd output
docker compose up
```

Arguments:

- `poa`: Use the PoA blockchain from `E00_ethereum_poa`. This is the
  default.
- `pos`: Use the PoS blockchain from `E01_ethereum_pos`.
- `amd`: Generate Docker configuration for AMD64. This is the default.
- `arm`: Generate Docker configuration for ARM64 hosts.

Examples:

```bash
python simple_oracle.py poa amd
```

```bash
python simple_oracle.py pos arm
```

The script loads the selected blockchain component, adds `oracle_node`
and `oracle_user` hosts to AS164, installs helper scripts on both hosts,
and generates the Docker output.


## Why Oracle Is Needed

Smart contracts cannot directly access external data. For example, a
contract cannot safely call a web API such as a price feed, because
every blockchain node must execute the same transaction and reach the
same result. If different nodes receive different API responses, the
blockchain cannot reach consensus.

An oracle solves this problem by moving external data access outside the
smart contract:

```text
external data source
    -> oracle node outside the blockchain
    -> transaction to oracle smart contract
    -> data stored on chain
```

In this example, the oracle node does not fetch a real external price.
For simplicity, it generates a random price and writes it into the
Oracle contract. The same workflow can be adapted to fetch real external
data.


## Example Architecture

This example uses the following components:

| Component | Role |
| --- | --- |
| Geth node | Provides Ethereum JSON-RPC, accepts transactions, executes EVM code, and stores contract state |
| Beacon/Validator nodes | Used in PoS mode to confirm blocks and transactions |
| Faucet server | Funds newly created oracle and user accounts so they can pay gas |
| Utility server | Stores the Oracle contract address under a known name |
| `oracle_node` | Deploys the Oracle contract, listens for update requests, and writes prices on chain |
| `oracle_user` | Requests price updates and reads the current price from the Oracle contract |

The E08 script creates two new hosts in AS164:

```python
oracle_user = as_.createHost('oracle_user').joinNetwork('net0')
oracle_node = as_.createHost('oracle_node').joinNetwork('net0')
```

For PoS mode, the application scripts use the Geth hostnames from the
E01 blockchain:

```python
ETH_NODE1 = 'gethnode1.net'
ETH_NODE2 = 'gethnode2.net'
```

For PoA mode, they use hostnames from the E00 blockchain:

```python
ETH_NODE1 = 'eth3.net'
ETH_NODE2 = 'eth5.net'
```


## The Oracle Contract

The Oracle contract is located in:

```text
contract/Oracle.sol
```

The contract is simple:

```solidity
contract Oracle {
    address public owner;
    uint256 price;

    constructor(){
        owner = msg.sender;
        price = 0;
    }

    receive() external payable { }

    function getPrice() public view returns (uint) {
        return price;
    }

    event UpdatePriceMessage(address indexed _from);

    function updatePrice() public payable {
        emit UpdatePriceMessage(msg.sender);
    }

    function setPrice(uint p) public {
        price = p;
    }
}
```

The important functions are:

- `updatePrice()`: emits an `UpdatePriceMessage` event. This is how a
  user requests a new price.
- `setPrice(uint p)`: writes a new price to the contract state. In this
  example, the oracle node calls this function.
- `getPrice()`: returns the current price. This is a local read-only
  call and does not require a transaction.

The contract also defines an `UpdatePriceMessage` event. The oracle node
monitors this event to know when a user wants the price to be updated.


## Oracle Node

The `oracle_node` container represents the off-chain oracle service. It
is not a special Ethereum node. It is a normal host that runs Python
programs and talks to the blockchain through Geth JSON-RPC.

When the container starts, it runs:

```bash
bash /oracle/oracle_node_start.sh
```

The script runs two programs:

```bash
python3 deploy_oracle_contract.py
python3 oracle_node_set_price.py
```

The first program performs the setup work:

1. Connects to the blockchain through Geth JSON-RPC.
2. Creates a new Ethereum account for the oracle node.
3. Requests funds from the Faucet server.
4. Deploys the Oracle contract.
5. Saves the account and Oracle contract address to
   `/oracle/oracle_account.json`.
6. Registers the Oracle contract address with the Utility server using
   the name `oracle-contract`.

The second program runs in a loop. It monitors the Oracle contract for
`UpdatePriceMessage` events. When it detects an update request, it
generates a random price and invokes `setPrice(price)` on the Oracle
contract. This is a real Ethereum transaction and requires gas.


## User Node

The `oracle_user` container represents a user application. It is also a
normal host that runs Python programs and talks to the blockchain
through Geth JSON-RPC.

When the container starts, it automatically runs:

```bash
python3 /oracle/user_create_account.py
```

This script creates a user account, requests funds from the Faucet
server, and stores the account data in:

```text
/oracle/user_account.json
```

The user program is not started automatically. After the emulator has
started, log into the `oracle_user` container and run:

```bash
python3 /oracle/user_get_price.py
```

This program performs the following steps:

1. Gets the Oracle contract address from the Utility server by querying
   the name `oracle-contract`.
2. Invokes `updatePrice()` on the Oracle contract. This sends a
   transaction and emits an `UpdatePriceMessage` event.
3. Repeatedly calls `getPrice()` to read and print the current price.


## How the Oracle Workflow Works

The full oracle workflow is:

```text
oracle_user invokes updatePrice()
    -> Oracle contract emits UpdatePriceMessage
    -> oracle_node detects the event
    -> oracle_node generates a random price
    -> oracle_node invokes setPrice(price)
    -> Oracle contract stores the new price
    -> oracle_user calls getPrice()
    -> user sees the updated price
```

There are two different types of contract interaction in this workflow:

- `updatePrice()` and `setPrice()` are transactions. They are signed by
  accounts, sent to Geth, included in blocks, and require gas.
- `getPrice()` is a local read-only call. It does not change blockchain
  state and does not require gas.

This distinction is important when building applications with smart
contracts.


## Observe the Oracle Workflow

After starting the emulator, find the oracle containers:

```bash
docker ps | grep -i oracle
```

Check the `oracle_node` logs:

```bash
docker logs <oracle-node-container-name>
```

The logs should show that the oracle account was funded, the Oracle
contract was deployed, and the contract address was registered with the
Utility server. The oracle node then waits for update events.

Check the `oracle_user` account file:

```bash
docker exec -it <oracle-user-container-name> bash
cat /oracle/user_account.json
```

Run the user program:

```bash
python3 /oracle/user_get_price.py
```

The output should show that `updatePrice()` was invoked and that the
program is reading prices from the Oracle contract:

```text
Successfully invoke updatePrice().
Price 0
Price 37
Price 37
Price 58
```

The exact prices are random. The price changes when the oracle node
handles an update event and sends a `setPrice()` transaction.

You can also query the Utility server to find the Oracle contract
address:

```bash
curl http://<utility-ip>:5000/contracts_info?name=oracle-contract
```

To verify that the Oracle contract exists on chain, query its bytecode
through Geth JSON-RPC:

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"eth_getCode","params":["<oracle-contract-address>","latest"],"id":1}' \
  http://<geth-ip>:8545
```

If the result is not `"0x"`, the contract bytecode is stored on chain.


## Important Notes

This example demonstrates the oracle workflow, not a production oracle
security design.

In this teaching contract, anyone can call `setPrice(uint p)`:

```solidity
function setPrice(uint p) public {
    price = p;
}
```

A real oracle contract should restrict who can update the price, for
example by checking that `msg.sender` is an authorized oracle address.

The example also generates a random price instead of fetching data from
a real external source. In a real application, the oracle node would
fetch data from an API, a database, a sensor, or another trusted data
source, validate it, and then submit it to the blockchain.
