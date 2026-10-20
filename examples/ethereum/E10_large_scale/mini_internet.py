"""E10 network only: exchanges, transit/stub ASes, routing and host capacity."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from seedemu.core import Emulator
from seedemu.layers import Base, Routing, Ebgp, Ibgp, Ospf, PeerRelationship

STUB_AS_START = 150
MAX_STUB_AS_COUNT = 100
MAX_HOSTS_PER_STUB_AS = 129
IXES: Dict[int, str] = {
    100: "New-York-100",
    101: "San-Jose-101",
    102: "Chicago-102",
    103: "Atlanta-103",
    104: "Dallas-104",
    105: "Seattle-105",
    106: "Amsterdam-106",
    107: "Singapore-107",
    108: "Frankfurt-108",
    109: "Tokyo-109",
}

TIER1_TRANSITS: Dict[int, List[int]] = {
    2: [100, 101, 102, 105],
    3: [100, 103, 104, 106],
    4: [101, 102, 104, 107],
    5: [102, 103, 105, 106],
    6: [100, 104, 105, 107],
    7: [103, 106, 108, 109],
    8: [104, 107, 108, 109],
}

REGIONAL_TRANSITS: Dict[int, List[int]] = {
    20: [100, 101],
    21: [101, 105],
    22: [102, 104],
    23: [103, 104],
    24: [105, 106],
    25: [106, 107],
    26: [100, 102, 103],
    27: [104, 105, 107],
    28: [108, 109],
    29: [100, 108],
    30: [103, 109],
    31: [104, 108],
    32: [105, 109],
    33: [102, 108, 109],
}

REGIONAL_UPSTREAMS: Dict[int, List[Tuple[int, int]]] = {
    20: [(100, 2), (101, 4)],
    21: [(101, 2), (105, 6)],
    22: [(102, 5), (104, 4)],
    23: [(103, 3), (104, 6)],
    24: [(105, 5), (106, 3)],
    25: [(106, 3), (107, 4)],
    26: [(100, 2), (102, 5), (103, 3)],
    27: [(104, 4), (105, 6), (107, 6)],
    28: [(108, 7), (109, 8)],
    29: [(100, 2), (108, 7)],
    30: [(103, 3), (109, 7)],
    31: [(104, 8), (108, 7)],
    32: [(105, 6), (109, 8)],
    33: [(102, 5), (108, 7), (109, 8)],
}

def _asns_by_ix(transits: Dict[int, List[int]]) -> Dict[int, List[int]]:
    by_ix = {ix: [] for ix in IXES}
    for asn, exchanges in transits.items():
        for ix in exchanges:
            by_ix[ix].append(asn)
    return by_ix

def _backbone_links(exchanges: Sequence[int]) -> List[Tuple[int, int]]:
    links = [(exchanges[i], exchanges[i + 1]) for i in range(len(exchanges) - 1)]
    if len(exchanges) > 3:
        links.append((exchanges[0], exchanges[-1]))
    return links

def _backbone_name(left_ix: int, right_ix: int) -> str:
    return f"bb{left_ix}_{right_ix}"

def _create_transit_as(base: Base, asn: int, exchanges: Sequence[int]) -> None:
    transit_as = base.createAutonomousSystem(asn)
    routers = {}

    for ix in exchanges:
        routers[ix] = transit_as.createRouter(f"r{ix}")
        routers[ix].joinNetwork(f"ix{ix}")

    for index, (left_ix, right_ix) in enumerate(_backbone_links(exchanges)):
        net = transit_as.createNetwork(_backbone_name(left_ix, right_ix))
        net.setDefaultLinkProperties(
            latency=2 + (index % 4),
            bandwidth=1_000_000_000,
            packetDrop=0,
        )
        routers[left_ix].joinNetwork(net.getName())
        routers[right_ix].joinNetwork(net.getName())

def _create_stub_as(
    base: Base,
    asn: int,
    host_count: int,
    primary_ix: int,
    secondary_ix: Optional[int],
    stub_index: int,
) -> None:
    stub_as = base.createAutonomousSystem(asn)
    net = stub_as.createNetwork("net0")
    net.setHostIpRange(hostStart=71, hostEnd=199, hostStep=1)
    net.setDefaultLinkProperties(
        latency=1 + (stub_index % 6),
        bandwidth=250_000_000,
        packetDrop=0,
    )

    router = stub_as.createRouter("router0")
    router.joinNetwork("net0")
    router.joinNetwork(f"ix{primary_ix}")
    if secondary_ix is not None and secondary_ix != primary_ix:
        router.joinNetwork(f"ix{secondary_ix}")

    assert host_count <= MAX_HOSTS_PER_STUB_AS, (
        f"AS{asn} needs {host_count} hosts, but net0 only supports "
        f"{MAX_HOSTS_PER_STUB_AS}. Increase --stub-as-count."
    )
    for host_id in range(host_count):
        stub_as.createHost(f"host_{host_id:03d}").joinNetwork("net0")

def _safe_private_peering(
    ebgp: Ebgp,
    seen: set[Tuple[int, int, int]],
    ix: int,
    provider: int,
    customer: int,
    relationship: PeerRelationship = PeerRelationship.Provider,
) -> None:
    key = (ix, provider, customer)
    if key in seen:
        return
    ebgp.addPrivatePeering(ix, provider, customer, relationship)
    seen.add(key)

def build_large_topology(stub_asns: Sequence[int], host_counts: Dict[int, int]) -> Emulator:
    emu = Emulator()
    base = Base()
    routing = Routing()
    ebgp = Ebgp()
    ibgp = Ibgp()
    ospf = Ospf()

    for ix, display_name in IXES.items():
        base.createInternetExchange(ix).getPeeringLan().setDisplayName(display_name)

    for asn, exchanges in TIER1_TRANSITS.items():
        _create_transit_as(base, asn, exchanges)

    for asn, exchanges in REGIONAL_TRANSITS.items():
        _create_transit_as(base, asn, exchanges)

    ix_sequence = list(IXES.keys())
    stub_profiles: Dict[int, Tuple[int, Optional[int]]] = {}
    for index, asn in enumerate(stub_asns):
        primary_ix = ix_sequence[index % len(ix_sequence)]
        secondary_ix = ix_sequence[(index * 3 + 1) % len(ix_sequence)] if index % 4 == 0 else None
        stub_profiles[asn] = (primary_ix, secondary_ix)
        _create_stub_as(
            base=base,
            asn=asn,
            host_count=host_counts.get(asn, 0),
            primary_ix=primary_ix,
            secondary_ix=secondary_ix,
            stub_index=index,
        )

    transit_by_ix = _asns_by_ix({**TIER1_TRANSITS, **REGIONAL_TRANSITS})
    for ix, peers in transit_by_ix.items():
        if peers:
            ebgp.addRsPeers(ix, sorted(peers))

    seen_private_peerings: set[Tuple[int, int, int]] = set()

    for regional_asn, upstreams in REGIONAL_UPSTREAMS.items():
        for ix, provider_asn in upstreams:
            _safe_private_peering(ebgp, seen_private_peerings, ix, provider_asn, regional_asn)

    tier1_by_ix = _asns_by_ix(TIER1_TRANSITS)
    regional_by_ix = _asns_by_ix(REGIONAL_TRANSITS)

    for index, stub_asn in enumerate(stub_asns):
        primary_ix, secondary_ix = stub_profiles[stub_asn]
        primary_pool = tier1_by_ix[primary_ix] if index % 7 == 0 else regional_by_ix[primary_ix]
        primary_provider = primary_pool[index % len(primary_pool)]
        _safe_private_peering(ebgp, seen_private_peerings, primary_ix, primary_provider, stub_asn)

        if secondary_ix is not None and secondary_ix != primary_ix:
            # A stub AS uses one border router for both IX links. Peering with the
            # same provider on both IXes creates duplicate BIRD protocol names.
            secondary_pool = [
                provider for provider in tier1_by_ix[secondary_ix]
                if provider != primary_provider
            ]
            if not secondary_pool:
                secondary_pool = tier1_by_ix[secondary_ix]
            secondary_provider = secondary_pool[(index // 4) % len(secondary_pool)]
            _safe_private_peering(
                ebgp,
                seen_private_peerings,
                secondary_ix,
                secondary_provider,
                stub_asn,
            )

    for offset in range(0, max(0, len(stub_asns) - len(ix_sequence)), len(ix_sequence)):
        left = stub_asns[offset]
        right = stub_asns[offset + len(ix_sequence)]
        ix, _ = stub_profiles[left]
        _safe_private_peering(
            ebgp,
            seen_private_peerings,
            ix,
            left,
            right,
            relationship=PeerRelationship.Peer,
        )

    emu.addLayer(base)
    emu.addLayer(routing)
    emu.addLayer(ebgp)
    emu.addLayer(ibgp)
    emu.addLayer(ospf)
    return emu

def build_emulator(stub_as_count=64, hosts_per_as=32, host_counts=None):
    if not 1 <= stub_as_count <= MAX_STUB_AS_COUNT:
        raise ValueError("stub_as_count must be in [1, 100]")
    asns = list(range(STUB_AS_START, STUB_AS_START + stub_as_count))
    counts = host_counts if host_counts is not None else {asn: hosts_per_as for asn in asns}
    if set(counts) != set(asns) or any(type(n) is not int or not 0 <= n <= MAX_HOSTS_PER_STUB_AS for n in counts.values()):
        raise ValueError("Provide 0..129 hosts for each stub AS")
    return build_large_topology(asns, counts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stub-as-count", type=int, default=64)
    parser.add_argument("--hosts-per-as", type=int, default=32)
    parser.add_argument("--host-counts", type=Path, help="Optional JSON mapping AS number to host count")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("network.bin"))
    args = parser.parse_args()
    counts = {int(k): v for k, v in json.loads(args.host_counts.read_text()).items()} if args.host_counts else None
    if args.output.exists():
        parser.error("Output already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    build_emulator(args.stub_as_count, args.hosts_per_as, counts).dump(str(args.output))
    print(f"Saved unrendered network to {args.output}")
