#!/usr/bin/env python3
"""Build the final Solana experiment network, including AS2/IX100 anchor links."""
from __future__ import annotations
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from seedemu import Base, Ebgp, Emulator, Ibgp, Ospf, PeerRelationship, Routing

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


ANCHOR_TRANSIT_ASN = 2


ANCHOR_TRANSIT_IX = 100


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
    anchor_ix: int,
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
    if anchor_ix not in (primary_ix, secondary_ix):
        router.joinNetwork(f"ix{anchor_ix}")

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


def _pick_provider(
    providers: Sequence[int],
    offset: int,
    used_provider_asns: set[int],
) -> Optional[int]:
    candidates = [provider for provider in providers if provider not in used_provider_asns]
    if not candidates:
        return None
    return candidates[offset % len(candidates)]


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
            anchor_ix=ANCHOR_TRANSIT_IX,
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
        used_provider_asns = {ANCHOR_TRANSIT_ASN}
        primary_pool = tier1_by_ix[primary_ix] if index % 7 == 0 else regional_by_ix[primary_ix]
        primary_provider = _pick_provider(primary_pool, index, used_provider_asns)
        if primary_provider is not None:
            _safe_private_peering(ebgp, seen_private_peerings, primary_ix, primary_provider, stub_asn)
            used_provider_asns.add(primary_provider)

        _safe_private_peering(
            ebgp,
            seen_private_peerings,
            ANCHOR_TRANSIT_IX,
            ANCHOR_TRANSIT_ASN,
            stub_asn,
        )

        if secondary_ix is not None and secondary_ix != primary_ix:
            secondary_provider = _pick_provider(
                tier1_by_ix[secondary_ix],
                index // 4,
                used_provider_asns,
            )
            if secondary_provider is not None:
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


def host_counts(validators=200, stub_as_count=64):
    if validators < 2 or not 1 <= stub_as_count <= MAX_STUB_AS_COUNT:
        raise ValueError('validators must be >=2 and stub_as_count must be in [1, 100]')
    counts = {150+i: (validators-i+stub_as_count-1)//stub_as_count for i in range(stub_as_count)}
    if max(counts.values()) > MAX_HOSTS_PER_STUB_AS:
        raise ValueError('Placement exceeds /24 capacity; increase stub_as_count')
    return counts


def build_emulator(validators=200, stub_as_count=64):
    counts = host_counts(validators, stub_as_count)
    return build_large_topology(list(counts), counts)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validators', type=int, default=200)
    parser.add_argument('--stub-as-count', type=int, default=64)
    parser.add_argument('--output', type=Path, default=Path('network.bin'))
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output exists; choose a new path')
    emu = build_emulator(args.validators, args.stub_as_count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    emu.dump(str(args.output))
