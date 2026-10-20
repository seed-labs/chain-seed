# Validator at Running

This example demonstrates how to add a validator to an Ethereum PoS
blockchain after the blockchain has already started. It is based on the
PoS blockchain from [E01_ethereum_pos](../E01_ethereum_pos).

In E01, all validators are created before the genesis block and become
part of the initial validator set. In this example, the blockchain
starts first. A new validator is then created, imported into a
Lighthouse validator client, funded with a 32 ETH deposit, and finally
activated by the beacon chain.


## Table of Content

- [How to Run](#how-to-run)
- [Example Architecture](#example-architecture)
- [Create the Validator-at-Running Container](#create-the-validator-at-running-container)
- [Run the Validator Setup Script](#run-the-validator-setup-script)
- [What the Setup Script Does](#what-the-setup-script-does)
- [Observe the Validator Status](#observe-the-validator-status)
- [Test Script](#test-script)
- [Restart the Validator Client](#restart-the-validator-client)
- [Important Notes](#important-notes)


## How to Run

Run the following commands from this example directory:

```bash
python3 validator.py [amd|arm]
cd output
docker compose build
docker compose up
```

Arguments:

- `amd`: Generate Docker configuration for AMD64. This is the default.
- `arm`: Generate Docker configuration for ARM64 hosts.

This example always uses the PoS blockchain from `E01_ethereum_pos`. It
does not take a `poa` or `pos` argument.


## Example Architecture

This example first creates the same type of Ethereum PoS blockchain as
E01. It contains:

| Component | Role |
| --- | --- |
| Geth nodes | Execution-layer nodes. They execute transactions and expose Ethereum JSON-RPC |
| Beacon nodes | Consensus-layer nodes. They track slots, epochs, validator status, attestations, and blocks |
| Validator clients | Lighthouse validator clients that hold validator keys and sign duties |
| Beacon setup node | Generates and distributes the local testnet configuration |
| Deposit contract | Execution-layer contract that accepts 32 ETH validator deposits |
| Validator-at-running node | A new validator client container added by this example |

The validator-at-running container is not part of the genesis validator
set. It joins later by creating a validator key and sending a 32 ETH
deposit transaction to the deposit contract.


## Create the Validator-at-Running Container

The example adds one extra VC node to the E01 PoS blockchain:

```python
vc_at_running_1: PoSVcServer = blockchain.createVcNode("vcnodeAtRunning")
vc_at_running_1.appendClassName("Ethereum-POS-Validator-AtRunning")
vc_at_running_1.connectToBeaconNode("beaconnode0")
vc_at_running_1.enablePOSValidatorAtRunning()
emu.getVirtualNode("vcnodeAtRunning").setDisplayName(
    "Ethereum-POS-Validator-AtRunning-1"
)
```

The generated container name is similar to:

```text
as161h-Ethereum-POS-Validator-AtRunning-1-10.161.0.71
```

You can find the actual container name with:

```bash
docker ps | grep -i Validator-AtRunning
```


## Run the Validator Setup Script

The setup script is:

```text
vc_start_at_running.sh
```

Copy it into the validator-at-running container:

```bash
docker cp vc_start_at_running.sh \
  <validator-at-running-container-name>:/tmp/
```

If you are already inside the generated `output` directory, use:

```bash
docker cp ../vc_start_at_running.sh \
  <validator-at-running-container-name>:/tmp/
```

Then execute the script:

```bash
docker exec -it <validator-at-running-container-name> \
  bash /tmp/vc_start_at_running.sh
```

During execution, Lighthouse first prints a 24-word BIP-39 mnemonic.
Save this mnemonic. When the script later asks:

```text
Enter the mnemonic phrase:
```

paste the same 24-word mnemonic exactly as printed.


## What the Setup Script Does

The script performs the following steps:

1. Reads the execution-layer account from `/tmp/keystore` and uses it
   as the fee recipient.
2. Creates a Lighthouse wallet named `seed` under
   `/tmp/vc/local-testnet/testnet`.
3. Uses `lighthouse validator-manager create` to generate one new
   validator key and deposit data.
4. Starts a Lighthouse validator client connected to the beacon node at
   `http://10.151.0.72:8000`.
5. Imports the generated validator key into the validator client through
   the validator client HTTP API.
6. Sends a 32 ETH deposit transaction through the Geth RPC endpoint at
   `http://10.150.0.72:8545`.

The deposit transaction calls the standard Ethereum deposit contract:

```text
0x00000000219ab540356cBB839Cbe05303d7705Fa
```

After the deposit is included in a block and processed by the beacon
chain, the new validator enters the activation queue. It becomes active
only after the beacon chain activates it.


## Observe the Validator Status

The validator client log is written to:

```text
/tmp/lighthouse-vc.log
```

Use the following command to follow the log:

```bash
docker exec -it <validator-at-running-container-name> \
  tail -f /tmp/lighthouse-vc.log
```

These log entries mean the validator client started and imported the
key, but the validator is not active yet:

```text
Enabled validator
Imported keystores via standard HTTP API
Connected to beacon node(s)
Awaiting activation
```

To query the beacon node directly, use the validator public key printed
in the log:

```bash
curl -s \
  http://10.151.0.72:8000/eth/v1/beacon/states/head/validators/<validator-pubkey> \
  | jq
```

Common validator states include:

| State | Meaning |
| --- | --- |
| `pending_initialized` | The deposit has been seen, but the validator is not queued for activation yet |
| `pending_queued` | The validator is waiting in the activation queue |
| `active_ongoing` | The validator is active and can perform duties |

When the validator becomes active, the log will show messages similar
to the following:

```text
All validators active
Successfully published attestation
```

If this validator is selected to propose a block, the log will show
messages similar to:

```text
Requesting unsigned block
Publishing signed block
Successfully published block
```


## Test Script

The test script is:

```text
test_vc_at_running.py
```

It is a runtime monitor. It does not create a validator and it does not
send a deposit. You should run it only after the emulator is running and
after `vc_start_at_running.sh` has been executed.

Run it from this example directory:

```bash
python3 test_vc_at_running.py
```

By default, it checks the beacon API at `http://10.151.0.72:8000` and
monitors validator rank `10`. This matches the default topology: E01
creates 9 validators at genesis, so the validator added by this example
is expected to become the 10th validator in the beacon registry.

The script repeatedly queries:

```text
/eth/v1/beacon/headers/head
/eth/v1/beacon/states/head/validators
```

It waits until the watched validator has been seen in a pending state
and later in an active state. Success looks like this:

```text
OK: validator_index=9 transitioned pending -> active
```

If the validator does not become active before the timeout, the script
exits with code `2`. You can tune the monitor if your topology is
different:

```bash
python3 test_vc_at_running.py \
  --beacon-api http://10.151.0.72:8000 \
  --rank 10 \
  --timeout-secs 7200 \
  --interval-secs 12
```


## Restart the Validator Client

The setup script is intended for the initial setup. Do not repeatedly
run the whole script after the wallet and validator key have already
been created. Re-running the full script can fail with:

```text
Unable to create wallet: NameAlreadyTaken("seed")
```

If the validator client stops after the key has already been imported
and the deposit has already been sent, restart only the Lighthouse
validator client:

```bash
docker exec -d <validator-at-running-container-name> bash -lc '
exec lighthouse --debug-level info vc \
  --datadir /tmp/vc/local-testnet/testnet \
  --testnet-dir /tmp/vc/local-testnet/testnet \
  --init-slashing-protection \
  --beacon-nodes http://10.151.0.72:8000 \
  --suggested-fee-recipient <fee-recipient-address> \
  --http \
  --http-address 0.0.0.0 \
  --http-port 5062 \
  --http-allow-origin "*" \
  --unencrypted-http-transport \
  --enable-doppelganger-protection \
  > /tmp/lighthouse-vc.log 2>&1
'
```

The fee recipient address is printed near the beginning of the setup
script output:

```text
[INFO] FEE_RECIPIENT=...
```

Then verify that the validator client is running:

```bash
docker exec -it <validator-at-running-container-name> \
  ps aux | grep lighthouse
```


## Important Notes

- `Awaiting activation` is not the same as being active. The validator
  is active only after the beacon API reports `active_ongoing` or the
  log shows successful attestation duties.
- The 32 ETH deposit is a normal execution-layer transaction sent to
  the deposit contract. The beacon chain later reads and processes this
  deposit.
- The validator public key identifies the validator on the beacon
  chain. The execution-layer fee recipient address is different from
  the validator public key.
- Keep the generated mnemonic private in real deployments. In this lab,
  the mnemonic is used only inside the local emulator.
- This example uses fixed internal addresses, including
  `http://10.150.0.72:8545` for Geth RPC and
  `http://10.151.0.72:8000` for the beacon node API. These addresses
  come from the generated E01-based topology.
