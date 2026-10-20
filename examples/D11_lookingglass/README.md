# D11 Ethereum Lookingglass

This example adds a global Lookingglass Server to the D01 PoS network:
three Geth clients, three Beacons, nine Validator clients, Faucet and Utility.
Geth HTTP RPC and Beacon Metrics are enabled. Lookingglass uses its defaults.

Run from the repository root:

```bash
uv pip install --reinstall-package chainseed .
chainseed-test all examples/D11_lookingglass/example.yaml --artifact-dir /tmp/chainseed-d11
```

To run each step separately and keep the deployment available for inspection:

```bash
chainseed-test compile examples/D11_lookingglass/example.yaml
chainseed-test build examples/D11_lookingglass/example.yaml
chainseed-test up examples/D11_lookingglass/example.yaml
chainseed-test probe examples/D11_lookingglass/example.yaml
chainseed-test test examples/D11_lookingglass/example.yaml --artifact-dir /tmp/chainseed-d11
# Stop when finished:
chainseed-test down examples/D11_lookingglass/example.yaml
```

Open http://127.0.0.1:8765. The Internet Map is at
http://127.0.0.1:8080/map.html. `all` stops the deployment when testing finishes;
use the separate steps to browse it. Stop other examples using ports 8080/8765
or overlapping emulated networks before starting D11.

The runtime test checks host access and web assets, the complete client inventory
and dependencies, fresh peer/txpool/Metrics observations, actual cross-AS Geth
and Beacon links, advancing Beacon heads, replay events and rejection of HTTP
writes. It saves JSON snapshots and a result summary under the artifact directory.
Memory/CPU and transaction history need separate collectors and are not required
by this example. Metrics checks verify successful scrapes, not a specific queue
value or the presence of optional Lighthouse histogram series.

In the browser, switch between Service map, Geth peers and Beacon peers; select
an AS and a node, inspect dependencies and live samples, and try pause/resume,
replay and snapshot export. Node queries can take several polling rounds after
the chain starts. Failed query details appear in the test report and node panel.
If the page loads but cross-AS queries fail, check routing and SeedEmu's Docker
bridge-forwarding fix.

To compile directly, use `python examples/D11_lookingglass/ethereum_pos.py`.
Add `--platform arm` for ARM64, or `--override` to replace an existing output.
See the [Lookingglass API manual](../../docs/user_manual/blockchain/lookingglass.md).
CI includes D11 compilation; run the workflow manually with `selected-example=D11`
and `run-full-lifecycle=true` to execute the Docker tests.
