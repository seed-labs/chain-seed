# Monero Large-Scale Tools

| Script | Usage |
| --- | --- |
| `prepare_wallets.py` | Distribute mining rewards to sender wallets and wait for unlocked outputs. |
| `send_transactions.py` | Send native transfers at the requested rate, then wait for confirmation on two nodes. |
| `miners.py` | Initialize a miner set, optionally ramp its size, or rotate miners periodically. |
| `check_health.py` | Check all nodes, their common chain and actual single-thread mining states. |
| `measure.py` | Collect project-scoped container resources and chain health. |
| `summarize.py` | Summarize the transfer window, including resources, chain progress, mining and inclusion. |

See the [M01 manual](../../../examples/monero/M01_large_scale/README.md) for the
commands in order. Each script has `--help`.

Use one run directory per experiment and keep `miner-state.json` there. Funding
events are saved in `funding/`; formal transfers and two-node receipt evidence
are saved in `transactions/`. Sending journals the prepared transaction before
broadcast and retries the same transaction when the relay response is uncertain.
It does not create replacement transfers for uncertain submissions.

`measure.py` records all containers in the compiled deployment, including network
infrastructure. Collection continues until Ctrl-C unless `--duration` is supplied.
Keep it and miner rotation running until transaction sending and receipt draining
finish. The summary aligns observations to `transactions/sampling.json`, excluding
funding, miner warmup and receipt-drain time from the formal resource window.

Miner transitions start replacements before stopping the previous miners, so the
actual count can briefly exceed the target. The controller checks all candidates
before committing its new state. Resource intervals overlapping transitions remain
in project totals and are reported separately from stable active/inactive groups.

Summary checks require at least 95% resource and health coverage, 99% healthy
observations, chain advancement, at least 95% of the offered transfer count, and
two-node inclusion for every prepared formal transfer. The initial CPU sample is
excluded. Missing records and interrupted sending produce a failed result; raw
records are retained. Memory is container cgroup usage and CPU is logical cores.

These tools operate on the example's private testnet and preserve normal funding
and output-unlock waits. They do not model modern-mainnet RingCT workload costs.
