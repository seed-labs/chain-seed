# S00_solana: Solana Blockchain Service Example

This example deploys a **private, self-contained Solana cluster** on top of an
emulated Internet. It runs the real [Agave](https://github.com/anza-xyz/agave)
validator software (the production Solana client maintained by Anza), so the
same tools and workflows used against real Solana clusters work here unchanged.

The example mirrors the structure of [`M00_monero`](../../monero/M00_monero): build a base
Internet, attach the blockchain service, bind its virtual nodes to hosts,
render, and compile to Docker.

> **Platform note.** The cluster runs **natively on both amd64 and arm64**. The
> `seedemu-solana` base image downloads Agave's official prebuilt binaries on
> amd64, and (since Anza ships no arm64 Linux binaries) compiles the same pinned
> version from source on arm64. The arm64 source build is slow the first time
> (tens of minutes) but is cached afterward.

## What gets built

`solana_basic.py` builds a 10-stub-AS Internet (via `Makers`) and a private
Solana cluster of ten nodes:

| Virtual node          | Role                | AS  | Host    |
| --------------------- | ------------------- | --- | ------- |
| `sol-boot-150`        | bootstrap validator | 150 | host_0  |
| `sol-validator-150b`  | validator           | 150 | host_1  |
| `sol-validator-151`   | validator           | 151 | host_0  |
| `sol-validator-152`   | validator           | 152 | host_0  |
| `sol-validator-153`   | validator           | 153 | host_0  |
| `sol-validator-154`   | validator           | 154 | host_0  |
| `sol-validator-160`   | validator           | 160 | host_0  |
| `sol-validator-161`   | validator           | 161 | host_0  |
| `sol-validator-162`   | validator           | 162 | host_0  |
| `sol-validator-163`   | validator           | 163 | host_0  |

- The **bootstrap validator** creates the genesis ledger with `solana-genesis`,
  stakes itself, runs `solana-faucet`, and is the gossip entrypoint.
- The **same-AS validator** (AS150/host_1) joins over the local network.
- The **cross-AS validators** join over inter-domain (BGP) routing,
  demonstrating a larger cluster that spans the emulated Internet.

Each validator waits for the bootstrap RPC, generates its own identity and vote
keypairs, funds its identity with an airdrop (relayed through the bootstrap
RPC), creates a vote account, and joins the cluster via the bootstrap node's
gossip entrypoint.

All addresses (each node's own IP, and the bootstrap's gossip/RPC endpoint) are
resolved from the virtual-node bindings at render time — nothing is hard-coded
in the service (see the design notes below).

## Build and run

If you are at the repository root, enter this example directory first:

```bash
cd examples/solana/S00_solana
```

Prepare the emulation first. This builds the Solana base image, generates the
SEED output, builds the local Docker images, starts all containers, and leaves
the cluster running for inspection:

```bash
./prepare_solana.sh
```

The equivalent manual flow, from this directory, is:

```bash
# 1. Build the Solana base image
docker build -t seedemu-solana ../../../docker_images/solana

# 2. Generate the emulation (defaults to the host architecture; or pass amd|arm)
python3 solana_basic.py

# 3. Build and start the cluster
cd output
# Build the local base images first. seedemu node images do `FROM <digest>`,
# where each base image is built by a "dummy" service (one per file under
# output/dummies/). docker compose v2 builds in parallel, so build these first:
docker compose build $(ls dummies)
docker compose up -d --build
```

Give the cluster a couple of minutes to converge the first time. Tear it down
only when you are done:

```bash
(cd output && docker compose down -v --remove-orphans)
```

## Interacting and verifying

The bootstrap validator's RPC listens on port `8899` inside the emulated
network. The cluster is not port-mapped to the host, so query it by exec-ing
into the bootstrap container (AS150 / host_0). Resolve the container from
`docker ps` each time you start a new shell, because container ids change when
Docker recreates containers:

```bash
BOOT=$(docker ps --format '{{.Names}}' | grep '^as150h-Solana-Bootstrap-150-' | head -n 1)
test -n "$BOOT" || { echo "bootstrap container is not running"; exit 1; }

# Cluster software version (proves RPC is up)
docker exec "$BOOT" solana --url http://127.0.0.1:8899 cluster-version

# Current slot — run twice; it should increase (blocks are being produced)
docker exec "$BOOT" solana --url http://127.0.0.1:8899 slot
docker exec "$BOOT" solana --url http://127.0.0.1:8899 block-height

# Epoch info (slot, epoch, absolute slot, transaction count)
docker exec "$BOOT" solana --url http://127.0.0.1:8899 epoch-info

# Validators in the cluster (should list up to ten once converged)
docker exec "$BOOT" solana --url http://127.0.0.1:8899 validators

# Nodes seen over gossip
docker exec "$BOOT" solana --url http://127.0.0.1:8899 gossip
```

Raw JSON-RPC also works (e.g. `getSlot`, `getBlockHeight`, `getEpochInfo`):

```bash
docker exec "$BOOT" sh -c \
  'curl -sS --connect-timeout 3 http://127.0.0.1:8899 \
     -X POST -H "Content-Type: application/json" \
     -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"getSlot\"}";
   echo'
```

## Send transactions

Use the helper script instead of typing a long `docker exec` command. It finds
the bootstrap container, creates Alice/Bob keypairs on the first run, airdrops
SOL to Alice, transfers SOL to Bob, confirms the signature, and prints the final
balances:

```bash
python3 send_transaction.py
```

You can change the airdrop and transfer amount:

```bash
python3 send_transaction.py --airdrop 20 --amount 2
```

By default, later runs reuse the same Alice/Bob keypairs, so Bob's balance
increases each time. Start over with fresh accounts when needed:

```bash
python3 send_transaction.py --reset
```

If Alice is running out of SOL, top her up before the transfer:

```bash
python3 send_transaction.py --top-up --airdrop 10
```

Check the latest Alice/Bob balances created by the demo:

```bash
python3 show_balances.py
```

The script still reaches the RPC through the bootstrap container because this
example does not expose port `8899` on the host. The important Solana flow is
unchanged: Alice's keypair signs the transfer, the RPC receives the signed
transaction, the validator pipeline forwards it to a leader, and the leader
records it in a produced block.

## Deploy a program

Solana smart contracts are called **programs**. Deploying a program means
uploading a compiled SBF shared object (`.so`) to a program account. The
`seedemu-solana` runtime image contains the validator and Solana CLI; it does
not contain the Rust/SBF compiler. Build the program outside the emulator, then
copy the resulting `.so` into the bootstrap container for deployment.

This example includes a minimal Rust program at
`programs/noop_logger`. The program logs its program id, account count, and
instruction data length whenever it is invoked.

If your host already has the Solana/Agave SBF toolchain, build and deploy in one
step:

```bash
python3 deploy_program.py --build
```

If you already built the `.so`, deploy it directly:

```bash
python3 deploy_program.py --so programs/noop_logger/dist/seedemu_solana_noop.so
```

The script copies the `.so` into the bootstrap container, creates/funds a
deployer account, runs `solana program deploy`, extracts the program id, and
prints `solana program show`.

What happened during deployment:
- The deployer keypair signs the deployment transactions and pays fees/rent.
- The CLI uploads the SBF bytes into program-data accounts controlled by the
  upgradeable loader.
- The loader marks the final program account executable.
- After that, any Solana client can send an instruction addressed to the program
  id; validators execute the program while processing that transaction.
- Calling a custom program requires a client that constructs an instruction for
  that program id; the Solana CLI manages deployment but does not provide a
  generic `program invoke` subcommand.

## Automated test

`test_solana.sh` verifies an already-running cluster. It does **not** build
images, generate the emulation, start containers, recreate containers, or tear
anything down. Run `./prepare_solana.sh` first, then run:

```bash
./test_solana.sh                   # verify the running cluster
MIN_VALIDATORS=1 ./test_solana.sh  # accept a single voting validator
MIN_VALIDATORS=10 ./test_solana.sh # require all ten validators to be voting
```

## Logs and troubleshooting

```bash
BOOT=$(docker ps --format '{{.Names}}' | grep '^as150h-Solana-Bootstrap-150-' | head -n 1)

# Validator log (bootstrap)
docker exec "$BOOT" tail -n 100 -f /opt/solana/config/bootstrap-validator/*.log

# Faucet log
docker exec "$BOOT" cat /var/log/solana-faucet.log

# On a joining validator (AS151)
V=$(docker ps --format '{{.Names}}' | grep '^as151h-Solana-Validator-151-' | head -n 1)
docker exec "$V" tail -n 100 -f /opt/solana/config/validator/*.log
```

Notes:
- The first startup is slow: containers build, the bootstrap creates genesis,
  then validators fetch genesis/snapshots over gossip and create vote accounts.
- A single staked validator already advances slots, so block production is
  visible even before the other validators finish joining.
- Solana validators are CPU/IO intensive (see PRINCIPLES.md P9 on scale being a
  real, resource-bounded concern). Give Docker ample CPU/RAM for larger clusters.
- The cluster runs natively on amd64 and arm64, so all ten Solana nodes
  (including the cross-AS ones) converge on either architecture once BGP
  converges. (Running the amd64 image under emulation on an arm64 host is
  **not** recommended: the emulated validator binary cannot complete
  non-loopback connects, which blocks the joining validators — build the native
  arm64 image instead.)

## Ports

| Port        | Purpose                                  |
| ----------- | ---------------------------------------- |
| 8899        | JSON-RPC                                 |
| 8900        | RPC PubSub (websocket)                   |
| 8001        | gossip                                   |
| 9900        | faucet (bootstrap only)                  |
| 8002–8030   | dynamic range (TPU / turbine / repair)   |

## Design notes (alignment with PRINCIPLES.md)

- **P1 (execution-agnostic):** the service and topology declarations contain no
  Docker image names; `emu.compile(ChainSeedDocker(), ...)` selects the
  ChainSeed-aware backend.
- **P4 (virtual nodes + late binding):** validators are symbolic vnodes; their
  IPs and the bootstrap entrypoint are resolved from `Binding`s during
  `configure()`. No IPs/ASNs are hard-coded in the service.
- **P5 (real production software):** runs real `agave-validator` /
  `solana-genesis` / `solana-faucet`, pinned to a specific Agave release in
  `docker_images/solana/Dockerfile`.
- **P6 (self-contained module):** `SolanaService` exposes a small high-level API
  (`createBlockchain`, `createBootstrapValidator`, `createValidator`) and hides
  all genesis/keypair/faucet boilerplate.
