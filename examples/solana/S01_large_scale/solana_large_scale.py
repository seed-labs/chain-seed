#!/usr/bin/env python3
"""Compile the final genesis-voting, low-memory Solana deployment."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT/'tools/solana/large_scale'))
import mini_internet
from _deployment import prepare_output
from seedemu import Binding, Emulator, Filter
from seedemu.compiler import BASE_IMAGE, DockerImage, Platform
from seedemu.layers import EtcHosts
from chainseed import ChainSeedDocker
from chainseed.solana import SolanaService

# Defaults from the final 200-node experiment. No alternate runtime modes.
SLOTS_PER_EPOCH = 262144
TARGET_TICK_DURATION = 500000  # Raw solana-genesis --target-tick-duration argument.
TICKS_PER_SLOT = 10
GENESIS_CREATION_TIME = '2026-01-01T00:00:00Z'
BOOTSTRAP_STAKE_LAMPORTS = 100000000000
CORE_STAKE_LAMPORTS = 1000000000000
VALIDATOR_STAKE_LAMPORTS = 50000000
BALANCE_LAMPORTS = 500000000000


def compile_network(output, validators=200, stub_as_count=64, image='seedemu-solana', network=None, dry_run=False):
    counts = mini_internet.host_counts(validators, stub_as_count)
    config = dict(validators=validators, stub_as_count=stub_as_count, image=image,
        slots_per_epoch=SLOTS_PER_EPOCH, target_tick_duration=TARGET_TICK_DURATION,
        ticks_per_slot=TICKS_PER_SLOT, genesis_creation_time=GENESIS_CREATION_TIME,
        bootstrap_stake_lamports=BOOTSTRAP_STAKE_LAMPORTS, core_stake_lamports=CORE_STAKE_LAMPORTS,
        validator_stake_lamports=VALIDATOR_STAKE_LAMPORTS, balance_lamports=BALANCE_LAMPORTS,
        genesis_start_barrier_validators=2, nofile=1000000,
        network_sha256=hashlib.sha256(Path(network).read_bytes()).hexdigest() if network else None)
    if dry_run:
        print(json.dumps(config, indent=2))
        return config
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('output exists; choose a new path')
    emu = Emulator().load(str(network)) if network else mini_internet.build_emulator(validators, stub_as_count)
    if {layer.getName() for layer in emu.getLayers()} != {'Base','Routing','Ebgp','Ibgp','Ospf'}:
        raise ValueError('Load a pure unrendered network from mini_internet.py')
    base = emu.getLayer('Base')
    solana = SolanaService()
    chain = solana.createBlockchain('seed-solana-large')
    hosts = []
    for index in range(validators):
        asn, host_name = 150+index%stub_as_count, f'host_{index//stub_as_count:03d}'
        host = base.getAutonomousSystem(asn).getHost(host_name)
        hosts.append(host)
        vnode = 'sol-boot-000' if index == 0 else f'sol-validator-{index:03d}'
        node = chain.createBootstrapValidator(vnode) if index == 0 else chain.createValidator(vnode)
        if index == 0:
            node.setHashesPerTick('sleep').setFaucetLamports(500000000000000000)
        else:
            node.setNodeSol(500)
        role = 'Bootstrap' if index == 0 else 'Validator'
        node.setDisplayName(f'Solana-{role}-{index:03d}')
        node.appendClassName(f'Solana-{role}')
        node.addHostName(f'{vnode}.large-solana.net')
        emu.addBinding(Binding(vnode, filter=Filter(asn=asn, nodeName=f'^{host_name}$')))
    emu.addLayer(solana)
    emu.addLayer(EtcHosts())
    emu.render()
    compiler = ChainSeedDocker(platform=Platform.AMD64, internetMapEnabled=False)
    compiler.addImage(DockerImage(name=image, software=[], subset=BASE_IMAGE))
    records = []
    for index, host in enumerate(hosts):
        compiler.setImageOverride(host, image)
        records.append(dict(index=index, ip=str(host.getInterfaces()[0].getAddress()),
            asn=host.getAsn(), host=host.getName(), role='bootstrap' if index == 0 else 'core' if index == 1 else 'validator',
            identity=None))
    output.parent.mkdir(parents=True, exist_ok=True)
    emu.compile(compiler, str(output), override=False)
    prepare_output(output, config)
    from _keys import _solana_pubkey
    for record in records:
        label = 'bootstrap:identity' if record['index'] == 0 else f'validator:{record["index"]:03d}:identity'
        record['identity'] = _solana_pubkey(label)
    (output/'nodes.json').write_text(json.dumps(records, indent=2)+'\n')
    (output/'deployment.json').write_text(json.dumps(config, indent=2)+'\n')
    print(f'Runnable output: {output} ({validators} voting-configured nodes)')
    return config


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validators', type=int, default=200)
    parser.add_argument('--stub-as-count', type=int, default=64)
    parser.add_argument('--image', default='seedemu-solana')
    parser.add_argument('--network', type=Path)
    parser.add_argument('--output', type=Path, default=SCRIPT_DIR/'output')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    compile_network(**vars(args))
