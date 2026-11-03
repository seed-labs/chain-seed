# CS2: Blockchain Amplification

Run the [Blockchain Amplification Attack](https://doi.org/10.1145/3711697)
authors' modified-Geth tests and configure custom clients in an emulated network.

## Author artifact

Go 1.22 and the external author source are required. From the repository root:

```bash
git clone https://github.com/taro-tsuchiya/BlockchainAmplification /tmp/BlockchainAmplification
git -C /tmp/BlockchainAmplification checkout 51486b72903896f95034c903a3ad3ca4bdde5ed3
python case_study/CS2_blockchain_amplification/run_author_artifact.py --artifact-dir /tmp/BlockchainAmplification --tests basis,amplification --assert-success
```

The tests examine honest and attack transactions in the txpool and constructed
blocks as attack-account counts change. CSV and JSON output is saved under this
example's `results/`. Use `--go-bin` to select Go, `--tests all` for baseline and
MemPurge comparisons, or `--build-modified-geth` to build the modified client.
The report records the source commit and Go version.

## Custom-client deployment

`build.py` is a separate PoS network example. Provide a modified Geth compatible
with the configured genesis and PoS Engine API:

```bash
python case_study/CS2_blockchain_amplification/build.py --nodes 8 --modified-count 1 --custom-geth /path/to/compatible/geth --require-custom-geth --compile
docker compose -f case_study/CS2_blockchain_amplification/output/docker-compose.yml up -d --build
docker compose -f case_study/CS2_blockchain_amplification/output/docker-compose.yml down --remove-orphans
```

The custom binary is configured through each selected Server's `setCustomGeth()`.
`--degree` and `--seed` control a deterministic peer graph, installed through
`setStaticPeers()` with discovery disabled. Its declarations are recorded in
`results/scenario_manifest.json`; live connections still require runtime checks.
Without `--custom-geth`, every node runs stock Geth. This deployment does not
send the attack workload: the author artifact above exercises that behavior.
A binary that passes the author's tests still needs protocol compatibility checks
before use in this PoS deployment.
