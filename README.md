# ChainSeed

[中文](README.zh-CN.md) | English

ChainSeed provides blockchain protocol extensions for
[SeedEmu](https://github.com/seed-labs/seed-emulator). It owns Ethereum,
Monero, Solana, and Chainlink service layers together with their image recipes,
tools, examples, runtime probes, and large-scale experiment definitions.

The dependency direction is intentionally one way:

```text
chain-seed -> seed-emulator
seed-emulator -X-> chain-seed
```

## Relationship and prerequisites

ChainSeed is an add-on package, not a standalone replacement for SeedEmu. A
working SeedEmu checkout and Python environment are prerequisites. Before
adding ChainSeed, users should be able to render, compile, build, and run a
non-blockchain SeedEmu example in that environment.

ChainSeed may import documented public APIs from `seedemu`. In the opposite
direction, SeedEmu must never import or package ChainSeed. ChainSeed service
code should also avoid SeedEmu compiler internals so that normal SeedEmu
compiler refactors do not unnecessarily break the extension.

## Package integration

Blockchain services are imported from `chainseed.*`.
ChainSeed services assign compiler-neutral `SystemProfile` objects through
SeedEmu's existing `Node.setBaseSystem` API. `ChainSeedDocker` maps those
ChainSeed-owned profiles to platform-specific images. ChainSeed no longer depends on SeedEmu's blockchain image table; blockchain
implementations, images, examples, and protocol tests are owned by this
repository. SeedEmu Docker retains its legacy blockchain implementations; ChainSEED operates independently of them.
EthExplorer is provided by `chainseed.visualization.EthExplorer`, a SeedEmu
`ContainerBundle`. Register it with `docker.addContainerBundle(explorer)`;
SeedEmu Docker compiles the bundle's containers, files and networks. Image
recipes remain in `docker_images/ethexplorer`. `ChainSeedDocker` currently
handles blockchain image mappings and Monero custom-image selection.

The optional [Lookingglass viewer](docs/user_manual/blockchain/lookingglass.md) can be
created with `ethereum.createLookingglassServer()` and bound like a Faucet
Server. It displays all Ethereum chains and publishes host port 8765 by default.
Its runtime and web assets are packaged with ChainSeed.

Generated Compose output, client databases, raw benchmark samples, datasets,
Python caches, and Node package caches are excluded from Git.

## Ordinary installation

The Python distribution and import name are both `chainseed`; the repository
remains `chain-seed`. Python 3.10 is currently supported. The legacy Web3 5
stack must be upgraded before Python 3.11 and newer can be supported.
Use the SeedEmu `development` branch (currently packaged as `0.0.7`).
ChainSEED checks for `SystemProfile`, image catalog hooks and `Docker.addContainerBundle` at import time;
a version number alone cannot establish compatibility. ChainSEED has not been published to PyPI.

Install SeedEmu from its `development` checkout in editable mode, then install ChainSEED normally:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -e ../seed-emulator
python -m pip install .
```

Install SeedEmu from the `development` checkout first, then install ChainSEED.
ChainSEED declares SeedEmu as a dependency, but an older PyPI build with the same
version may lack the required hooks. SeedEmu is maintained independently and
still retains its legacy blockchain implementation.
Its ordinary wheel currently omits legacy blockchain templates and fails during
import. Keep the SeedEmu checkout for the editable installation above until
upstream packaging is fixed.
Docker, client images, and Node tooling are separate runtime prerequisites.
E01 PoS block production and signed ETH transfer validation passed on Docker 29.9.0; other examples still need runtime validation.

## Install for coordinated development

The recommended layout keeps both repositories as siblings under one workspace
directory:

```text
seed-workspace/
├── seed-emulator/
└── chain-seed/
```

The repositories do not technically depend on this location, but the sibling
layout makes cross-repository development and example reuse predictable. Never
clone ChainSeed inside the SeedEmu repository.

```bash
mkdir seed-workspace
cd seed-workspace

git clone --branch development https://github.com/seed-labs/seed-emulator.git
git clone https://github.com/seed-labs/chain-seed.git

python3 -m venv .venv
source .venv/bin/activate

python -m pip install -e ./seed-emulator
python -m pip install -e "./chain-seed[dev]"
```

Run a local compile-only check or the complete Docker lifecycle with the same
entry point used by CI:

```bash
chainseed-test compile chain-seed/examples/ethereum/E01_ethereum_pos/example.yaml
chainseed-test all chain-seed/examples/ethereum/E01_ethereum_pos/example.yaml
```

Shared network definitions live in `examples/ethereum/E00_ethereum_poa/mini_internet.py`,
use public SeedEmu APIs, and support mini/full/hybrid layouts and network `.bin` export. ChainSeed examples no longer depend on the
SeedEmu checkout's top-level `examples` directory. Example scripts remain in this
repository; keep the complete `examples/` directory when copying them.

See [case studies](case_study/README.md) for routing attacks, topology discovery and peer configuration.

Use explicit chain imports:

```python
from seedemu import Binding, Emulator, Filter
from chainseed import ChainSeedDocker
from chainseed.services.ethereum import ConsensusMechanism, EthereumService
from chainseed.services.monero import MoneroService
from chainseed.services.solana import SolanaService
```

## Version compatibility and initial 1.0.0 release

ChainSeed releases independently from SeedEmu. A ChainSeed release may adapt
to a newer SeedEmu without requiring a new SeedEmu release, while every
ChainSeed release declares the SeedEmu versions it supports.

During coordinated development, both repositories support ordinary or editable
installation and tested together. The current alpha metadata remains in place and
does not claim compatibility with an unreleased SeedEmu API.

The initial `1.0.0` release gate is:

1. Finish the coordinated changes in both repositories.
2. Pass local tests and both repositories' remote CI/CD.
3. Change both projects' release metadata to `1.0.0`.
4. Publish `v1.0.0` from each repository's current remote.
5. Reinstall both projects from those tags and rerun the compatibility suite.
6. Only then open the SeedEmu pull request against its upstream repository.

ChainSeed currently has no separate upstream remote and can be released from
its current remote. The SeedEmu upstream remote must not be pushed to or tagged
as part of this process.

After the coordinated release, ChainSeed should use a bounded requirement such
as `seedemu>=1.0.0,<2.0.0`, provided SeedEmu treats the public extension API as
semantic-versioned. A tested compatibility matrix belongs in each release.

## Layout

```text
chainseed/       Python service layers and protocol-aware testing
docker_images/   Blockchain client and explorer image recipes
tools/           Explorer, wallet, and blockchain support tools
examples/        Examples grouped by chain: chainlink, ethereum, monero and solana
case_study/      Routing attacks, topology discovery and peer configuration
experiments/     Archived prototypes and examples
tests/           Package, compiler and runner checks
docs/            Architecture, integration and user manuals
```

The target architecture and remaining SeedEmu API work are documented in
[docs/design](docs/design/README.md).

Docker network configuration is inherited from SeedEmu `development`.
ChainSEED does not override network compilation.
