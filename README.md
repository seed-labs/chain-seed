# ChainSeed

[中文](README.zh-CN.md) | English

ChainSeed is a scalable, high-fidelity blockchain emulator built on the
[SEED Internet Emulator](https://github.com/seed-labs/seed-emulator). It combines
real blockchain clients with configurable routed networks, allowing researchers
to study blockchain performance, security, and applications under controlled
network conditions.

ChainSeed supports Ethereum, Monero, and Solana, together with Chainlink services.
It provides APIs and tools for configuring nodes, customizing genesis state and
peer connections, deploying smart contracts, and generating transaction workloads.
Monitoring and visualization tools help users inspect chain activity and node
behavior, with examples ranging from private testnets to large-scale deployments
and security experiments.

## Installation

ChainSeed depends on SeedEmu. Follow the
[SeedEmu installation instructions](https://github.com/seed-labs/seed-emulator/blob/development/README.md#getting-started)
to set up the required environment, including Python 3.10, Docker Engine,
and Docker Compose, then install SeedEmu from its `development` branch.
We recommend running a basic SeedEmu example to verify the environment
before installing ChainSeed.

Clone both repositories into the same workspace, using the `development` branch
of SeedEmu:

```bash
mkdir -p workspace
cd workspace

git clone --branch development https://github.com/seed-labs/seed-emulator.git
git clone https://github.com/seed-labs/chain-seed.git
```

```text
workspace/
├── seed-emulator/
└── chain-seed/
```

Enter `chain-seed`, then choose either Conda or uv below. The commands use
`../seed-emulator` to refer to the sibling SeedEmu checkout.

```bash
cd chain-seed
```

### Conda

```bash
conda create -n chainseed python=3.10 pip -y
conda activate chainseed
python -m pip install -e ../seed-emulator
python -m pip install .
```

### uv

```bash
uv venv --python 3.10
source .venv/bin/activate
uv pip install -e ../seed-emulator
uv pip install .
```

SeedEmu is installed in editable mode, so keep its source directory after installation.

## Quick start

From the `chain-seed` directory, run the Ethereum PoS example to generate the
Docker deployment files, then build and start the containers:

```bash
python examples/ethereum/E01_ethereum_pos/ethereum_pos.py
cd examples/ethereum/E01_ethereum_pos/output
docker compose build
docker compose up -d
```

To stop the emulation and remove its containers and networks, run the following
command from the `output` directory:

```bash
docker compose down
```

See the [Ethereum PoS example](examples/ethereum/E01_ethereum_pos/README.md)
for configuration and access instructions.

See [examples](examples/README.md) for blockchain configurations and deployment
examples. When copying examples, keep the complete `examples/` directory, as
some examples reuse code from others.

See [case studies](case_study/README.md) for experiments on routing attacks,
blockchain amplification attacks, topology discovery, and node connectivity.

## Monitoring and visualization

[EthExplorer](examples/ethereum/E02_eth_explorer/README.md) provides a web
interface for browsing Ethereum blocks, transactions, epochs, and validators.

[Lookingglass](docs/user_manual/blockchain/lookingglass.md) provides a global
view of Ethereum nodes, peer connections, and runtime status across the emulated
network.

## Documentation

- [User guide](docs/user_manual/blockchain/README.md)
- [Ethereum client configuration](docs/user_manual/blockchain/server_configuration.md)
- [Transaction generator](tools/ethereum/transaction_generator/README.md)

## License

ChainSeed is licensed under the [GNU General Public License v3.0](LICENSE.txt).
