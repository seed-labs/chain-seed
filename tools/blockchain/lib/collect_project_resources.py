#!/usr/bin/env python3
"""Reuse the E12 cgroup scanner without per-container Docker exec."""
import sys
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from tools.blockchain.lib import collect_node_memory as collector

original = collector.classify_container


def classify(name, labels, cmdline=''):
    text = ' '.join([name, cmdline, *map(str, labels.values())])
    if 'Solana-Bootstrap-' in text:
        return 'solana_bootstrap'
    if 'Solana-Validator-' in text:
        return 'solana_validator'
    for role in ('miner', 'seed', 'full'):
        if f'Monero-{role}-' in text:
            return 'monero_' + role
    return original(name, labels, cmdline)


def main(argv=None):
    args = collector.parse_args(argv)
    if args.scope != 'compose' or args.backend not in ('cgroup-scan', 'cgroup-scan-enriched'):
        raise ValueError('Collection requires Compose-scoped cgroup sampling')
    names = sorted(collector.load_compose_container_names(args.compose_file))
    if not names:
        raise ValueError('Compose has no named containers')
    original_command = collector.run_cmd
    try:
        collector.run_cmd = lambda command: subprocess.check_output(command, text=True, timeout=60)
        metadata = collector.inspect_containers(names)
    finally:
        collector.run_cmd = original_command
    if {r.name for r in metadata.values()} != set(names):
        raise RuntimeError('Incomplete project identity snapshot')
    if any(r.pid <= 0 for r in metadata.values()):
        raise RuntimeError('Project contains stopped containers before resource sampling')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    unique = {r.container_id:r for r in metadata.values()}
    (args.output_dir/'container-identity.json').write_text(json.dumps([
        dict(id=r.container_id, name=r.name, pid=r.pid, labels=r.labels,
             cgroup_path=r.cgroup_path) for r in unique.values()], indent=2))
    # Resolve only this project's known names once. Every sample reads live
    # cgroups, including current PIDs, without querying Docker or spawning nsenter.
    saved = collector.docker_ps_ids, collector.inspect_containers, collector.classify_container
    try:
        collector.docker_ps_ids = lambda: names
        collector.inspect_containers = lambda identities: metadata
        collector.classify_container = classify
        effective_argv = list(sys.argv[1:] if argv is None else argv)
        effective_argv.extend(['--backend', 'cgroup-scan-enriched'])
        return collector.main(effective_argv)
    finally:
        collector.docker_ps_ids, collector.inspect_containers, collector.classify_container = saved


if __name__ == '__main__':
    raise SystemExit(main())
