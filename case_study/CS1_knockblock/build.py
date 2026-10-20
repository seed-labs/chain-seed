#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from seedemu import *
from seedemu.utilities import Makers
from chainseed import ChainSeedDocker
from chainseed.services.ethereum import ConsensusMechanism, EthereumService
from seedemu.services import ExaBgpService

STUB_ASNS = [200, 201, 202, 203, 204, 205, 206, 207]

# The generated stub Internet keeps AS202 as a harmless dummy AS because the
# multi-IX transit topology uses the third IX internally. In Docker runtime
# tests on this host, the AS2 router attached to that IX does not reliably
# propagate routes to the rest of AS2. We therefore bind BlockchainService
# nodes only to ASes whose prefixes are reachable from all other experiment ASes.
BLOCKCHAIN_BINDING_ASNS = [200, 201, 203, 204, 205, 206, 207]

KNOCKBLOCK_SH = r'''#!/usr/bin/env bash
set -euo pipefail
prefix=${1:-10.203.0.0/25}
duration=${2:-12}
: "${prefix:?prefix required}"
mkdir -p /run/exabgp
mkfifo /run/exabgp/manual.in 2>/dev/null || true
echo "announce route ${prefix} next-hop self" > /run/exabgp/manual.in
sleep "${duration}"
echo "withdraw route ${prefix} next-hop self" > /run/exabgp/manual.in
'''

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


def write_json(path: str | Path, payload) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def add_exabgp_attacker(emu, target_prefixes):
    base = emu.getLayer("Base")
    attacker = base.createAutonomousSystem(230)
    attacker.createHost("exabgp").joinNetwork("ix100", address="10.100.0.230")
    exabgp = ExaBgpService()
    speaker = exabgp.install("knockblock-exabgp").setLocalAsn(230)
    speaker.addPeer(ix=100, peer_asn=2, router_relationship="customer")
    # No static announcements. The attack script announces and withdraws during
    # the proposer window, matching the short-lived KnockBlock setting.
    emu.addBinding(Binding("knockblock-exabgp", filter=Filter(asn=230, nodeName="exabgp")))
    emu.addLayer(exabgp)
    vnode = emu.getVirtualNode("knockblock-exabgp")
    vnode.setFile("/root/knockblock_hijack.sh", KNOCKBLOCK_SH)
    vnode.appendStartCommand("chmod +x /root/knockblock_hijack.sh")
    vnode.setFile("/root/target_prefixes.txt", "\n".join(target_prefixes) + "\n")


def build_emulator(beacon_nodes: int, validators_per_beacon: int, target_prefixes, geth_nodes: int = 1):
    total_validators = beacon_nodes * validators_per_beacon
    blockchain_vnode_count = 1 + geth_nodes + beacon_nodes + total_validators
    hosts_per_as = max(4, math.ceil(blockchain_vnode_count / len(BLOCKCHAIN_BINDING_ASNS)) + 1)
    emu = make_stub_internet(hosts_per_as=hosts_per_as, asns=STUB_ASNS)
    eth = EthereumService()
    chain = eth.createBlockchain(chainName="pos-routing", consensus=ConsensusMechanism.POS, chainId=202703)
    chain.addLocalAccountsFromMnemonic(
        mnemonic="gentle always fun glass foster produce north tail security list example gain",
        total=10,
        balance=1000000,
    )

    geth_node_objs = []
    beacon_servers = []
    vc_nodes = []
    setup = chain.createBeaconSetupNode("BeaconSetupNode")
    emu.getVirtualNode("BeaconSetupNode").setDisplayName("Routing-POS-BeaconSetup")

    for i in range(geth_nodes):
        g = chain.createGethNode(f"gethnode{i}")
        g.enableGethHttp().appendClassName("Routing-POS-Geth")
        if i == 0:
            g.setBootNode(True)
        geth_node_objs.append(g)
        emu.getVirtualNode(f"gethnode{i}").setDisplayName(f"Routing-POS-Geth-{i}")

    for i in range(beacon_nodes):
        b = chain.createBeaconNode(f"beaconnode{i}")
        b.appendClassName("Routing-POS-Beacon")
        b.connectToGethNode(f"gethnode{i % geth_nodes}")
        if i == 0:
            b.setBootNode(True)
        beacon_servers.append(b)
        emu.getVirtualNode(f"beaconnode{i}").setDisplayName(f"Routing-POS-Beacon-{i}")

    for i in range(total_validators):
        vc = chain.createVcNode(f"vcnode{i}")
        vc.appendClassName("Routing-POS-Validator")
        vc.connectToBeaconNode(f"beaconnode{i % len(beacon_servers)}")
        vc.enablePOSValidatorAtGenesis()
        vc_nodes.append(vc)
        emu.getVirtualNode(f"vcnode{i}").setDisplayName(f"Routing-POS-Validator-{i}")

    emu.addLayer(eth)
    all_vnodes = ["BeaconSetupNode"] + [f"gethnode{i}" for i in range(geth_nodes)] + [f"beaconnode{i}" for i in range(beacon_nodes)] + [f"vcnode{i}" for i in range(total_validators)]
    for index, vnode in enumerate(all_vnodes):
        emu.addBinding(Binding(vnode, filter=Filter(asn=BLOCKCHAIN_BINDING_ASNS[index % len(BLOCKCHAIN_BINDING_ASNS)], nodeName="host_*"), action=Action.FIRST))

    add_exabgp_attacker(emu, target_prefixes)
    return emu


def parse_args():
    parser = argparse.ArgumentParser(description="Build an Ethereum PoS network for a routing attack.")
    parser.add_argument("--beacon-nodes", type=int, default=8)
    parser.add_argument("--geth-nodes", type=int, default=1)
    parser.add_argument("--validators-per-beacon", type=int, default=4)
    parser.add_argument(
        "--target-prefix",
        action="append",
        dest="target_prefixes",
        default=None,
        help="Beacon prefix for the experiment manifest (default: 10.203.0.0/25).",
    )
    parser.add_argument("--platform", choices=["amd", "arm"], default="amd")
    parser.add_argument("--output", default=str(SCRIPT_DIR / "output"))
    parser.add_argument("--manifest", default=str(SCRIPT_DIR / "results" / "scenario_manifest.json"))
    parser.add_argument("--dumpfile")
    parser.add_argument("--compile", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.beacon_nodes < 1 or args.validators_per_beacon < 1 or args.geth_nodes < 1:
        raise SystemExit("beacon, geth, and validator counts must be positive")
    args.target_prefixes = args.target_prefixes or ["10.203.0.0/25"]
    emu = build_emulator(args.beacon_nodes, args.validators_per_beacon, args.target_prefixes, geth_nodes=args.geth_nodes)
    write_json(args.manifest, {
        "experiment": "routing_pos_attack",
        "reference": "Routing Attacks in Ethereum PoS",
        "description": "Short BGP hijack targeting a Beacon that serves a scheduled proposer",
        "attack": "KnockBlock short BGP hijack of the proposer immediately before the attacker's proposer slot",
        "scale": {
            "beacon_nodes": args.beacon_nodes,
            "geth_nodes": args.geth_nodes,
            "validators": args.beacon_nodes * args.validators_per_beacon,
            "hosts_per_as": max(4, math.ceil((1 + args.geth_nodes + args.beacon_nodes + args.beacon_nodes * args.validators_per_beacon) / len(BLOCKCHAIN_BINDING_ASNS)) + 1),
            "stub_asns": STUB_ASNS,
            "slot_seconds": 12,
        },
        "target_prefixes": args.target_prefixes,
        "target_role": "Beacon 0 serving the victim proposer selected from the duty schedule",
        "node_role_prefixes": {
            name: f"10.{BLOCKCHAIN_BINDING_ASNS[index % len(BLOCKCHAIN_BINDING_ASNS)]}.0.0/24"
            for index, name in enumerate(
                ["BeaconSetupNode"] + [f"gethnode{i}" for i in range(args.geth_nodes)]
                + [f"beaconnode{i}" for i in range(args.beacon_nodes)]
                + [f"vcnode{i}" for i in range(args.beacon_nodes * args.validators_per_beacon)]
            )
        },
        "runtime_scripts": {
            "exabgp": "/root/knockblock_hijack.sh <prefix> <duration_seconds>",
        },
        "metrics": [
            "selected route to victim prefix",
            "victim reachability before, during, and after hijack",
            "victim proposer slot and subsequent control slot block presence",
        ],
        "note": "This scenario measures routing and consensus behavior, not MEV or proposer revenue.",
    })
    if args.dumpfile:
        emu.dump(args.dumpfile)
    if args.compile:
        emu.render()
        output_dir = Path(args.output).resolve()
        ChainSeedDocker(internetMapEnabled=True, platform=(Platform.AMD64 if args.platform == "amd" else Platform.ARM64)).compile(emu, str(output_dir), override=True)
    print(f"wrote {args.manifest}")
    if args.compile:
        print(f"compiled {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
