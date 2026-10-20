# Solana Large-Scale Network

This example creates 200 Solana nodes using the final experiment's genesis-voting
and low-memory configuration. Install SeedEmu and ChainSEED in the same Python
environment. Run these commands from this example directory.

## Build the image and compile

Build the shared Agave image once:

```bash
docker build -t seedemu-solana ../../../images/solana
python solana_large_scale.py
```

The image recipe pins Agave v2.2.14. Use `--image IMAGE` for a compatible prepared
image or an immutable local image ID. Generated node files are mounted into the
shared image; no per-node image build is needed.

## Start

Inspect or apply the host limits before starting a large deployment:

```bash
../../../tools/solana/large_scale/host_tuning.sh show
sudo ../../../tools/solana/large_scale/host_tuning.sh apply
```

Start infrastructure, bootstrap and the first validator, then check the core:

```bash
./up.sh --phase core
python ../../../tools/solana/large_scale/check_health.py \
  --deployment output --core --output results/run-1/core-ready.jsonl
```

Start the remaining nodes in batches and check the full deployment:

```bash
./up.sh --phase validators
python ../../../tools/solana/large_scale/check_health.py \
  --deployment output --output results/run-1/ready.jsonl
```

Readiness includes a stable window: 120 seconds for the core, 2,400 seconds for
the full deployment. See `--help` to adjust these waits for smaller runs.

## Measure

```bash
python ../../../tools/solana/large_scale/measure.py \
  --deployment output --run-dir results/run-1 --duration 18000
```

Optionally send native SOL transfers in another terminal:

```bash
python ../../../tools/solana/large_scale/send_transactions.py \
  --deployment output --run-dir results/run-1 --rate 0.05 --duration 18000
```

Wait for measurement and optional transaction confirmation to finish, then summarize:

```bash
python ../../../tools/solana/large_scale/summarize.py --run-dir results/run-1
```

Results are saved in `results/run-1/summary/`. Use a new run directory each time.

## Stop

```bash
./down.sh
sudo ../../../tools/solana/large_scale/host_tuning.sh restore
```

Stopping removes containers and runtime genesis/barrier state. Generated keys and
observation records remain available.

## Reuse a network

```bash
python mini_internet.py --output network.bin
python solana_large_scale.py --network network.bin --output custom-output
./up.sh --output custom-output --phase core
```

Continue the same health/start/measurement steps with `--deployment custom-output`.
Use `./up.sh --output custom-output --phase validators` and
`./down.sh --output custom-output` for the remaining lifecycle steps.
Pass matching `--validators` and `--stub-as-count` values to both Python scripts
when changing the network size. Each compilation requires a new output directory.
