# CS1: KnockBlock

Announce a more-specific BGP route for a victim Beacon near its
validator's proposer slot, then withdraw the route and observe recovery. Based
on [Routing Attacks in Ethereum PoS](https://arxiv.org/abs/2505.07713).

Run from the repository root:

```bash
python case_study/CS1_knockblock/build.py --beacon-nodes 2 --validators-per-beacon 2 --compile
docker compose -f case_study/CS1_knockblock/output/docker-compose.yml up -d --build
python case_study/CS1_knockblock/run_attack.py --beacon-nodes 2 --validators-per-beacon 2 --duration 48 --recovery-wait 24 --ready-timeout 900
docker compose -f case_study/CS1_knockblock/output/docker-compose.yml down --remove-orphans
```

`build.py` creates the routed network, Geth, Beacon and validator clients, and an
ExaBGP speaker in AS230. `run_attack.py` waits for chain progress, selects a
future proposer served by Beacon 0, announces `10.203.0.0/25`, records routes,
reachability and slot blocks, and waits for withdrawal and recovery. Use matching
node counts for the build and attack steps. Defaults are eight Beacons and four
validator clients per Beacon.

Results and container logs are saved under this example's `results/`. Exit 0
requires an observed hijack, connectivity failure and recovery, and a confirmed
missing block for the selected victim slot. Failed block queries are recorded as
unknown. The script leaves the deployment running; shut it down separately.
This case measures routing and consensus behavior, not MEV or proposer revenue.

Use `--output` and `--manifest` on the builder and `--output-dir` on the attack
script for custom deployment paths. Other options are listed by `--help`.
