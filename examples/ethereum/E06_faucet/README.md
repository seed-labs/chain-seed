# Faucet Server

Before sending a transaction to the blockchain, the user's account
needs to have some fund. In most test nets, a faucet server is provided
to fund users' accounts after receiving requests. We have implemented
such a faucet server in the SEED blockchain emulator.

This example demonstrates how to use the Faucet server with either a
PoA blockchain based on [E00_ethereum_poa](../E00_ethereum_poa) or a
PoS blockchain based on [E01_ethereum_pos](../E01_ethereum_pos).


## Table of Content

- [How to Run](#how-to-run)
- [Create Faucet Server](#create-faucet-server)
- [How Faucet Works](#how-faucet-works)
- [Fund Accounts Using Faucet](#fund-accounts-using-faucet)
- [Fund Accounts During the Build Time](#fund-accounts-during-the-build-time)
- [Fund Accounts During the Run Time Using curl](#fund-accounts-during-the-run-time-using-curl)
- [Fund Accounts During the Run Time Using FaucetUserService](#fund-accounts-during-the-run-time-using-faucetuserservice)
- [Fund Accounts During the Run Time Using Python](#fund-accounts-during-the-run-time-using-python)
- [Observe Funding Results](#observe-funding-results)
- [Developer Manual](#developer-manual)


## How to Run

Run the following commands from this example directory:

```bash
python faucet.py [poa|pos] [amd|arm]
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
python faucet.py poa amd
```

```bash
python faucet.py pos arm
```

The script loads the selected blockchain component, gets the existing
Faucet server from that blockchain, adds build-time funding requests,
and creates a `FaucetUserService` container to demonstrate runtime
funding.


## Create Faucet Server

We first need to add a Faucet server to a blockchain. This server runs
a web server, which can transfer funds from its own account to whoever
requests funds.

In the PoA blockchain from [E00_ethereum_poa](../E00_ethereum_poa),
the Faucet server is created as follows:

```python
faucet: FaucetServer = blockchain.createFaucetServer(
        vnode='faucet',
        port=80,
        linked_eth_node='eth5',
        balance=10000,
        max_fund_amount=10)
faucet.setDisplayName('Faucet')
```

In the PoS blockchain from [E01_ethereum_pos](../E01_ethereum_pos),
the Faucet server is linked to a Geth execution-layer node:

```python
faucet: FaucetServer = blockchain.createFaucetServer(
        vnode='faucet',
        port=80,
        linked_eth_node='gethnode1',
        balance=10000,
        max_fund_amount=10)
faucet.setDisplayName('Faucet')
```

We can specify the following parameters:

- `vnode`: the virtual node name of the Faucet server.
- `port`: the port number used by the Faucet web server.
- `linked_eth_node`: the Ethereum node used by the Faucet server to
  send transactions to the blockchain. This node must have HTTP RPC
  enabled.
- `balance`: the initial balance, in Ethers, of the Faucet account.
  This account is created during the build time and added to the
  genesis block.
- `max_fund_amount`: the maximal amount of fund, in Ethers, that can
  be transferred in each request.

Because the selected base blockchain already has a Faucet server, this
example gets the existing Faucet server object:

```python
eth         = emu.getLayer('EthereumService')
blockchain  = eth.getBlockchainByName(eth.getBlockchainNames()[0])
faucet_name = blockchain.getFaucetServerNames()[0]
faucet      = blockchain.getFaucetServerByName(faucet_name)
```


## How Faucet Works

The Faucet server is not an Ethereum node. It is a web service that
owns an Ethereum account. When it receives a `/fundme` request, it
constructs a transaction from its own account to the requested recipient
address, signs the transaction with the Faucet account's private key,
and sends the raw transaction through the linked Ethereum node's HTTP
RPC interface.

Therefore, the Faucet does not directly modify account balances. It
funds an account by sending a normal Ethereum transaction.


## Fund Accounts Using Faucet

This example demonstrates three ways to fund accounts:

- Fund known addresses during the build time.
- Fund an address during the run time using `curl`.
- Fund a dynamically created account during the run time using
  `FaucetUserService`.


## Fund Accounts During the Build Time

During the emulator build time, if we already know the account address,
we can ask the Faucet to fund it. The actual transaction is carried out
after the emulator starts.

```python
faucet.fund('0x72943017a1fa5f255fc0f06625aec22319fcd5b3', 2)
faucet.fund('0x5449ba5c5f185e9694146d60cfe72681e2158499', 5)
```

These API calls generate startup commands for the Faucet container.
When the emulation starts and the Faucet server becomes ready, those
commands send HTTP requests to the Faucet server.


## Fund Accounts During the Run Time Using curl

Very often, we do not know the account addresses during the build time,
because the accounts are created during the run time. In this case, the
user can send an HTTP request to the Faucet server to ask it to fund a
specified account.

First find the Faucet container and its IP address:

```bash
docker ps | grep -i faucet
docker inspect <faucet-container-name>
```

Check whether the Faucet server is running:

```bash
curl http://<faucet-ip>:80/
```

The expected response is:

```text
OK
```

Data in the funding request can be conveyed using either form data or
JSON data.

Using form data:

```bash
curl -X POST \
  -d "address=0x72943017a1fa5f255fc0f06625aec22319fcd5b3&amount=2" \
  http://<faucet-ip>:80/fundme
```

Using JSON data:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"address":"0x72943017a1fa5f255fc0f06625aec22319fcd5b3","amount":2}' \
  http://<faucet-ip>:80/fundme
```

The requested amount cannot exceed `max_fund_amount`, which is `10` in
this example.


## Fund Accounts During the Run Time Using FaucetUserService

This example also creates a `FaucetUserService` container. It
demonstrates how a service can create an account during the emulator
run time and then request funds from the Faucet server.

```python
faucetUserService = FaucetUserService()
faucetUserService.install('faucetUser').setDisplayName('FaucetUser')
faucet_info = blockchain.getFaucetServerInfo()
faucetUserService.setFaucetServerInfo(faucet_info[0]['name'],
                                      faucet_info[0]['port'])
emu.addBinding(Binding('faucetUser'))
emu.addLayer(faucetUserService)
```

The `FaucetUserService` resolves the Faucet server's IP address from
the Faucet vnode name and port number. It then generates the following
script inside the `faucetUser` container:

```text
/faucet_user/fundme.py
```

When the `faucetUser` container starts, this script waits for the
Faucet server to become available. If no account address is given to
the script, it creates a new Ethereum account and sends a `/fundme`
request for that new account.

After the emulator starts, use the following command to observe this
runtime funding process:

```bash
docker logs <faucetuser-container-name>
```

The logs should include the newly created account address and a success
message from the Faucet server.


## Fund Accounts During the Run Time Using Python

We can also write Python programs to interact with the Faucet server.
A helper class called
[FaucetHelper.py](../../../library/blockchain/FaucetHelper.py) is
created to make writing such programs easier.

The helper sends a JSON request to the Faucet server's `/fundme` API:

```python
from FaucetHelper import FaucetHelper

faucet = FaucetHelper("http://<faucet-ip>:80")
faucet.wait_for_server_ready()
faucet.send_fundme_request(
        "0x72943017a1fa5f255fc0f06625aec22319fcd5b3",
        2)
```


## Observe Funding Results

The best way to understand the Faucet is to observe both the web
request and the blockchain transaction.

First check the `faucetUser` logs:

```bash
docker logs <faucetuser-container-name>
```

Then check the Faucet server logs:

```bash
docker logs <faucet-container-name>
```

The Faucet logs should show the recipient address, requested amount,
transaction hash, and transaction receipt.

To verify the recipient balance using Geth HTTP RPC, find a Geth node
IP address and run:

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"eth_getBalance","params":["<recipient-address>","latest"],"id":1}' \
  http://<geth-ip>:8545
```

The returned balance is in Wei and encoded as a hexadecimal number.

For PoS runs, ChainSeed EthExplorer is enabled by default and can be
disabled with `--no-eth-explorer`. PoA runs do not enable it because the
Beacon consensus endpoint required by EthExplorer is not present.


## Developer Manual

The `FaucetUserService` section above shows how to request funds during
runtime from a service container. For implementation details about how
to build a custom service that uses the Faucet server, see the
[developer manual](../../../docs/developer_manual/blockchain/faucet-user-service.md).
