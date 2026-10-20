"""Shared network definitions for ChainSEED examples; no blockchain services."""

from seedemu.core import Emulator
from seedemu.layers import Base, Ebgp, Ibgp, Ospf, PeerRelationship, Routing
from seedemu.raps import OpenVpnRemoteAccessProvider
from seedemu.utilities import Makers

SYRACUSE_ASN = 11872
SYRACUSE_EXAMPLE_PREFIXES = ["128.230.0.0/16"]
HYBRID_ASN = 99999
HYBRID_DEFAULT_PREFIXES = ["0.0.0.0/1", "128.0.0.0/1"]


def build_mini_internet(hosts_per_as=2) -> Emulator:
    emu = Emulator()
    ebgp = Ebgp()
    base = Base()

    ###############################################################################
    # Create internet exchanges
    ix100 = base.createInternetExchange(100)
    ix101 = base.createInternetExchange(101)
    ix102 = base.createInternetExchange(102)
    ix103 = base.createInternetExchange(103)
    ix104 = base.createInternetExchange(104)
    ix105 = base.createInternetExchange(105)

    # Customize names (for visualization purpose)
    ix100.getPeeringLan().setDisplayName("NYC-100")
    ix101.getPeeringLan().setDisplayName("San Jose-101")
    ix102.getPeeringLan().setDisplayName("Chicago-102")
    ix103.getPeeringLan().setDisplayName("Miami-103")
    ix104.getPeeringLan().setDisplayName("Boston-104")
    ix105.getPeeringLan().setDisplayName("Huston-105")

    ###############################################################################
    # Create Transit Autonomous Systems

    ## Tier 1 ASes
    Makers.makeTransitAs(
        base,
        2,
        [100, 101, 102, 105],
        [(100, 101), (101, 102), (100, 105)],
    )

    Makers.makeTransitAs(
        base,
        3,
        [100, 103, 104, 105],
        [(100, 103), (100, 105), (103, 105), (103, 104)],
    )

    Makers.makeTransitAs(
        base,
        4,
        [100, 102, 104],
        [(100, 104), (102, 104)],
    )

    ## Tier 2 ASes
    Makers.makeTransitAs(base, 11, [102, 105], [(102, 105)])
    Makers.makeTransitAs(base, 12, [101, 104], [(101, 104)])

    ###############################################################################
    # Create single-homed stub ASes.
    Makers.makeStubAsWithHosts(emu, base, 150, 100, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 151, 100, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 152, 101, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 153, 101, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 154, 102, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 160, 103, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 161, 103, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 162, 103, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 163, 104, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 164, 104, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 170, 105, hosts_per_as)
    Makers.makeStubAsWithHosts(emu, base, 171, 105, hosts_per_as)

    # An example to show how to add a host with customized IP address.
    as154 = base.getAutonomousSystem(154)
    new_host = as154.createHost("host_new").joinNetwork("net0", address="10.154.0.129")
    from seedemu.core import OptionMode, OptionRegistry

    o = OptionRegistry().sysctl_netipv4_conf_rp_filter(
        {"all": False, "default": False, "net0": False},
        mode=OptionMode.RUN_TIME,
    )
    new_host.setOption(o)

    o = OptionRegistry().sysctl_netipv4_udp_rmem_min(5000, mode=OptionMode.RUN_TIME)
    new_host.setOption(o)

    ###############################################################################
    # Peering via route servers.
    ebgp.addRsPeers(100, [2, 3, 4])
    ebgp.addRsPeers(102, [2, 4])
    ebgp.addRsPeers(104, [3, 4])
    ebgp.addRsPeers(105, [2, 3])

    # Private peerings for transit service.
    ebgp.addPrivatePeerings(100, [2], [150, 151], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(100, [3], [150], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(101, [2], [12], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(101, [12], [152, 153], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(102, [2, 4], [11, 154], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(102, [11], [154], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(103, [3], [160, 161, 162], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(104, [3, 4], [12], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(104, [4], [163], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(104, [12], [164], PeerRelationship.Provider)

    ebgp.addPrivatePeerings(105, [3], [11, 170], PeerRelationship.Provider)
    ebgp.addPrivatePeerings(105, [11], [171], PeerRelationship.Provider)

    ###############################################################################
    # Add layers to the emulator

    emu.addLayer(base)
    emu.addLayer(Routing())
    emu.addLayer(ebgp)
    emu.addLayer(Ibgp())
    emu.addLayer(Ospf())
    return emu

def add_remote_access(base: Base) -> None:
    ovpn = OpenVpnRemoteAccessProvider()
    base.getAutonomousSystem(152).getNetwork("net0").enableRemoteAccess(ovpn)

def add_real_world_as(base: Base, ebgp: Ebgp, use_live_prefixes: bool = False) -> None:
    prefixes = None if use_live_prefixes else SYRACUSE_EXAMPLE_PREFIXES
    as11872 = base.createAutonomousSystem(SYRACUSE_ASN)
    as11872.createRealWorldRouter("rw-11872-syr", prefixes=prefixes).joinNetwork("ix102", "10.102.0.118")
    ebgp.addPrivatePeerings(102, [11], [SYRACUSE_ASN], PeerRelationship.Provider)

def add_default_real_world_gateway(base: Base, ebgp: Ebgp) -> None:
    as99999 = base.createAutonomousSystem(HYBRID_ASN)
    as99999.createRealWorldRouter(
        "rw-real-world",
        prefixes=HYBRID_DEFAULT_PREFIXES,
    ).joinNetwork("ix100", "10.100.0.99")
    ebgp.addPrivatePeerings(100, [3], [HYBRID_ASN], PeerRelationship.Provider)

def build_hybrid_internet(hosts_per_as: int = 2, use_live_prefixes: bool = False) -> Emulator:
    emu = build_mini_internet(hosts_per_as=hosts_per_as)

    base: Base = emu.getLayer("Base")
    ebgp: Ebgp = emu.getLayer("Ebgp")

    add_remote_access(base)
    add_real_world_as(base, ebgp, use_live_prefixes=use_live_prefixes)
    add_default_real_world_gateway(base, ebgp)
    return emu

def build_emulator(hosts_per_as: int = 2, topology: str = "mini") -> Emulator:
    """Build a fresh network, preserving the historical mini/hybrid layouts."""
    if hosts_per_as < 1:
        raise ValueError("hosts_per_as must be at least one")
    if topology == "mini":
        return Makers.makeEmulatorBaseWith10StubASAndHosts(hosts_per_as)
    if topology == "full":
        return build_mini_internet(hosts_per_as)
    if topology == "hybrid":
        return build_hybrid_internet(hosts_per_as)
    raise ValueError("unknown network topology: " + topology)


def run(dumpfile=None, hosts_per_as: int = 2, topology: str = "mini") -> Emulator:
    """Return the unrendered network and optionally export it for later binding."""
    emulator = build_emulator(hosts_per_as, topology)
    if dumpfile is not None:
        from pathlib import Path
        target = Path(dumpfile).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        emulator.dump(str(target))
    return emulator


def main():
    import argparse
    from pathlib import Path
    from seedemu.compiler import Docker, Platform

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts-per-as", type=int, default=2)
    parser.add_argument("--topology", choices=("mini", "full", "hybrid"), default="mini")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--dumpfile")
    target.add_argument("--output", help="Render and compile a network-only Docker deployment")
    parser.add_argument("--platform", choices=("amd", "arm"), default="amd")
    args = parser.parse_args()
    emulator = run(
        dumpfile=None if args.output else args.dumpfile or "mini-internet.bin",
        hosts_per_as=args.hosts_per_as,
        topology=args.topology,
    )
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        emulator.render()
        platform = Platform.AMD64 if args.platform == "amd" else Platform.ARM64
        emulator.compile(Docker(platform=platform), str(output), override=True)


if __name__ == "__main__":
    main()
