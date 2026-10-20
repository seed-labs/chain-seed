# Ethereum Large-Scale Network

This example creates an Ethereum PoS network using Geth and Lighthouse.
Install SeedEmu and ChainSEED in the same Python environment before running it.

Run the following commands from this example directory.

## Compile and start

```bash
python ethereum_large_scale.py
./up.sh
```

Client options are set on individual Server instances in
`ethereum_large_scale.py`. To change the example's common values from the command line:

```bash
python ethereum_large_scale.py --worker-cap 4 --geth-cache-mib 128 \
  --geth-gomemlimit-mib 512 --keys-per-client 100 --genesis-delay 1800
```

Use `--no-reconstruct-historic-states` to omit historical-state reconstruction.
See the [Server configuration API](../../../docs/user_manual/blockchain/server_configuration.md)
for configuring individual clients differently.

The generated deployment is saved in `output/`. To view container status:

```bash
docker compose -p chainseed-e12 -f output/docker-compose.yml ps -a
```

## Check health

Startup may take some time. Check that the chain is ready:

```bash
python ../../../tools/ethereum/large_scale/check_health.py \
  --compose output/docker-compose.yml --run-dir results/run-1
```

## Deploy workload contracts

```bash
python ../../../tools/ethereum/transaction_generator/deploy_contracts.py \
  --compose-file output/docker-compose.yml --accounts 1000 \
  --output results/run-1/tx-load/contracts.json
```

## Collect data and send transactions

Start collection in one terminal:

```bash
python ../../../tools/ethereum/large_scale/measure.py \
  --compose output/docker-compose.yml --run-dir results/run-1
```

Start receipt collection in a second terminal, from the same directory:

```bash
python ../../../tools/ethereum/transaction_generator/collect_tx_receipts.py \
  --compose-file output/docker-compose.yml \
  --tx-log results/run-1/tx-load/tx_sender.csv --output results/run-1/tx_receipts.csv \
  --mode blocks --interval 2 --sender-state results/run-1/tx-load/run_info.json
```

Send transactions in a third terminal:

```bash
python ../../../tools/ethereum/transaction_generator/send_transactions.py \
  --compose-file output/docker-compose.yml --accounts 1000 \
  --contracts-file results/run-1/tx-load/contracts.json --log-dir results/run-1/tx-load \
  --phases steady:20:18000 --phase-settle-seconds 0 \
  --send-workers 32 --sign-workers 4 --rpc-targets 32 --queue-depth 512
```

When both sending and receipt collection finish, press Ctrl-C in the measurement terminal.

## View observations

To include Lookingglass in the deployment, compile with:

```bash
python ethereum_large_scale.py --lookingglass
./up.sh
```

Open http://127.0.0.1:8765. Lookingglass runs on an additional emulated host and
shows every Ethereum chain. The batching script builds that host's application
image and starts it with the deployment; `./down.sh` stops it too.
Add `--lookingglass-run-dir results/run-1` to show separately collected resources
and transactions. Node queries work without measurement scripts.

See the [Lookingglass manual](../../../docs/user_manual/blockchain/lookingglass.md)
for optional settings.

## Summarize

```bash
python ../../../tools/ethereum/large_scale/summarize.py --run-dir results/run-1
```

Results are saved in `results/run-1/summary/`. Use a new results directory for each run.

## Stop

```bash
./down.sh
```

## Reuse a network

To generate the network separately and use it for the Ethereum deployment:

```bash
python mini_internet.py --output network.bin
python ethereum_large_scale.py --network network.bin --output custom-output
./up.sh --output custom-output
./down.sh --output custom-output
```

Use each script's `--help` option for available arguments.
