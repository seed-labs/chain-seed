#!/usr/bin/env python3
"""Check an existing chain and record its environment; never starts/stops deployment."""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import yaml
from _deployment import read_deployment
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.blockchain.lib.processes import Processes, interrupted

LIB = Path(__file__).with_name('_lib')

RESOURCE_COLLECTOR = Path(__file__).resolve().parents[2] / 'blockchain/lib/collect_node_memory.py'


def record_environment(compose, run_dir):
    payload = yaml.safe_load(compose.read_text())
    images = sorted({s['image'] for s in payload['services'].values()})
    ethereum_image = next(s['image'] for s in payload['services'].values()
        if s.get('labels', {}).get('org.seedsecuritylabs.seedemu.meta.displayname', '').startswith('Ethereum-POS-Geth-'))
    report = dict(python=sys.version, platform=list(os.uname()), cpu_count=os.cpu_count(),
        meminfo=Path('/proc/meminfo').read_text(),
        packages={name: metadata.version(name) for name in ('seedemu', 'chainseed', 'web3')},
        compose_sha256=hashlib.sha256(compose.read_bytes()).hexdigest(),
        images=json.loads(subprocess.check_output(['docker', 'image', 'inspect', *images], text=True, timeout=60)),
        docker=subprocess.check_output(['docker', 'version'], text=True, timeout=30),
        compose=subprocess.check_output(['docker', 'compose', 'version'], text=True, timeout=30))
    report['client_versions'] = {}
    # Probe the actual local image, rather than inferring versions from Dockerfiles.
    for binary in ('lighthouse', 'geth'):
        report['client_versions'][binary] = subprocess.check_output(['docker', 'run', '--rm',
            '--pull=never', '--network=none', '--entrypoint', binary, ethereum_image,
            '--version' if binary == 'lighthouse' else 'version'], text=True, timeout=60)
    sources = [p for p in Path(__file__).parent.rglob('*') if p.suffix in ('.py', '.json') and p.is_file()]
    sources.append(Path(__file__).resolve().parents[2] / 'blockchain/lib/runtime_mounts.py')
    sources.append(RESOURCE_COLLECTOR)
    sources.append(Path(__file__).resolve().parents[2] / 'blockchain/lib/processes.py')
    transaction_tools = Path(__file__).parent.parent / 'transaction_generator'
    sources.extend(p for p in transaction_tools.rglob('*') if p.suffix in ('.py', '.json') and p.is_file()
                   and 'results' not in p.relative_to(transaction_tools).parts)
    example = Path(__file__).resolve().parents[3] / 'examples/ethereum/E10_large_scale'
    sources.extend(p for p in example.glob('*') if p.suffix in ('.py', '.sh') and p.is_file())
    report['source_sha256'] = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    path = run_dir / 'provenance.json'
    with path.open('x') as handle:
        json.dump(report, handle, indent=2)


def check(compose, run_dir, timeout=7200):
    cfg = read_deployment(compose)
    run_dir.mkdir(parents=True, exist_ok=True)
    record_environment(compose, run_dir)
    commands = {
        'readiness-gate': ['health.py', '--compose', compose, '--data-dir', run_dir,
            '--gate', '--timeout', timeout, '--expected-validators', cfg['active_validators']],
        'readiness-resources': [RESOURCE_COLLECTOR, '--compose-file', compose,
            '--output-dir', run_dir / 'readiness-resources', '--backend', 'cgroup-scan-enriched',
            '--once', '--expect-beacons', cfg['beacons'], '--expect-geth', cfg['geth'],
            '--expect-validators', cfg['validator_clients']],
    }
    group = Processes(run_dir / 'logs')
    try:
        for name, args in commands.items():
            print(f'{name}: see {run_dir / "logs" / (name + ".log")}', flush=True)
            child = group.start(name, [sys.executable, LIB / args[0], *args[1:]])
            if child.wait():
                raise RuntimeError(f'{name} failed; inspect its log')
    finally:
        group.stop()
    (run_dir / 'health-result.json').write_text(json.dumps(dict(status='passed',
        expected_validators=cfg['active_validators'], beacons=cfg['beacons'], geth=cfg['geth']), indent=2)+'\n')
    print('Chain readiness and node process counts passed')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compose', type=Path, required=True)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--timeout', type=int, default=7200)
    a = p.parse_args()
    if a.timeout < 1:
        p.error('timeout must be positive')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    check(a.compose.resolve(), a.run_dir.resolve(), a.timeout)
