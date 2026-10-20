# CS3: TopoShot

Evaluate [TopoShot](https://doi.org/10.1145/3487552.3487814)
against known peer connections. `local/` contains four-role local validation;
`topology/` measures controlled overlays of different sizes.

Both use PoA and the repository's AMD64 Geth 1.10.18 binary at
`examples/ethereum/E09_blockchain/resources/custom_geth`, configured through
`setCustomGeth()`. Run on Linux AMD64 with Docker Compose. Commands below run
from the repository root, with one deployment active at a time.

## Four-role local validation

```bash
python case_study/CS3_toposhot/local/build.py --compile
docker compose -f case_study/CS3_toposhot/local/output/docker-compose.yml up -d --build
python case_study/CS3_toposhot/local/measure.py --iterations 100 --assert-success
docker compose -f case_study/CS3_toposhot/local/output/docker-compose.yml down --remove-orphans
```

The roles are a synchronization miner and three measured nodes. The measurement
script configures seven reference overlays and probes links with replacement
transactions. `--iterations` repeats each case; start with `--iterations 1`
for a short validation.

## 4/6/8/12-node subgroups

```bash
python case_study/CS3_toposhot/topology/build.py --nodes 12 --accounts 2000 --compile
docker compose -f case_study/CS3_toposhot/topology/output/docker-compose.yml up -d --build
python case_study/CS3_toposhot/topology/measure.py --nodes 12 --group-sizes 4,6,8,12 --account-start 1000 --assert-success
docker compose -f case_study/CS3_toposhot/topology/output/docker-compose.yml down --remove-orphans
```

The default eight families are empty, path, ring, star, balanced bipartite,
lollipop, random degree-three and complete. The measurement script resets live
peer connections, establishes and checks each reference graph, then records
inferred links, precision, recall and transaction evidence.

## Larger graphs

For example, run six 32-node families with:

```bash
python case_study/CS3_toposhot/topology/build.py --nodes 32 --accounts 6000 --compile
# Start the generated deployment before measuring.
python case_study/CS3_toposhot/topology/measure.py --nodes 32 --group-sizes 32 --topologies path,ring,star,balanced_bipartite,lollipop,random_deg3 --account-start 1000 --assert-success
```

For a 100-node path:

```bash
python case_study/CS3_toposhot/topology/build.py --nodes 100 --accounts 7000 --compile
# Start the generated deployment before measuring.
python case_study/CS3_toposhot/topology/measure.py --nodes 100 --group-sizes 100 --topologies path --account-start 1000
```

Stop the previous deployment before rebuilding. Each deployment includes an
additional miner. The compiler checks available host memory; size the machine
accordingly. Extra measurement batches need unused funded account indices or a
fresh deployment.

Manifests and measurement reports are saved under each subexample's `results/`.
`--assert-success` requires perfect precision and recall; omit it for experiments
studying missed links, such as the 100-node path. Measurements compare inferred
links against the configured reference graphs.
