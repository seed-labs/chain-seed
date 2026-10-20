#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from typing import Dict, Iterable, List, Set, Tuple
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


STUB_ASNS = [200, 201, 202, 203, 204, 205, 206, 207, 208, 209]

Edge = Tuple[int, int]
Adjacency = Dict[int, Set[int]]


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


def bind_virtual_nodes_round_robin(emu, vnode_names, asns):
    from seedemu import Action, Binding, Filter
    for index, vnode in enumerate(vnode_names):
        emu.addBinding(Binding(vnode, filter=Filter(asn=asns[index % len(asns)], nodeName="host_*"), action=Action.FIRST))


def normalize_edge(a: int, b: int) -> Edge:
    if a == b:
        raise ValueError("self loop")
    return (a, b) if a < b else (b, a)


def adjacency_from_edges(node_count: int, edges: Iterable[Edge]) -> Adjacency:
    adj: Adjacency = {i: set() for i in range(node_count)}
    for a, b in edges:
        if a == b:
            continue
        if not (0 <= a < node_count and 0 <= b < node_count):
            raise ValueError(f"edge {(a, b)} outside 0..{node_count - 1}")
        adj[a].add(b)
        adj[b].add(a)
    return adj


def edges_from_adjacency(adj: Adjacency) -> List[Edge]:
    out: Set[Edge] = set()
    for a, nbrs in adj.items():
        for b in nbrs:
            out.add(normalize_edge(a, b))
    return sorted(out)


def random_regularish_graph(node_count: int, degree: int, seed: int = 1) -> Adjacency:
    """Build a deterministic connected graph with approximately bounded degree.

    It is not a strict random-regular generator. The goal is to create stable
    benchmark overlays that resemble Ethereum's sparse peer graph enough for
    reproducible experiments.
    """
    if node_count < 3:
        raise ValueError("node_count must be >= 3")
    degree = max(2, min(degree, node_count - 1))
    rng = random.Random(seed)
    edges: Set[Edge] = set()

    # Ring backbone guarantees connectivity.
    for i in range(node_count):
        edges.add(normalize_edge(i, (i + 1) % node_count))

    target_edges = node_count * degree // 2
    attempts = 0
    max_attempts = node_count * node_count * 20
    while len(edges) < target_edges and attempts < max_attempts:
        attempts += 1
        a = rng.randrange(node_count)
        b = rng.randrange(node_count)
        if a == b:
            continue
        edge = normalize_edge(a, b)
        if edge in edges:
            continue
        adj = adjacency_from_edges(node_count, edges)
        if len(adj[a]) >= degree + 2 or len(adj[b]) >= degree + 2:
            continue
        edges.add(edge)
    return adjacency_from_edges(node_count, edges)


def graph_summary(adj: Adjacency) -> Dict[str, float]:
    node_count = len(adj)
    edges = edges_from_adjacency(adj)
    degrees = [len(adj[i]) for i in range(node_count)]
    return {
        "nodes": node_count,
        "edges": len(edges),
        "avg_degree": round(sum(degrees) / node_count, 3) if node_count else 0,
        "min_degree": min(degrees) if degrees else 0,
        "max_degree": max(degrees) if degrees else 0,
    }


def write_json(path: str | Path, payload) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_emulator(nodes: int, modified_count: int, custom_geth: str | None = None, save_state: bool = False, degree: int = 8, seed: int = 2027):
    beacon_count = max(2, min(4, nodes // 2))
    validator_count = max(4, beacon_count * 2)
    total_roles = 1 + nodes + beacon_count + validator_count
    hosts_per_as = max(3, (total_roles + len(STUB_ASNS) - 1) // len(STUB_ASNS))
    emu = make_stub_internet(hosts_per_as=hosts_per_as, asns=STUB_ASNS)
    eth = EthereumService(saveState=save_state, override=True)
    chain = eth.createBlockchain(chainName="baa", consensus=ConsensusMechanism.POS, chainId=202701)
    chain.addLocalAccountsFromMnemonic(
        mnemonic="gentle always fun glass foster produce north tail security list example gain",
        total=10,
        balance=1000000,
    )

    overlay = random_regularish_graph(nodes, degree, seed)
    vnode_names = []
    custom_path = Path(custom_geth).resolve() if custom_geth else None
    if custom_path and not custom_path.exists():
        raise FileNotFoundError(f"custom geth binary does not exist: {custom_path}")

    setup = chain.createBeaconSetupNode("baa-beacon-setup")
    emu.getVirtualNode("baa-beacon-setup").setDisplayName("BAA-BeaconSetup")
    vnode_names.append("baa-beacon-setup")

    for i in range(nodes):
        vnode = f"baa-geth-{i:03d}"
        server = chain.createGethNode(vnode)
        server.enableGethHttp()
        server.setNoDiscover().setStaticPeers([f"baa-geth-{peer:03d}" for peer in sorted(overlay[i])])
        server.setMaxPeers(nodes - 1)
        server.appendClassName("BAA-Modified-Geth" if custom_path and i < modified_count else "BAA-Stock-Geth")
        if i == 0:
            server.setBootNode(True)
        if custom_path and i < modified_count:
            server.setCustomGeth(str(custom_path))
        emu.getVirtualNode(vnode).setDisplayName(("BAA-Modified" if custom_path and i < modified_count else "BAA-Stock") + f"-{i:03d}")
        vnode_names.append(vnode)

    for i in range(beacon_count):
        vnode = f"baa-beacon-{i:03d}"
        beacon = chain.createBeaconNode(vnode)
        beacon.connectToGethNode(f"baa-geth-{i % nodes:03d}")
        beacon.appendClassName("BAA-Beacon")
        if i == 0:
            beacon.setBootNode(True)
        emu.getVirtualNode(vnode).setDisplayName(f"BAA-Beacon-{i:03d}")
        vnode_names.append(vnode)

    for i in range(validator_count):
        vnode = f"baa-vc-{i:03d}"
        vc = chain.createVcNode(vnode)
        vc.connectToBeaconNode(f"baa-beacon-{i % beacon_count:03d}")
        vc.enablePOSValidatorAtGenesis()
        vc.appendClassName("BAA-Validator")
        emu.getVirtualNode(vnode).setDisplayName(f"BAA-Validator-{i:03d}")
        vnode_names.append(vnode)

    emu.addLayer(eth)
    bind_virtual_nodes_round_robin(emu, vnode_names, asns=STUB_ASNS)
    emu.addLayer(EtcHosts())
    return emu, vnode_names

def manifest(nodes: int, modified_count: int, seed: int, degree: int, custom_geth: str | None):
    adj = random_regularish_graph(nodes, degree, seed)
    return {
        "experiment": "blockchain_amplification",
        "reference": "Blockchain Amplification Attack",
        "scale": {"ethereum_nodes": nodes, "modified_geth_nodes": modified_count if custom_geth else 0},
        "custom_geth": str(Path(custom_geth).resolve()) if custom_geth else None,
        "node_roles": [
            {"vnode": f"baa-geth-{i:03d}", "role": "modified-geth" if custom_geth and i < modified_count else "stock-geth"}
            for i in range(nodes)
        ],
        "overlay_summary": graph_summary(adj),
        "overlay_edges": edges_from_adjacency(adj),
        "description": "Custom Geth deployment on a controlled Ethereum peer graph",
        "metrics": [
            "honest transaction ratio in txpool",
            "honest transaction ratio in final block",
            "attack transactions included in final block",
        ],
        "note": "Custom binaries are installed with --custom-geth. The author artifact tests run separately; this deployment does not send the attack workload.",
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Build the SEED scenario with custom Geth clients.")
    parser.add_argument("--nodes", type=int, default=80)
    parser.add_argument("--modified-count", type=int, default=1)
    parser.add_argument("--custom-geth", help="Path to a modified Geth binary. If omitted, every node runs stock Geth.")
    parser.add_argument("--require-custom-geth", action="store_true")
    parser.add_argument("--degree", type=int, default=8)
    parser.add_argument("--seed", type=int, default=2027)
    parser.add_argument("--platform", choices=["amd", "arm"], default="amd")
    parser.add_argument("--output", default=str(SCRIPT_DIR / "output"))
    parser.add_argument("--manifest", default=str(SCRIPT_DIR / "results" / "scenario_manifest.json"))
    parser.add_argument("--dumpfile")
    parser.add_argument("--compile", action="store_true", help="Render and compile docker-compose output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.nodes < 4:
        raise SystemExit("--nodes must be >= 4")
    if not (0 <= args.modified_count <= args.nodes):
        raise SystemExit("--modified-count must be in [0, nodes]")
    if args.require_custom_geth and not args.custom_geth:
        raise SystemExit("--require-custom-geth was set but --custom-geth is missing")
    emu, _ = build_emulator(args.nodes, args.modified_count, args.custom_geth, degree=args.degree, seed=args.seed)
    write_json(args.manifest, manifest(args.nodes, args.modified_count, args.seed, args.degree, args.custom_geth))
    if args.dumpfile:
        emu.dump(args.dumpfile)
    if args.compile:
        emu.render()
        output_dir = Path(args.output).resolve()
        ChainSeedDocker(platform=(Platform.AMD64 if args.platform == "amd" else Platform.ARM64)).compile(emu, str(output_dir), override=True)
    print(f"wrote {args.manifest}")
    if args.compile:
        print(f"compiled {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
