# Blockchain Examples

Examples are grouped by chain. Each example has its own manual.

| Chain | Examples | Large-scale example |
| --- | --- | --- |
| [Chainlink](chainlink/) | C00 | — |
| [Ethereum](ethereum/) | E00–E14 | [E12](ethereum/E12_large_scale/) |
| [Monero](monero/) | M00–M01 | [M01](monero/M01_large_scale/) |
| [Solana](solana/) | S00–S01 | [S01](solana/S01_large_scale/) |

Install SeedEmu and ChainSeed in the same Python environment, then run an example:

```bash
python -m pip install /path/to/seed-emulator
python -m pip install .
python examples/ethereum/E01_ethereum_pos/ethereum_pos.py
```

For examples with an `example.yaml` manifest:

```bash
chainseed-test compile examples/ethereum/E01_ethereum_pos/example.yaml
chainseed-test all examples/ethereum/E01_ethereum_pos/example.yaml
```

Shared network definitions are in
[E00's mini_internet.py](ethereum/E00_ethereum_poa/mini_internet.py).
Export a reusable network with:

```bash
python examples/ethereum/E00_ethereum_poa/mini_internet.py \
  --topology hybrid --hosts-per-as 3 --dumpfile /tmp/network.bin
```

Other examples can call `mini_internet.build_emulator()` or load the exported
network with `Emulator.load()`. Each large-scale example contains its own
network definition. Observation and workload tools are in [`tools/`](../tools/).
Generated `output/` directories are not versioned.
