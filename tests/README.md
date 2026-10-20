# Test Ownership

ChainSeed uses the same manifest-driven lifecycle as SeedEmu. Canonical tests
live beside their examples as `example.yaml` and `test_runtime.py`; the
`chainseed-test` command runs the compile, build, start, readiness, probe,
functional-test, and cleanup stages locally and in GitHub Actions.

For example:

```bash
chainseed-test compile examples/D01_ethereum_pos/example.yaml
chainseed-test all examples/D01_ethereum_pos/example.yaml
```

`test_public_imports.py` is a lightweight package/API check. Runtime coverage
belongs in example manifests and runtime programs, shared by local runs and
GitHub Actions.

ChainSeed CI checks out SeedEmu `Docker`, installs it in editable mode,
and verifies the installed ChainSEED wheel and copied examples. Upstream SeedEmu
currently omits legacy blockchain template assets from its wheel; using its
source assets avoids the missing upstream wheel resources.
`test_package_integration.py` compiles Ethereum PoA/PoW/PoS, Explorer, Monero,
Solana and Chainlink configurations, including a custom Geth binary.
SeedEmu CI does not install or import ChainSeed.

`test_ethereum_runtime_config.py` checks independent Server tuning through generated
scripts, compiled Docker files and process arguments, plus genesis/VC key ranges.

`test_ethereum_static_peers.py` checks logical Geth peers, client identity files,
cross-AS enodes, dump reuse, legacy/PoS commands and invalid peer declarations.

`test_example_network.py` checks mini/hybrid networks and `.bin` reuse.
`test_lookingglass_server.py` checks the global inventory, defaults, native Docker
port publication, runtime files, optional observations and D61 mount compatibility.
`test_d11_lookingglass.py` checks D11 defaults and verifies that its runtime test
rejects stale, missing and configured-only observations. Run the Docker checks
manually with `chainseed-test all examples/D11_lookingglass/example.yaml`.
`check_repository_boundaries.py --seedemu ../seed-emulator` checks source
ownership, removed API references, and Python syntax across both repositories.
SeedEmu retains its legacy blockchain sources; boundary checks enforce ChainSEED
imports independently of those implementations. CI defaults to compilation; the Docker lifecycle requires explicit opt-in.

Build output is streamed to `logs/build.log` when `--artifact-dir` is provided.
Use `tail -f` to inspect progress from another terminal. Command timeouts return
exit code 124 and retain partial output; `all` still attempts cleanup.
`test_runner_commands.py` covers timeout diagnostics and lifecycle cleanup.

Before Compose cleanup, the ChainSEED runner saves `logs/runtime-ps.log` and
`logs/runtime-logs.log` (the last 200 lines per service). For interactive
diagnosis, run `up` and `probe` separately; a probe failure then leaves the
containers running until an explicit `down`.
