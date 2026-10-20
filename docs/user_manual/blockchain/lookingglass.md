# Ethereum Lookingglass

See [E05](../../../examples/ethereum/E05_lookingglass/) for a complete deployment and runtime tests.

Create one global viewer in the existing `EthereumService` and bind it to a host:

```python
from seedemu.core import Action, Binding, Filter

lookingglass = ethereum.createLookingglassServer()
as150.createHost("lookingglass").joinNetwork("net0")
emu.addBinding(Binding(
    "lookingglass", action=Action.FIRST,
    filter=Filter(asn=150, nodeName="^lookingglass$"),
))
```

Render, compile, build and start the deployment as usual. Open
http://127.0.0.1:8765; the Server publishes the host port automatically.
It includes all Ethereum chains, with AS and chain filters in the page.
It reaches clients through the emulated network's routes.

Read-only client queries are enabled by default at 10-second intervals, with
eight peer-query workers. Target Geth HTTP APIs must be explicitly enabled with
`enableGethHttp()`. Beacon Metrics follow each Server's `enableMetrics()` setting.
Disabled APIs remain disabled, and failed queries do not stop the viewer.
Configured dependencies and static peers are separate from observed P2P links.

Optional settings, applied before `emu.render()`:

```python
lookingglass.setPort(8765)
lookingglass.setProbePolicy(
    enabled=True, peer_interval=10, metrics_interval=10, workers=8,
)
lookingglass.setObservationDirectory("results/run-1")
```

`setPort()` sets both the listener and published host port. The optional
observation directory is created during rendering and mounted read-only;
resource and transaction collectors run separately. Missing observations remain
unavailable. Legacy collector names are associated using AS/host labels from
the collector's optional `observed-compose.yml`; ambiguous records are omitted.
Queries add load, so keep the same settings across compared measurements.

`chainseed/ethereum/LookingglassServer/` contains the deployment class
(`LookingglassServer.py`), HTTP application (`app.py`), data readers (`sources.py`)
and web assets (`static/`). Files are loaded through Python package resources;
deployment does not depend on the source checkout's filesystem location.
