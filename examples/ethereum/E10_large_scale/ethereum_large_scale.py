#!/usr/bin/env python3
"""Compile the paper 5.1 Ethereum deployment (Beacon:Geth:VC = 1:1:1.5)."""
from __future__ import annotations
import argparse
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import sys
from typing import Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools/ethereum/large_scale"))
import mini_internet
from _deployment import prepare_output
from seedemu.core import Emulator, Binding, Filter, Action
from seedemu.layers import EtcHosts
from seedemu.compiler import Platform
from chainseed import ChainSeedDocker
from chainseed.services.ethereum import (EthereumService, ConsensusMechanism,
    PoSBeaconSetupServer, PoSGethServer, PoSBeaconServer, PoSVcServer)

DOMAIN = ".large-pos.net"
LOCAL_ACCOUNT_BALANCE_ETHER = 10**50
# Experiment defaults; client options are configured on each Server instance.
WORKER_CAP = 2
GETH_CACHE_MIB = 128
GETH_GOMEMLIMIT_MIB = 384
KEYS_PER_CLIENT = 100
GENESIS_DELAY_SECONDS = 1800
BLOCK_GAS_LIMIT = 36_000_000

@dataclass(frozen=True)
class Placement:
    asn: int
    host: str


def _validator_beacon_index(index, validator_count, beacon_count):
    return index * beacon_count // validator_count


def plan_placements(beacons, stub_as_count):
    if beacons < 4 or beacons % 2:
        raise ValueError("beacons must be an even integer >=4 for the 1:1:1.5 ratio")
    if not 1 <= stub_as_count <= mini_internet.MAX_STUB_AS_COUNT:
        raise ValueError("stub_as_count must be in [1, 100]")
    asns = list(range(150, 150 + stub_as_count))
    counts = {asn: 0 for asn in asns}
    placements = {}
    def place(name, asn):
        index = counts[asn]
        counts[asn] += 1
        placements[name] = Placement(asn, f"host_{index:03d}")
    place("beaconsetup", asns[0])
    for i in range(beacons):
        asn = asns[i % len(asns)]
        place(f"gethnode{i:03d}", asn)
        place(f"beaconnode{i:03d}", asn)
    for i in range(beacons * 3 // 2):
        bn = _validator_beacon_index(i, beacons * 3 // 2, beacons)
        place(f"vcnode{i:03d}", asns[bn % len(asns)])
    if max(counts.values()) > mini_internet.MAX_HOSTS_PER_STUB_AS:
        raise ValueError("Placement exceeds /24 host capacity; increase stub_as_count")
    return placements, counts


def _bind(emu: Emulator, vnode: str, placement: Placement) -> None:
    emu.addBinding(
        Binding(
            vnode,
            filter=Filter(asn=placement.asn, nodeName=f"^{placement.host}$"),
            action=Action.FIRST,
        )
    )

def add_ethereum_pos_layer(
    emu: Emulator,
    placements: Dict[str, Placement],
    beacon_count: int,
    geth_count: int,
    validator_count: int,
    beacon_peers: int,
    beacon_bootnodes: int,
    geth_bootnodes: int,
    local_account_count: int,
    *,
    keys_per_client: int = KEYS_PER_CLIENT,
    worker_cap: int = WORKER_CAP,
    geth_cache_mib: int = GETH_CACHE_MIB,
    geth_gomemlimit_mib: int = GETH_GOMEMLIMIT_MIB,
    genesis_delay: int = GENESIS_DELAY_SECONDS,
    reconstruct_historic_states: bool = True,
) -> None:
    eth = EthereumService()
    blockchain = eth.createBlockchain(
        chainName="pos-large",
        consensus=ConsensusMechanism.POS,
        chainId=1337,
    )
    blockchain.setLocalAccountParameters(
        mnemonic="gentle always fun glass foster produce north tail security list example gain",
        balance=LOCAL_ACCOUNT_BALANCE_ETHER,
        total=local_account_count,
    )
    blockchain.setGasLimitPerBlock(BLOCK_GAS_LIMIT)
    blockchain.setTargetCommitteeSize(4)
    blockchain.setTargetAggregatorPerCommittee(2)

    setup: PoSBeaconSetupServer = blockchain.createBeaconSetupNode("beaconsetup")
    setup.setGenesisDelay(genesis_delay)
    setup.setDisplayName("Ethereum-POS-BeaconSetup")
    setup.appendClassName("Ethereum-POS-BeaconSetup")
    setup.addHostName(f"beaconsetup{DOMAIN}")
    _bind(emu, "beaconsetup", placements["beaconsetup"])

    geth_nodes: List[PoSGethServer] = []
    for i in range(geth_count):
        vnode = f"gethnode{i:03d}"
        geth: PoSGethServer = blockchain.createGethNode(vnode)
        geth.enableGethHttp()
        geth.setCacheMiB(geth_cache_mib)
        geth.setGoMemoryLimitMiB(geth_gomemlimit_mib)
        geth.setRpcTxFeeCap(0)
        geth.appendClassName("Ethereum-POS-Geth")
        geth.appendClassName(f"Ethereum-POS-Geth-{i:03d}")
        geth.setDisplayName(f"Ethereum-POS-Geth-{i:03d}")
        geth.addHostName(f"{vnode}{DOMAIN}")
        if i < geth_bootnodes:
            geth.setBootNode(True)
        geth_nodes.append(geth)
        _bind(emu, vnode, placements[vnode])

    beacon_nodes: List[PoSBeaconServer] = []
    for i in range(beacon_count):
        vnode = f"beaconnode{i:03d}"
        beacon: PoSBeaconServer = blockchain.createBeaconNode(vnode)
        beacon.appendClassName("Ethereum-POS-Beacon")
        beacon.appendClassName(f"Ethereum-POS-Beacon-{i:03d}")
        beacon.setDisplayName(f"Ethereum-POS-Beacon-{i:03d}")
        beacon.addHostName(f"{vnode}{DOMAIN}")
        beacon.connectToGethNode(f"gethnode{i % len(geth_nodes):03d}")
        beacon.setBeaconPeerCounts(beacon_peers)
        beacon.setProcessorMaxWorkers(worker_cap)
        beacon.setReconstructHistoricStates(reconstruct_historic_states)
        beacon.enableMetrics(port=5054)
        beacon.setBootstrapRetryPolicy(attempts=720, connect_timeout_seconds=5,
                                       request_timeout_seconds=120)
        if i < beacon_bootnodes:
            beacon.setBootNode(True)
        beacon_nodes.append(beacon)
        _bind(emu, vnode, placements[vnode])

    for i in range(validator_count):
        vnode = f"vcnode{i:03d}"
        validator: PoSVcServer = blockchain.createVcNode(vnode)
        validator.appendClassName("Ethereum-POS-Validator")
        validator.appendClassName(f"Ethereum-POS-Validator-{i:03d}")
        validator.setDisplayName(f"Ethereum-POS-Validator-{i:03d}")
        validator.addHostName(f"{vnode}{DOMAIN}")
        beacon_index = _validator_beacon_index(i, validator_count, beacon_count)
        validator.connectToBeaconNode(f"beaconnode{beacon_index:03d}")
        validator.setValidatorKeyCount(keys_per_client)
        validator.enablePOSValidatorAtGenesis()
        validator.setBootstrapRetryPolicy(attempts=720, connect_timeout_seconds=5,
                                          request_timeout_seconds=120)
        _bind(emu, vnode, placements[vnode])

    emu.addLayer(eth)
    emu.addLayer(EtcHosts())


def run(output=SCRIPT_DIR / "output", beacons=100, stub_as_count=64,
        network=None, accounts=1000, keys_per_client=KEYS_PER_CLIENT,
        worker_cap=WORKER_CAP, geth_gomemlimit_mib=GETH_GOMEMLIMIT_MIB,
        genesis_delay=GENESIS_DELAY_SECONDS, beacon_peers=32, override=False,
        image=None, dry_run=False, lookingglass=False, lookingglass_port=8765,
        lookingglass_run_dir=None, geth_cache_mib=GETH_CACHE_MIB,
        reconstruct_historic_states=True):
    placements, counts = plan_placements(beacons, stub_as_count)
    viewer_placement = None
    if lookingglass:
        asn = min(counts)
        viewer_placement = Placement(asn, f"host_{counts[asn]:03d}")
        counts[asn] += 1
        if counts[asn] > mini_internet.MAX_HOSTS_PER_STUB_AS:
            raise ValueError("Lookingglass needs one additional host; increase stub_as_count")
    config = dict(beacons=beacons, geth=beacons, validator_clients=beacons * 3 // 2,
        keys_per_client=keys_per_client, active_validators=beacons * 3 // 2 * keys_per_client,
        worker_cap=worker_cap, geth_cache_mib=geth_cache_mib,
        geth_gomemlimit_mib=geth_gomemlimit_mib, genesis_delay_seconds=genesis_delay,
        local_accounts=accounts, stub_as_count=stub_as_count, beacon_peers=beacon_peers,
        block_gas_limit=BLOCK_GAS_LIMIT, historic_states="all" if reconstruct_historic_states else "default", image_override=image,
        placements={name: asdict(p) for name, p in placements.items()},
        host_counts=counts)
    if lookingglass:
        config["lookingglass"] = dict(port=lookingglass_port, probe_peers=True,
                                      placement=asdict(viewer_placement))
    if min(accounts, keys_per_client, worker_cap, geth_gomemlimit_mib, beacon_peers) < 1 or accounts < 2:
        raise ValueError("Counts/budgets must be positive and accounts >=2")
    if type(genesis_delay) is not int or genesis_delay < 0:
        raise ValueError("genesis_delay must be a non-negative integer")
    if type(geth_cache_mib) is not int or geth_cache_mib < 0:
        raise ValueError("geth_cache_mib must be a non-negative integer")
    output = Path(output).resolve()
    if dry_run:
        print(json.dumps(config, indent=2))
        return config
    if output.exists() and not override:
        raise ValueError(f"Output exists: {output}; use a new directory or --override")
    if network:
        emu = Emulator()
        emu.load(str(Path(network).resolve()))
        if emu.rendered() or any(layer.getName() == "EthereumService" for layer in emu.getLayers()):
            raise ValueError("Load an unrendered network without blockchain services")
        base = emu.getLayer("Base")
        for name, placement in placements.items():
            try:
                base.getAutonomousSystem(placement.asn).getHost(placement.host)
            except (AssertionError, KeyError) as exc:
                raise ValueError(f"Network lacks host for {name}: {placement}") from exc
    else:
        emu = mini_internet.build_emulator(stub_as_count=stub_as_count, host_counts=counts)
    add_ethereum_pos_layer(emu, placements, beacons, beacons, beacons * 3 // 2,
                           beacon_peers, min(4, beacons), min(3, beacons), accounts,
                           keys_per_client=keys_per_client, worker_cap=worker_cap,
                           geth_cache_mib=geth_cache_mib, geth_gomemlimit_mib=geth_gomemlimit_mib,
                           genesis_delay=genesis_delay,
                           reconstruct_historic_states=reconstruct_historic_states)
    if lookingglass:
        system = emu.getLayer("Base").getAutonomousSystem(viewer_placement.asn)
        try:
            system.getHost(viewer_placement.host)
        except (AssertionError, KeyError):
            system.createHost(viewer_placement.host).joinNetwork("net0")
        viewer = emu.getLayer("EthereumService").createLookingglassServer()
        viewer.setPort(lookingglass_port)
        if lookingglass_run_dir is not None:
            viewer.setObservationDirectory(lookingglass_run_dir)
        _bind(emu, "lookingglass", viewer_placement)
    emu.render()
    compiler = ChainSeedDocker(platform=Platform.AMD64, internetMapEnabled=False)
    if image:
        base = emu.getLayer("Base")
        for placement in placements.values():
            compiler.setImageOverride(base.getAutonomousSystem(placement.asn).getHost(placement.host), image)
        from seedemu.compiler import DockerImage
        compiler.addImage(DockerImage(name=image, software=[], subset=None))
    emu.compile(compiler, str(output), override=override)
    prepare_output(output, config)
    print(f"Runnable output: {output} ({beacons} Beacon, {beacons} Geth, {beacons * 3 // 2} VC)")
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--beacons", type=int, default=100)
    parser.add_argument("--stub-as-count", type=int, default=64)
    parser.add_argument("--network", type=Path, help="Optional unrendered network .bin")
    parser.add_argument("--output", type=Path, default=SCRIPT_DIR / "output")
    parser.add_argument("--accounts", type=int, default=1000)
    parser.add_argument("--keys-per-client", type=int, default=KEYS_PER_CLIENT)
    parser.add_argument("--worker-cap", type=int, default=WORKER_CAP)
    parser.add_argument("--geth-cache-mib", type=int, default=GETH_CACHE_MIB)
    parser.add_argument("--no-reconstruct-historic-states", dest="reconstruct_historic_states",
                        action="store_false", help="Omit historical-state reconstruction on Beacon nodes")
    parser.add_argument("--geth-gomemlimit-mib", type=int, default=GETH_GOMEMLIMIT_MIB)
    parser.add_argument("--genesis-delay", type=int, default=GENESIS_DELAY_SECONDS)
    parser.add_argument("--beacon-peers", type=int, default=32)
    parser.add_argument("--image", help="Optional compatible Ethereum base image tag/digest")
    parser.add_argument("--lookingglass", action="store_true", help="Include the optional Lookingglass viewer")
    parser.add_argument("--lookingglass-port", type=int, default=8765)
    parser.add_argument("--lookingglass-run-dir", type=Path, help="Optional existing/new measurement directory to mount read-only")
    parser.add_argument("--override", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print counts and placement, without compiling")
    args = parser.parse_args()
    try:
        run(**vars(args))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
