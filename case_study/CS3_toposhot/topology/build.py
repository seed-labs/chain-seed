#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from seedemu import *
from seedemu.utilities import Makers
from chainseed import ChainSeedDocker
from chainseed.services.ethereum import ConsensusMechanism, EthereumService


CHAIN_ID = 202705
MNEMONIC = "gentle always fun glass foster produce north tail security list example gain"
CUSTOM_GETH = REPO_ROOT / "examples" / "ethereum" / "E09_blockchain" / "resources" / "custom_geth"
SCALE_ASNS = [238, 239, 240, 241, 242, 243]
SINGLE_ASN = 238
TRANSIT_ASN = 5
BASE_IX = 160

DEFAULT_GETH_MEMORY_MIB = 256
DEFAULT_BASE_MEMORY_MIB = 8192
DEFAULT_MEMORY_SAFETY_FACTOR = 1.5


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


def set_default_host_ip_ranges(emu, asns, start=71, end=250):
    base_layer = emu.getLayer("Base")
    for asn in asns:
        as_obj = base_layer.getAutonomousSystem(asn)
        try:
            net0 = as_obj.getNetwork("net0")
        except Exception:
            continue
        net0.setHostIpRange(hostStart=start, hostEnd=end, hostStep=1)


def bind_virtual_nodes_round_robin(emu, vnode_names, asns):
    from seedemu import Action, Binding, Filter
    for index, vnode in enumerate(vnode_names):
        emu.addBinding(Binding(vnode, filter=Filter(asn=asns[index % len(asns)], nodeName="host_*"), action=Action.FIRST))


def write_json(path: str | Path, payload) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def memory_available_mib() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def enforce_resource_guard(nodes: int, memory_per_geth_mib: int, safety_factor: float) -> None:
    geth_count = nodes + 1
    estimated = DEFAULT_BASE_MEMORY_MIB + geth_count * memory_per_geth_mib
    required = int(estimated * safety_factor)
    available = memory_available_mib()
    if available is None:
        print("warning: could not read /proc/meminfo; skipping memory guard", file=sys.stderr)
        return
    if required > available:
        raise SystemExit(
            "refusing to compile likely oversized TopoShot live scale scenario: "
            f"measured_nodes={nodes}, geth_containers={geth_count}, "
            f"estimated={estimated} MiB, safety_factor={safety_factor}, "
            f"required={required} MiB, available={available} MiB. "
            "Use a smaller --nodes value or pass --skip-resource-check only on a provisioned host."
        )
    print(
        "live-scale resource guard passed: "
        f"measured_nodes={nodes}, geth_containers={geth_count}, "
        f"estimated={estimated} MiB, required_with_safety={required} MiB, available={available} MiB"
    )


def build_emulator(nodes: int, account_count: int, layout: str):
    asns = [SINGLE_ASN] if layout == "single-as" else SCALE_ASNS
    hosts_per_as = max(3, ((nodes + 1) + len(asns) - 1) // len(asns) + 1)
    emu = make_stub_internet(
        hosts_per_as=hosts_per_as,
        asns=asns,
        transit_asn=TRANSIT_ASN,
        ix=BASE_IX,
    )
    set_default_host_ip_ranges(emu, asns=asns, start=10, end=180)
    eth = EthereumService(saveState=False, override=True)
    chain = eth.createBlockchain(chainName="toposhot-scale", consensus=ConsensusMechanism.POA, chainId=CHAIN_ID)
    chain.addLocalAccountsFromMnemonic(
        mnemonic=MNEMONIC,
        total=account_count,
        balance=1000000,
    )

    vnode_names = []

    miner = chain.createNode("toposhot-scale-miner")
    miner.setCustomGeth(str(CUSTOM_GETH))
    miner.enableGethHttp()
    miner.setNoDiscover(True)
    miner.setBootNode(True)
    miner.unlockAccounts()
    miner.startMiner()
    miner.appendClassName("TopoShot-Scale-Geth")
    emu.getVirtualNode("toposhot-scale-miner").setDisplayName("TopoShot-Scale-Miner")
    vnode_names.append("toposhot-scale-miner")

    for index in range(nodes):
        vnode = f"toposhot-scale-n{index:03d}"
        node = chain.createNode(vnode)
        node.setCustomGeth(str(CUSTOM_GETH))
        node.enableGethHttp()
        node.setNoDiscover(True)
        node.appendClassName("TopoShot-Scale-Geth")
        emu.getVirtualNode(vnode).setDisplayName(f"TopoShot-Scale-N{index:03d}")
        vnode_names.append(vnode)

    eth.addDependency("EtcHosts", False, False)
    emu.addLayer(eth)
    bind_virtual_nodes_round_robin(emu, vnode_names, asns=asns)
    emu.addLayer(EtcHosts())
    return emu


def manifest(nodes: int, account_count: int, layout: str) -> dict:
    asns = [SINGLE_ASN] if layout == "single-as" else SCALE_ASNS
    return {
        "experiment": "toposhot_runtime_scale_probe",
        "reference": "TopoShot: Uncovering Ethereum's Network Topology Leveraging Replacement Transactions",
        "reference_url": "https://doi.org/10.1145/3487552.3487814",
        "pdf_url": "https://tristartom.github.io/docs/imc21-toposhot.pdf",
        "chain_id": CHAIN_ID,
        "mnemonic": MNEMONIC,
        "measured_nodes": nodes,
        "account_count": account_count,
        "consensus": "POA",
        "geth": {
            "version": "1.10.18-stable",
            "source": str(CUSTOM_GETH.relative_to(REPO_ROOT)),
            "reason": "TopoShot relies on pre-merge Geth transaction replacement and txpool propagation behavior.",
        },
        "topology": {
            "layout": layout,
            "stub_asns": asns,
            "transit_asn": TRANSIT_ASN,
            "base_ix": BASE_IX,
        },
        "runtime_driver": "measure.py",
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Build a medium-scale live SEED/Geth scenario for TopoShot group probing.")
    parser.add_argument("--nodes", type=int, default=12)
    parser.add_argument("--accounts", type=int, default=2000)
    parser.add_argument("--output", default=str(SCRIPT_DIR / "output"))
    parser.add_argument("--manifest", default=str(SCRIPT_DIR / "results" / "runtime_scale_manifest.json"))
    parser.add_argument("--layout", choices=["single-as", "multi-as"], default="single-as")
    parser.add_argument("--dumpfile")
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--skip-resource-check", action="store_true")
    parser.add_argument("--memory-per-geth-mib", type=int, default=DEFAULT_GETH_MEMORY_MIB)
    parser.add_argument("--memory-safety-factor", type=float, default=DEFAULT_MEMORY_SAFETY_FACTOR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.nodes < 4:
        raise SystemExit("--nodes must be >= 4")
    min_accounts = 10 + args.nodes * (args.nodes - 1) // 2
    if args.accounts < min_accounts:
        raise SystemExit(f"--accounts must be at least {min_accounts} for one full group probe")
    if args.compile and not args.skip_resource_check:
        enforce_resource_guard(args.nodes, args.memory_per_geth_mib, args.memory_safety_factor)

    emu = build_emulator(args.nodes, args.accounts, args.layout)
    write_json(args.manifest, manifest(args.nodes, args.accounts, args.layout))
    if args.dumpfile:
        emu.dump(args.dumpfile)
    if args.compile:
        emu.render()
        output_dir = Path(args.output).resolve()
        ChainSeedDocker(internetMapEnabled=False, platform=Platform.AMD64).compile(emu, str(output_dir), override=True)
    print(f"wrote {args.manifest}")
    if args.compile:
        print(f"compiled {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
