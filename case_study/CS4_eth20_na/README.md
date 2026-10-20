# CS4: Beacon peer configuration

Compare Lighthouse target peer counts of 8, 7 and 5,
motivated by [Eth2.0-NA](https://doi.org/10.1109/INFOCOM59046.2026.11571391).
The network contains ten Beacon nodes, one validator client per Beacon and one
Geth execution node. Keep the network and measurement settings fixed across runs.

Run the following steps from the repository root:

```bash
python case_study/CS4_eth20_na/build.py --target-peers 8 --compile
docker compose -f case_study/CS4_eth20_na/output_tp8/docker-compose.yml up -d --build
python case_study/CS4_eth20_na/measure.py --target-peers 8 --measure-seconds 180 --sample-interval 1 --ready-timeout 900
docker compose -f case_study/CS4_eth20_na/output_tp8/docker-compose.yml down --remove-orphans
```

Repeat these steps with `7` and `5` in both `--target-peers` and `output_tpN`.
Generated deployments are isolated by peer count. Measurements are written to
`results/eth20_na_tpN.json`; a new run with the same target overwrites that report.

`build.py` configures each Beacon using `setBeaconPeerCounts()`, `enableMetrics()`
and `setSubscribeAllSubnets()`. All-subnet subscription is enabled by default;
use `--no-subscribe-all-subnets` to disable it. `--no-metrics` disables metric
scraping endpoints while leaving the Beacon APIs available. Node counts and
output/manifest paths can also be changed; see `--help`.

`measure.py` waits for ready, advancing Beacons, samples head observations and
records peer counts, metrics and Beacon interface RX/TX byte deltas. The traffic
metric is the sum of RX and TX deltas across Beacon containers; it includes
traffic other than GossipSub. Head-observation spread is sampled at one-second
resolution, rather than a direct measurement of message propagation latency.
Use `--manifest` to measure a deployment compiled with a custom manifest path.
The measurement script leaves the deployment running.

This experiment varies Lighthouse target peer count on a fixed network and
measures traffic and sampled head-observation spread. Target peer count differs
from GossipSub mesh degree D.
