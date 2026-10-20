# Ethereum PoS with EthExplorer

This example creates a PoS network and an EthExplorer ContainerBundle. Explorer
uses the Geth and Lighthouse APIs to display slots, epochs, validators and
execution transactions. Install SeedEmu and ChainSeed in the same environment.

Run from the repository root:

```bash
chainseed-test all examples/ethereum/E02_eth_explorer/example.yaml
```

Or run the steps separately:

```bash
chainseed-test compile examples/ethereum/E02_eth_explorer/example.yaml
chainseed-test build examples/ethereum/E02_eth_explorer/example.yaml
chainseed-test up examples/ethereum/E02_eth_explorer/example.yaml
chainseed-test probe examples/ethereum/E02_eth_explorer/example.yaml
chainseed-test test examples/ethereum/E02_eth_explorer/example.yaml
chainseed-test down examples/ethereum/E02_eth_explorer/example.yaml
```

Open http://127.0.0.1:5000. The Internet Map is available at
http://127.0.0.1:8080/map.html. Indexing can take time after the chain starts.

## Configure the bundle

Explorer is provided by `chainseed.visualization.EthExplorer` and registered
through SeedEmu's public Docker interface:

```python
from chainseed import ChainSeedDocker
from chainseed.visualization import EthExplorer

emu.render()
docker = ChainSeedDocker(internetMapEnabled=True)
docker.addContainerBundle(EthExplorer(emu, chain_name="pos", port=5000))
emu.compile(docker, "output")
```

`ChainSeedDocker` currently supplies the blockchain image mappings. The Explorer
bundle itself uses the same `addContainerBundle()` interface on SeedEmu `Docker`.
Its seven containers are ClickHouse, PostgreSQL, Redis, two Bigtable instances,
and the Explorer backend and web application. Image recipes are in
[`docker_images/ethexplorer`](../../../docker_images/ethexplorer/).

Use logical node names to choose the observation clients:

```bash
python examples/ethereum/E02_eth_explorer/ethereum_pos.py   --explorer-geth gethnode1 --explorer-beacon beaconnode1
```

The equivalent Python configuration is:

```python
explorer = EthExplorer(
    emu, chain_name="pos", port=5000,
    geth_vnode="gethnode1", beacon_vnode="beaconnode1",
)
docker.addContainerBundle(explorer)
```

The selected Geth must enable its HTTP API. The selected Beacon must retain
historical-state reconstruction. Without selectors, Explorer chooses eligible
clients from the requested chain. Its emulated route uses the selected Geth's
network; the configured Geth RPC port is passed to both applications.

Use `port=5050` to change the published web port. `backend_image` and `web_image`
can select compatible custom images. The bundle must be configured against a
rendered emulator; create it before or after rendering and compile after render.

The default network has three Geth nodes, three Beacons, nine genesis validator
clients, BeaconSetup, Faucet and Utility services. Use `--help` for scale and
output options. Generated files are saved in this example's `output/` directory.
