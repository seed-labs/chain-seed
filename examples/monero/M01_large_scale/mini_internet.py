#!/usr/bin/env python3
"""Build the single-IX network used by the large-scale Monero example."""
from __future__ import annotations

import argparse
from pathlib import Path

from seedemu import Base, Ebgp, Emulator, Ibgp, Makers, Ospf, PeerRelationship, Routing

STUB_AS_START = 150
MAX_STUB_AS_COUNT = 100
MAX_HOSTS_PER_STUB_AS = 129


def host_counts(nodes: int, stub_as_count: int | None = None) -> dict[int, int]:
    if not 1 <= nodes <= 12000:
        raise ValueError("nodes must be in [1, 12000]")
    count = min(MAX_STUB_AS_COUNT, nodes) if stub_as_count is None else stub_as_count
    if not 1 <= count <= min(MAX_STUB_AS_COUNT, nodes):
        raise ValueError("stub_as_count must be in [1, min(100, nodes)]")
    counts = {STUB_AS_START + i: (nodes - i + count - 1) // count for i in range(count)}
    if max(counts.values()) > MAX_HOSTS_PER_STUB_AS:
        raise ValueError("Too many hosts for a /24 network; increase stub_as_count")
    return counts


def build_emulator(nodes: int = 1200, stub_as_count: int | None = None) -> Emulator:
    """Return an unrendered network, without blockchain services."""
    counts = host_counts(nodes, stub_as_count)
    emu, base, bgp = Emulator(), Base(), Ebgp()
    base.createInternetExchange(100)
    Makers.makeTransitAs(base, 2, [100], [])
    bgp.addRsPeers(100, [2])
    for asn, count in counts.items():
        stub = base.createAutonomousSystem(asn)
        stub.createNetwork("net0").setHostIpRange(71, 199, 1)
        stub.createRouter("router0").joinNetwork("net0").joinNetwork("ix100")
        bgp.addPrivatePeerings(100, [2], [asn], PeerRelationship.Provider)
        for index in range(count):
            stub.createHost(f"host_{index}").joinNetwork("net0", address=f"10.{asn}.0.{71 + index}")
    for layer in (base, Routing(), bgp, Ibgp(), Ospf()):
        emu.addLayer(layer)
    return emu


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=1200)
    parser.add_argument("--stub-as-count", type=int, help="Default: min(100, nodes)")
    parser.add_argument("--output", type=Path, default=Path("network.bin"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new path")
    emu = build_emulator(args.nodes, args.stub_as_count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    emu.dump(str(args.output))
    print(f"Network saved to {args.output}")


if __name__ == "__main__":
    main()
