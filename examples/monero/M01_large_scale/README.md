# Monero Large-Scale Network

This example creates 1,200 Monero nodes across 100 stub ASes, connected through
IX100 and transit AS2. Six nodes are seeds. One single-threaded miner starts
automatically; the remaining nodes maintain and propagate the ledger.
The Service supplies seed endpoints using `MoneroSeedConnectionMode.SEED`.

Install SeedEmu and ChainSEED in the same Python environment. Run the following
commands from this example directory.

## Compile and start

The default image is `handsonsecurity/seedemu-monero:latest`, containing
`monerod`, `monero-wallet-cli` and `monero-wallet-rpc`.
Its build recipe is in `../../../images/monero`. Pass `--image IMAGE` to use
another compatible image extending the SeedEmu base.

```bash
python monero_large_scale.py --tx-wallets 16
docker compose -p chainseed-monero-m01 -f output/docker-compose.yml pull
./up.sh
```

If the required images are already available locally, skip `pull`. Generated
node files are mounted into shared images; no per-node image build is needed.

```bash
docker compose -p chainseed-monero-m01 -f output/docker-compose.yml ps -a
docker compose -p chainseed-monero-m01 -f output/docker-compose.yml logs -f
```

`output/nodes.json` records node addresses and initial roles. With `--tx-wallets`,
`output/wallets.json` records the funding wallet and sender RPC credentials.
Node 6 is the initial miner and funding wallet; the final 16 nodes are senders.
No fixed difficulty is configured.

## Check health and prepare wallets

```bash
python ../../../tools/monero/large_scale/check_health.py \
  --deployment output --output results/run-1/readiness.jsonl
python ../../../tools/monero/large_scale/prepare_wallets.py \
  --deployment output --run-dir results/run-1 --funding-rounds 16
```

Wallet preparation waits for mining rewards and funded outputs to unlock.
Use a new run directory for each experiment.

## Configure miners

Initialize the target miner count:

```bash
python ../../../tools/monero/large_scale/miners.py \
  --deployment output --state results/run-1/miner-state.json --count 1 --initialize
python ../../../tools/monero/large_scale/check_health.py \
  --deployment output --miner-state results/run-1/miner-state.json \
  --output results/run-1/miners-ready.jsonl
```

Use `--count 1`, `10`, `100` or `200` for the paper's configurations. For larger
counts, add `--ramp-step 10` to initialization to increase mining gradually and
wait for health and block-rate checks at each level.

Start rotation in one terminal, using the same count:

```bash
python ../../../tools/monero/large_scale/miners.py \
  --deployment output --state results/run-1/miner-state.json --count 1 --interval 900
```

## Measure and send transactions

Start measurement in a second terminal:

```bash
python ../../../tools/monero/large_scale/measure.py \
  --deployment output --run-dir results/run-1 --miner-state results/run-1/miner-state.json
```

Send transfers in a third terminal:

```bash
python ../../../tools/monero/large_scale/send_transactions.py \
  --deployment output --run-dir results/run-1 --rate 0.3 --duration 18000
```

The sender waits for two-node confirmation after sending finishes. When it exits,
stop measurement and rotation with Ctrl-C, then summarize:

```bash
python ../../../tools/monero/large_scale/summarize.py --run-dir results/run-1
```

Results are saved in `results/run-1/summary/`. See the
[tools manual](../../../tools/monero/large_scale/README.md) for record formats
and checks.

## Stop

```bash
./down.sh
```

Stopping removes containers and their chain/wallet state. The generated files
remain available for a fresh run.

## Reuse a network

```bash
python mini_internet.py --output network.bin
python monero_large_scale.py --network network.bin --tx-wallets 16 --output custom-output
./up.sh --output custom-output
./down.sh --output custom-output
```

For a smaller deployment, pass the same `--nodes` and `--stub-as-count` values
to both Python scripts. Each compilation requires a new output directory.
Use `--help` for available arguments.
