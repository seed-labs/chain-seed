# Add a blockchain example

Create a directory under `examples/<protocol>/<prefix><number>_<name>/`. Keep network construction and
blockchain configuration in separate Python files when the network is reusable.
Use SeedEmu's public network APIs and import blockchain services from `chainseed`.

```text
examples/<protocol>/<prefix><number>_<name>/
  mini_internet.py
  <protocol>_example.py
  README.md
```

The configuration script renders the emulator and compiles it with
`ChainSeedDocker`. Its generated `output/` should be ready for Docker Compose.
For large deployments, add separate batching scripts for startup and shutdown.
The three large-scale examples live under
`examples/ethereum/E10_large_scale/`, `examples/monero/M01_large_scale/`
and `examples/solana/S01_large_scale/`.

Put reusable services and configuration APIs in `chainseed/services/<protocol>/`.
Observation, workload and summary scripts belong in `tools/<protocol>/`;
keep their steps independent from compilation and container startup.

The README should give the commands in order, including required images,
startup, observation and shutdown. Use a fresh results directory for each run.
Generated deployments, client data and measurement output are not committed.

For runtime validation through `chainseed-test`, add an `example.yaml` and
`test_runtime.py` beside the example. See the Ethereum E01 example for the format.
