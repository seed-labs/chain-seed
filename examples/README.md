# Blockchain Examples

Examples are arranged by D number. Each directory contains its own manual.

| Example | Contents |
| --- | --- |
| [D00](D00_ethereum_poa/) | Ethereum PoA and reusable network topology |
| [D01](D01_ethereum_pos/) | Ethereum PoS |
| [D05](D05_ethereum_small/) | Small Ethereum network |
| [D06](D06_ethereum_test/) | Ethereum test scripts |
| [D10](D10_eth_explorer/) | Ethereum explorer |
| [D11](D11_lookingglass/) | Global Ethereum Lookingglass |
| [D20](D20_faucet/) | Faucet |
| [D21](D21_deploy_contract/) | Contract deployment |
| [D22](D22_oracle/) | Oracle |
| [D23](D23_validator/) | Validators |
| [D27](D27_ipfs_kubo_dapp/) | IPFS/Kubo DApp |
| [D31](D31_chainlink/) | Chainlink |
| [D50](D50_blockchain/) | Blockchain configuration |
| [D60](D60_monero/) | Monero |
| [D61](D61_large_scale/) | Large-scale Ethereum, Monero and Solana networks |
| [D70](D70_solana/) | Solana |
| [D99](D99_tools/) | Ethereum helper scripts |
| [R00](R00_ethereum_pos_test/) | Ethereum PoS experiment scripts |

Install SeedEmu and ChainSeed in the same Python environment, then run an example:

```bash
python -m pip install /path/to/seed-emulator
python -m pip install .
python examples/D01_ethereum_pos/ethereum_pos.py
```

For examples with an `example.yaml` manifest:

```bash
chainseed-test compile examples/D01_ethereum_pos/example.yaml
chainseed-test all examples/D01_ethereum_pos/example.yaml
```

Shared network definitions are in
[D00's mini_internet.py](D00_ethereum_poa/mini_internet.py).
Export a reusable network with:

```bash
python examples/D00_ethereum_poa/mini_internet.py \
  --topology hybrid --hosts-per-as 3 --dumpfile /tmp/network.bin
```

Other examples can call `mini_internet.build_emulator()` or load the exported
network with `Emulator.load()`. D61 keeps separate network definitions for each
large-scale topology. Observation and workload tools are in [`tools/`](../tools/).
Generated `output/` directories are not versioned.
