# Ethereum Blockchain (PoA)

This example deploys a private Ethereum proof-of-authority (PoA) network using
Geth. It demonstrates how to configure pre-funded accounts and signer nodes,
bind blockchain services to hosts in an emulated network, and generate Docker
deployment files.

`component_poa.py` configures the blockchain; `ethereum_poa.py` combines it with
the network from `mini_internet.py` and generates the Docker deployment.

## Create a blockchain

Create an `EthereumService`, then use `createBlockchain()` to add a PoA
blockchain. A single service can manage multiple blockchains.

```python
from chainseed.services.ethereum import EthereumService, ConsensusMechanism

eth = EthereumService()
blockchain = eth.createBlockchain(
    chainName="POA",
    consensus=ConsensusMechanism.POA,
)
```

## Configure pre-funded accounts

Before creating Ethereum nodes, configure the accounts generated for each node.
This example creates two accounts per node, each with an initial balance of
1,000 ETH.

```python
mnemonic, _, _ = blockchain.getEmuAccountParameters()
blockchain.setEmuAccountParameters(
    mnemonic=mnemonic,
    balance=1000,
    total_per_node=2,
)
```

You can also allocate an initial balance to an existing address without importing
its private key into the emulator:

```python
blockchain.addLocalAccount(
    address="0xF5406927254d2dA7F7c28A61191e3Ff1f2400fe9",
    balance=30,
)
```

These balances are recorded in the genesis state and are available when the
chain starts. See the
[account management guide](../../../docs/user_manual/blockchain/accounts.md)
for more configuration options.

## Create Ethereum Nodes

By default, the example creates 20 Ethereum nodes. Even-indexed nodes are
signers, and nodes whose indices are divisible by three are bootnodes.

Create an Ethereum node with a unique virtual node name, then configure the
returned Server instance. The following node acts as both a PoA signer and a
bootnode, with HTTP and WebSocket RPC enabled:

```python
eth_node = blockchain.createNode("eth0")
eth_node.startMiner()
eth_node.setBootNode(True)
eth_node.enableGethHttp()
eth_node.enableGethWs()
```

For PoA, `startMiner()` enables block signing. `setBootNode(True)` makes the node
a bootstrap peer for node discovery. See
[`EthereumServer`](../../../chainseed/services/ethereum/EthereumServer.py)
for additional configuration APIs.

## Customize Geth

Configure additional Geth command-line options or use a custom binary before
calling `emu.render()`. These settings apply to the selected Server instance.

Use `setCustomGethCommandOption()` for options not exposed by the Server APIs:

```python
eth_node.setCustomGethCommandOption("--txpool.globalslots 8192")
```

Use `setCustomGeth()` to include a local Geth binary in the node image. The binary
must support Clique PoA and match the target architecture.

```python
eth_node.setCustomGeth("./custom_geth_binary")
```

## Faucet and Utility servers

This example also includes Faucet and Utility servers. For configuration and
usage, see [E04_faucet](../E04_faucet) and
[E05_deploy_contract](../E05_deploy_contract). Both examples support PoA and PoS.

## Bind services to network hosts

Bind each virtual Server to a host in the emulated network.
`getAllServerNames()` returns the names of the Ethereum nodes, Faucet, and
Utility servers. This example applies a node-name filter and uses `Action.FIRST`
to select the first eligible host that has not already been bound.

```python
from seedemu.core import Action, Binding, Filter

for servers in blockchain.getAllServerNames().values():
    for vnode in servers:
        emu.addBinding(
            Binding(
                vnode,
                filter=Filter(nodeName="host_*"),
                action=Action.FIRST,
            )
        )
```

## How to run

From the repository root, generate the deployment files, then build and start
the containers:

```bash
cd examples/ethereum/E00_ethereum_poa
python ethereum_poa.py
cd output
docker compose build
docker compose up -d
```

The script defaults to AMD64. To select ARM64, run `python ethereum_poa.py arm`
instead. Stop the emulation from the `output` directory with:

```bash
docker compose down
```
