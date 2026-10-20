# EthUtilityServer

The Utility server has two roles. The first role is to help deploy
smart contracts, and the second role is to provide contract addresses
to other services. In Ethereum, once a contract has been deployed, it
is assigned an address. Users and applications need this address to
interact with the contract.

This example demonstrates how to use the Utility server with either a
PoA blockchain based on [E00_ethereum_poa](../E00_ethereum_poa) or a
PoS blockchain based on [E01_ethereum_pos](../E01_ethereum_pos). It
also shows how a contract deployment is prepared during emulator build
time and carried out after the emulator starts.


## Table of Content

- [How to Run](#how-to-run)
- [Create Utility Server](#create-utility-server)
- [Smart Contract Files](#smart-contract-files)
- [Deploy a Contract](#deploy-a-contract)
- [How Deployment Works](#how-deployment-works)
- [Interact with the Utility Server Using curl](#interact-with-the-utility-server-using-curl)
- [Observe Deployment Results](#observe-deployment-results)
- [Interact with the Utility Server Using Python](#interact-with-the-utility-server-using-python)


## How to Run

Run the following commands from this example directory:

```bash
python deploy_contract.py [poa|pos] [amd|arm]
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
python deploy_contract.py poa amd
```

```bash
python deploy_contract.py pos arm
```

The script loads the selected blockchain component, gets the existing
Utility server from that blockchain, registers the contract files with
the Utility server, and generates the Docker output.


## Create Utility Server

We first need to add a Utility server to a blockchain. The Utility
server runs a web server for contract address registration and lookup.
It can also deploy contracts after the emulator starts.

In the PoA blockchain from [E00_ethereum_poa](../E00_ethereum_poa),
the Utility server is created as follows:

```python
util_server: EthUtilityServer = blockchain.createEthUtilityServer(
        vnode='utility',
        port=5000,
        linked_eth_node='eth6',
        linked_faucet_node='faucet')
```

In the PoS blockchain from [E01_ethereum_pos](../E01_ethereum_pos),
the Utility server is linked to a Geth execution-layer node:

```python
util_server: EthUtilityServer = blockchain.createEthUtilityServer(
        vnode='utility',
        port=5000,
        linked_eth_node='gethnode2',
        linked_faucet_node='faucet')
```

We can specify the following parameters:

- `vnode`: the virtual node name of the Utility server.
- `port`: the port number used by the Utility server web API.
- `linked_eth_node`: the Ethereum node used by the Utility server to
  send contract deployment transactions. This node must have HTTP RPC
  enabled.
- `linked_faucet_node`: the Faucet server used to fund the account that
  deploys contracts.

Because the selected base blockchain already has a Utility server, this
example gets the existing Utility server object:

```python
eth        = emu.getLayer('EthereumService')
blockchain = eth.getBlockchainByName(eth.getBlockchainNames()[0])
name       = blockchain.getUtilityServerNames()[0]
utility    = blockchain.getUtilityServerByName(name)
```


## Smart Contract Files

The contract files used by this example are located in the `Contracts`
directory:

```text
Contracts/contract.sol
Contracts/contract.abi
Contracts/contract.bin
```

The files have different purposes:

- `contract.sol`: the Solidity source code. This is the human-readable
  contract program.
- `contract.abi`: the contract interface description. Applications use
  it to know which functions exist and how to encode calls.
- `contract.bin`: the compiled EVM bytecode. This is the code deployed
  to the blockchain.

The example contract is a small `Crowdfunding` contract:

```solidity
contract Crowdfunding {
    uint256 amount;

    receive() external payable {
        amount += msg.value;
    }

    function claimFunds(address payable _to, uint _amount) public payable {
        _to.transfer(_amount);
    }
}
```

The `receive()` function is triggered when ETH is sent directly to the
contract address. The `claimFunds()` function transfers funds from the
contract balance to a specified address. This contract is only a simple
teaching example; it does not implement access control.


## Deploy a Contract

To deploy a contract using the Utility server, we need to provide the
ABI file and the bytecode file. The paths can be either relative or
absolute.

```python
utility.deployContractByFilePath(
        contract_name='test',
        abi_path='./Contracts/contract.abi',
        bin_path='./Contracts/contract.bin')
```

This API does not immediately deploy the contract. During emulator build
time, it registers the contract files with the Utility server. The
actual deployment happens after the emulator starts.

The contract is registered under the name `test`. After deployment, the
Utility server stores a mapping from this name to the deployed contract
address.


## How Deployment Works

A contract deployment is an Ethereum transaction. The Utility server
must therefore have an account with enough ETH to pay gas.

When the Utility container starts, it runs the following setup script:

```bash
python3 ./fund_account.py
python3 ./deploy_contract.py
```

The setup process works as follows:

1. The Utility server connects to the linked Ethereum node through HTTP
   RPC.
2. It creates a new Ethereum account and saves the address and private
   key in `/utility_server/account.json`.
3. It sends a `/fundme` request to the linked Faucet server.
4. It waits until the new account has a positive balance.
5. It reads the registered ABI and BIN files.
6. It constructs a contract deployment transaction.
7. It signs the transaction using the generated account's private key.
8. It sends the raw transaction through the linked Ethereum node.
9. After the transaction is confirmed, it saves the deployed contract
   address in `/utility_server/deployed_contracts/contract_address.txt`.

The Utility server is therefore not the smart contract itself. It is a
helper service that funds a deployer account, sends the deployment
transaction, and records the resulting contract address.


## Interact with the Utility Server Using curl

After the emulator starts, we can interact with the Utility server using
`curl`. First find the Utility container and its IP address:

```bash
docker ps | grep -i utility
docker inspect <utility-container-name>
```

Check whether the Utility server is running:

```bash
curl http://<utility-ip>:5000/
```

The expected response is:

```text
OK
```

### Register a Contract

To register a contract address manually, send a POST request to the
`/register_contract` API:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"contract_name":"test999","contract_address":"0xc0ffee254729296a45a3885639AC7E10F9d54979"}' \
  http://<utility-ip>:5000/register_contract
```

This only registers a name-address mapping in the Utility server. It
does not deploy a new contract to the blockchain.

### Get a List of Registered Contracts

Use either of the following APIs to get all registered contract
addresses:

```bash
curl http://<utility-ip>:5000/all
curl http://<utility-ip>:5000/contracts_info
```

### Get a Contract Address by Name

To get the address of a particular contract, provide the `name`
argument:

```bash
curl http://<utility-ip>:5000/contracts_info?name=test
```


## Observe Deployment Results

The best way to understand contract deployment is to observe both the
Utility server logs and the blockchain state.

First check the Utility server logs:

```bash
docker logs <utility-container-name>
```

The logs should show that the Utility server connected to the Ethereum
node, requested funds from the Faucet server, funded the deployer
account, and deployed the contract.

Then inspect the generated files inside the Utility container:

```bash
docker exec -it <utility-container-name> bash
cat /utility_server/account.json
cat /utility_server/contracts/contract_file_paths.txt
cat /utility_server/deployed_contracts/contract_address.txt
```

The `account.json` file contains the deployer account created by the
Utility server. The `contract_address.txt` file contains the deployed
contract address, for example:

```json
{
    "test": "0x..."
}
```

To verify that the address is really a contract on the blockchain, use
Geth HTTP RPC to query the code stored at the address:

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"eth_getCode","params":["<contract-address>","latest"],"id":1}' \
  http://<geth-ip>:8545
```

If the result is `"0x"`, there is no contract code at that address. If
the result is a long hexadecimal string, the contract bytecode has been
stored on chain.

For PoS runs, ChainSeed EthExplorer is enabled by default and can be
disabled with `--no-eth-explorer`. PoA runs do not enable it because the
Beacon consensus endpoint required by EthExplorer is not present.


## Interact with the Utility Server Using Python

We can write Python programs to interact with the Utility server. A
helper class called
[UtilityServerHelper.py](../../../library/blockchain/UtilityServerHelper.py)
is created to make writing such programs easier.

For example, a program can query the address of the deployed `test`
contract from the Utility server and then use that address together
with the contract ABI to interact with the smart contract.
