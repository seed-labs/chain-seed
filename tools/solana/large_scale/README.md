# Solana Large-Scale Tools

| Script | Usage |
| --- | --- |
| `check_health.py` | Check scoped Agave processes, bootstrap finalized progress and voting stake, then wait for stability. |
| `measure.py` | Collect project-scoped resources and bootstrap consensus observations. |
| `send_transactions.py` | Send native SOL transfers using the genesis faucet account and wait for finalized receipts. |
| `summarize.py` | Summarize resources, finalized progress, process counts and optional transfer evidence. |
| `host_tuning.sh` | Explicitly show, apply or restore runtime host limits. |

See the [S01 manual](../../../examples/solana/S01_large_scale/README.md) for the
commands in order. Each Python script has `--help`.

Only the final genesis-preseeded voting configuration is supported. All identities,
vote accounts and stakes are included in genesis. Bootstrap first publishes a
complete initialized ledger; bootstrap and validator 1 pass a two-node start
barrier, and other nodes join in batches. There is no runtime account-creation or
observer mode. Keys are deterministic emulator keys.

The retained stake distribution is 100 SOL for bootstrap, 1,000 SOL for validator 1,
and 0.05 SOL for each remaining validator. A process count does not establish that
all nodes are voting. Health records current/delinquent vote accounts separately
and requires more than two-thirds of stake to be current, together with advancing
finalized slots. Process checks read only the configured containers' cgroups.

Compilation settings live at the top of
[`solana_large_scale.py`](../../../examples/solana/S01_large_scale/solana_large_scale.py).
`_deployment.py` contains the retained low-memory Agave options. Genesis keeps the
original raw `--target-tick-duration 500000` and `--ticks-per-slot 10` arguments;
the old wrapper's misleading `_MS` variable name is not used. The original
experiment described approximately five-second slots; observed progress remains
part of dynamic validation.

Measurement defaults to five hours with 60-second samples. `--duration 0` collects
until Ctrl-C. `summary/` contains JSON/CSV results, resource series and SVG plots.
Totals include network infrastructure. The initial CPU sample is excluded; missing
containers, less than 95% resource/health coverage, less than 99% healthy rounds,
or stalled finalization fail the summary. The resource window is the measurement
window. Optional transfers record their own start, duration, submitted signatures
and finalized statuses; their summary is shown separately. The bootstrap's total
transaction counter includes vote traffic and is not the generated transfer TPS.

Host tuning is a separate manual step and is not run by compilation or startup.
Actual image IDs, source hashes and raw records are retained by observation tools.
