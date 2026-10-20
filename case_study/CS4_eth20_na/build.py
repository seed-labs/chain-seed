#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from seedemu import *
from seedemu.utilities import Makers
from chainseed import ChainSeedDocker
from chainseed.services.ethereum import ConsensusMechanism, EthereumService

# Keep ASNs <=255 because the helper maps ASNs to 10.<asn>.0.0/24 prefixes.
# These ASNs avoid the previously generated experiments in this workspace.
STUB_ASNS = [220, 221, 222, 223, 224, 225, 226, 227]
BINDING_ASNS = [220, 221, 223, 224, 225, 226, 227]
TRANSIT_ASN = 6
IX_BASE = 120
DOMAIN = ".net"
MNEMONIC = "gentle always fun glass foster produce north tail security list example gain"
CHAIN_ID = 2027063


def make_stub_internet(hosts_per_as: int, asns, transit_asn: int = 2, ix: int = 100):
    """Create BGP-routed stub ASes connected through a transit AS."""
    emu = Emulator()
    base = Base()
    routing = Routing()
    ebgp = Ebgp()

    stub_asn_list = [int(asn) for asn in asns]
    ixes = [ix + idx for idx in range(len(stub_asn_list))]
    for ix_id in ixes:
        base.createInternetExchange(ix_id, create_rs=False)

    intra_ix_links = [(ixes[0], ix_id) for ix_id in ixes[1:]]
    Makers.makeTransitAs(base, transit_asn, ixes, intra_ix_links)

    for asn, ix_id in zip(stub_asn_list, ixes):
        stub = base.createAutonomousSystem(asn)
        stub.createNetwork("net0")
        for host_index in range(hosts_per_as):
            stub.createHost(f"host_{host_index}").joinNetwork("net0")
        stub.createRouter("router0").joinNetwork("net0").joinNetwork(f"ix{ix_id}")
        ebgp.addPrivatePeerings(ix_id, [transit_asn], [asn], PeerRelationship.Provider)

    emu.addLayer(base)
    emu.addLayer(routing)
    emu.addLayer(ebgp)
    emu.addLayer(Ibgp())
    emu.addLayer(Ospf())
    return emu


def write_json(path: Path | str, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def assign_node(emu: Emulator, vnode: str, index: int, hosts_per_as: int) -> dict[str, Any]:
    asn = BINDING_ASNS[index % len(BINDING_ASNS)]
    host_index = index // len(BINDING_ASNS)
    if host_index >= hosts_per_as:
        raise ValueError(f"not enough hosts_per_as={hosts_per_as} for node index {index}")
    ip = f"10.{asn}.0.{71 + host_index}"
    emu.addBinding(
        Binding(
            vnode,
            filter=Filter(asn=asn, nodeName=f"^host_{host_index}$"),
            action=Action.FIRST,
        )
    )
    return {"vnode": vnode, "asn": asn, "host_index": host_index, "ip": ip}


def build_emulator(
    *,
    beacon_nodes: int,
    validators_per_beacon: int,
    geth_nodes: int,
    target_peers: int,
    metrics: bool,
    subscribe_all_subnets: bool,
) -> tuple[Emulator, dict[str, Any]]:
    if beacon_nodes < 2:
        raise ValueError("beacon_nodes must be >= 2")
    if validators_per_beacon < 1:
        raise ValueError("validators_per_beacon must be >= 1")
    if type(target_peers) is not int or target_peers < 1:
        raise ValueError("target_peers must be a positive integer")
    if geth_nodes < 1:
        raise ValueError("geth_nodes must be >= 1")

    total_validators = beacon_nodes * validators_per_beacon
    vnode_names = ["BeaconSetupNode"]
    vnode_names += [f"gethnode{i}" for i in range(geth_nodes)]
    vnode_names += [f"beaconnode{i}" for i in range(beacon_nodes)]
    vnode_names += [f"vcnode{i}" for i in range(total_validators)]
    hosts_per_as = max(4, math.ceil(len(vnode_names) / len(BINDING_ASNS)))

    emu = make_stub_internet(hosts_per_as=hosts_per_as, asns=STUB_ASNS, transit_asn=TRANSIT_ASN, ix=IX_BASE)

    eth = EthereumService()
    chain = eth.createBlockchain(chainName="eth20-na", consensus=ConsensusMechanism.POS, chainId=CHAIN_ID)
    chain.addLocalAccountsFromMnemonic(mnemonic=MNEMONIC, total=16, balance=1000000)

    chain.createBeaconSetupNode("BeaconSetupNode")
    emu.getVirtualNode("BeaconSetupNode").setDisplayName("Eth20NA-BeaconSetup")

    for i in range(geth_nodes):
        geth = chain.createGethNode(f"gethnode{i}")
        geth.enableGethHttp()
        geth.appendClassName(f"Eth20NA-Geth-{i}")
        geth.addHostName(f"gethnode{i}{DOMAIN}")
        if i == 0:
            geth.setBootNode(True)
        emu.getVirtualNode(f"gethnode{i}").setDisplayName(f"Eth20NA-Geth-{i}")

    for i in range(beacon_nodes):
        beacon = chain.createBeaconNode(f"beaconnode{i}")
        beacon.appendClassName(f"Eth20NA-Beacon-{i}")
        beacon.addHostName(f"beaconnode{i}{DOMAIN}")
        beacon.connectToGethNode(f"gethnode{i % geth_nodes}")
        beacon.setBeaconPeerCounts(target_peers)
        beacon.enableMetrics(metrics)
        beacon.setSubscribeAllSubnets(subscribe_all_subnets)
        if i == 0:
            beacon.setBootNode(True)
        emu.getVirtualNode(f"beaconnode{i}").setDisplayName(f"Eth20NA-Beacon-{i}")

    for i in range(total_validators):
        vc = chain.createVcNode(f"vcnode{i}")
        vc.appendClassName(f"Eth20NA-Validator-{i}")
        vc.connectToBeaconNode(f"beaconnode{i % beacon_nodes}")
        vc.enablePOSValidatorAtGenesis()
        emu.getVirtualNode(f"vcnode{i}").setDisplayName(f"Eth20NA-Validator-{i}")

    emu.addLayer(eth)

    assignments = []
    for index, vnode in enumerate(vnode_names):
        assignments.append(assign_node(emu, vnode, index, hosts_per_as))

    emu.addLayer(EtcHosts())

    role_by_vnode = {row["vnode"]: row for row in assignments}
    beacon_rows = []
    for i in range(beacon_nodes):
        row = role_by_vnode[f"beaconnode{i}"]
        name = f"as{row['asn']}h-Eth20NA-Beacon-{i}-{row['ip']}"
        beacon_rows.append({**row, "index": i, "container": name, "api": f"http://{row['ip']}:8000", "metrics": f"http://{row['ip']}:5054/metrics"})

    manifest = {
        "experiment": "eth20_na",
        "reference": "Eth2.0-NA: Modeling Message Propagation to Optimize Mesh Size in Ethereum 2.0 Network",
        "reference_doi": "10.1109/INFOCOM59046.2026.11571391",
        "description": "Vary Lighthouse target peers on a fixed network and observe traffic and sampled head spread",
        "chain_id": CHAIN_ID,
        "target_peers": target_peers,
        "beacon_nodes": beacon_nodes,
        "validators_per_beacon": validators_per_beacon,
        "validators": total_validators,
        "geth_nodes": geth_nodes,
        "metrics_enabled": metrics,
        "subscribe_all_subnets": subscribe_all_subnets,
        "stub_asns": STUB_ASNS,
        "binding_asns": BINDING_ASNS,
        "transit_asn": TRANSIT_ASN,
        "ix_base": IX_BASE,
        "hosts_per_as": hosts_per_as,
        "vnode_assignments": assignments,
        "beacons": beacon_rows,
        "expected_observations": [
            "connected beacon peer count increases with target_peers when enough beacon nodes exist",
            "higher forwarding redundancy should not increase propagation delay under the same topology",
            "higher forwarding redundancy should increase aggregate network bytes or gossip-related metrics",
        ],
    }
    return emu, manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Lighthouse peer-configuration example.")
    parser.add_argument("--beacon-nodes", type=int, default=10)
    parser.add_argument("--validators-per-beacon", type=int, default=1)
    parser.add_argument("--geth-nodes", type=int, default=1)
    parser.add_argument("--target-peers", type=int, default=8)
    parser.add_argument("--platform", choices=["amd", "arm"], default="amd")
    parser.add_argument("--output", default=None)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--dumpfile")
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--no-metrics", action="store_true")
    parser.add_argument("--no-subscribe-all-subnets", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    emu, manifest = build_emulator(
        beacon_nodes=args.beacon_nodes,
        validators_per_beacon=args.validators_per_beacon,
        geth_nodes=args.geth_nodes,
        target_peers=args.target_peers,
        metrics=not args.no_metrics,
        subscribe_all_subnets=not args.no_subscribe_all_subnets,
    )
    manifest_path = Path(args.manifest or SCRIPT_DIR / "results" / f"scenario_manifest_tp{args.target_peers}.json").resolve()
    write_json(manifest_path, manifest)
    if args.dumpfile:
        emu.dump(args.dumpfile)
    if args.compile:
        emu.render()
        output_dir = Path(args.output or SCRIPT_DIR / f"output_tp{args.target_peers}").resolve()
        emu.compile(
            ChainSeedDocker(internetMapEnabled=False, platform=(Platform.AMD64 if args.platform == "amd" else Platform.ARM64)),
            str(output_dir),
            override=True,
        )
        print(f"compiled {output_dir}")
    print(f"wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
