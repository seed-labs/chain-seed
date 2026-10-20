# E02 EthExplorer Example

This example runs an Ethereum PoS private network and attaches the ChainSeed
EthExplorer stack. The explorer integration is owned by
`chainseed.services.ethereum.EthExplorer`; its image recipes and runtime assets are
owned by [`docker_images/ethexplorer`](../../../docker_images/ethexplorer).

The explorer images are adapted from
[eth2-beaconchain-explorer](https://github.com/gobitfly/eth2-beaconchain-explorer)
and [beaconchain](https://github.com/gobitfly/beaconchain).

## What the example creates

The example reuses E01 to create:

- three Geth execution nodes;
- three Lighthouse beacon nodes;
- nine genesis validator clients;
- one beacon setup node;
- Faucet and utility services;
- the Internet Map;
- the EthExplorer web, backend, and data services.

EthExplorer selects one rendered `PoSGethServer` and one rendered
`PoSBeaconServer` from the requested Ethereum chain. You can select them by
virtual node name. Automatic selection chooses the first eligible rendered node
in registry/ID order: Geth must have HTTP RPC enabled and Beacon must retain
historical-state reconstruction. Display names are not used for selection.

## Compile and run

Run from the ChainSeed repository root:

```bash
chainseed-test compile examples/ethereum/E02_eth_explorer/example.yaml
chainseed-test all examples/ethereum/E02_eth_explorer/example.yaml
```

To compile the example directly:

```bash
python examples/ethereum/E02_eth_explorer/ethereum_pos.py \
  --platform amd \
  --output examples/ethereum/E02_eth_explorer/output
```

Then start or stop the generated deployment:

```bash
cd examples/ethereum/E02_eth_explorer/output
docker compose up -d --build
docker compose down --remove-orphans
```

AMD64 is the default. Use `--platform arm` for ARM64.

## Python integration

E01 renders the emulator first, then gives the rendered topology and Docker
compiler to the ChainSeed component:

```python
emu.render()

docker = ChainSeedDocker(internetMapEnabled=True, platform=platform)
docker.enableEthExplorer(
    chain_name="pos", port=5000,
    geth_vnode="gethnode1",
    beacon_vnode="beaconnode1",
)

emu.compile(docker, output, override=True)
```

Omit either selector to choose that role automatically. Explicit selectors must
name the correct Server role in the requested chain. Unknown names, wrong roles,
other chains, disabled Geth HTTP RPC, or disabled Beacon historical reconstruction
produce errors during compilation. Set Server options before `emu.render()`;
the component does not change them.

For a dedicated observer in your own topology:

```python
observer.setReconstructHistoricStates(True)
# Other Beacon instances can call setReconstructHistoricStates(False).
# Use observer's virtual node name as beacon_vnode when enabling EthExplorer.
```

E01 and E02 also accept selectors on the command line:

```bash
python examples/ethereum/E02_eth_explorer/ethereum_pos.py \
  --explorer-geth gethnode1 --explorer-beacon beaconnode1
```

In E01, the `--eth-explorer` and `--no-eth-explorer` command-line options control
this step. The `--ether-view` names are also accepted as aliases.

SeedEmu calls a protected additional-services hook while compiling Compose.
`ChainSeedDocker` overrides the hook, obtains service definitions from
`EthExplorer`, and resolves the selected emulated network names through its
inherited compiler helper. SeedEmu does not know which containers belong to
EthExplorer.

## Services and networking

| Service | Purpose |
| --- | --- |
| `seedemu-ethexplorer-web` | Web UI, search, validator tagging, and frontend updates |
| `seedemu-ethexplorer-backend` | Execution and consensus indexing, statistics, and schema initialization |
| `postgres` / `alloy` | Explorer and indexer relational data |
| `clickhouse` | Analytical chain data |
| `redis` | Cache and session data |
| `littlebigtable` / `rawbigtable` | Local Bigtable-compatible storage |

The data services share the Compose default network. The web and backend
services also join the two emulated networks containing the selected Geth and
Beacon nodes. Their addresses are provided as:

- `EL_HOST` / `EL_PORT`: selected Geth node address and configured HTTP RPC port;
- `CL_HOST` / `CL_PORT`: selected Beacon node address and HTTP API port (currently 8000).

The web UI is published at `http://127.0.0.1:5000`. The Internet Map remains
available at `http://127.0.0.1:8080/map.html`.

## Image layout

```text
docker_images/ethexplorer/
├── docker-compose.yml
├── beaconchain/backend/
│   ├── Dockerfile
│   ├── start.sh
│   └── local_deployment/
└── eth2-beaconchain-explorer/
    ├── Dockerfile
    ├── start.sh
    └── local-deployment/
```

The default image references are declared by
`chainseed.services.ethereum.EthExplorer`:

```text
handsonsecurity/seedemu-ethexplorer-backend:1.0
handsonsecurity/seedemu-ethexplorer-web:1.0
```

They can be overridden through `ChainSeedDocker.enableEthExplorer()`.

## Validation

The manifest-driven test checks:

- the expected Geth, Beacon, and validator topology;
- that Explorer services carry the ChainSeed ownership label;
- container readiness and Explorer HTTP availability;
- consensus slot and epoch indexing;
- a signed execution-layer transaction and its Explorer pages.

## Troubleshooting

If `http://127.0.0.1:5000` is unavailable, inspect service state and logs:

```bash
docker compose ps
docker compose logs -f seedemu-ethexplorer-backend
docker compose logs -f seedemu-ethexplorer-web
```

Initial indexing can take several slots while Geth, Lighthouse, Postgres,
ClickHouse, Redis, and Bigtable-compatible services become ready.

If port 5000 is occupied, change the component configuration and recompile:

```python
docker.enableEthExplorer(chain_name="pos", port=5050)
```
