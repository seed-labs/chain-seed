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


CHAIN_ID = 202704
MNEMONIC = "gentle always fun glass foster produce north tail security list example gain"
CUSTOM_GETH = REPO_ROOT / "examples" / "ethereum" / "E09_blockchain" / "resources" / "custom_geth"
TOPOSHOT_ASNS = [240, 241, 242, 243, 244, 245]
TRANSIT_ASN = 3
BASE_IX = 140
ROLES = ["M", "A1", "A2", "B"]
ROLE_ASNS = {
    "M": 240,
    "A1": 241,
    # Avoid the third stub AS in this generated transit topology; like the
    # earlier routing experiment's AS202, this IX position can fail to propagate
    # routes reliably on the local Docker bridge backend.
    "A2": 244,
    "B": 243,
}


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


def build_emulator(account_count: int):
    emu = make_stub_internet(hosts_per_as=3, asns=TOPOSHOT_ASNS, transit_asn=TRANSIT_ASN, ix=BASE_IX)
    eth = EthereumService(saveState=False, override=True)
    chain = eth.createBlockchain(chainName="toposhot-runtime", consensus=ConsensusMechanism.POA, chainId=CHAIN_ID)
    chain.addLocalAccountsFromMnemonic(
        mnemonic=MNEMONIC,
        total=account_count,
        balance=1000000,
    )

    for i, role in enumerate(ROLES):
        vnode = f"toposhot-{role.lower()}"
        node = chain.createNode(vnode)
        node.setCustomGeth(str(CUSTOM_GETH))
        node.enableGethHttp()
        node.setNoDiscover(True)
        node.appendClassName("TopoShot-Runtime-Geth")
        if role == "M":
            node.setBootNode(True)
            node.unlockAccounts()
            node.startMiner()
        emu.getVirtualNode(vnode).setDisplayName(f"TopoShot-Runtime-{role}")

    eth.addDependency("EtcHosts", False, False)
    emu.addLayer(eth)
    bindings = {
        "toposhot-m": ROLE_ASNS["M"],
        "toposhot-a1": ROLE_ASNS["A1"],
        "toposhot-a2": ROLE_ASNS["A2"],
        "toposhot-b": ROLE_ASNS["B"],
    }
    for vnode, asn in bindings.items():
        emu.addBinding(Binding(vnode, filter=Filter(asn=asn, nodeName="host_*"), action=Action.FIRST))
    emu.addLayer(EtcHosts())
    return emu


def manifest(account_count: int):
    role_asns = dict(ROLE_ASNS)
    return {
        "experiment": "toposhot_runtime_parallel_validation",
        "reference": "TopoShot: Uncovering Ethereum's Network Topology Leveraging Replacement Transactions",
        "reference_url": "https://doi.org/10.1145/3487552.3487814",
        "pdf_url": "https://tristartom.github.io/docs/imc21-toposhot.pdf",
        "description": "Local parallel topology probing with replacement transactions",
        "chain_id": CHAIN_ID,
        "mnemonic": MNEMONIC,
        "account_count": account_count,
        "roles": ROLES,
        "consensus": "POA",
        "geth": {
            "version": "1.10.18-stable",
            "source": str(CUSTOM_GETH.relative_to(REPO_ROOT)),
            "reason": "Pre-merge Geth provides the transaction gossip and replacement behavior used by this example.",
        },
        "role_asns": role_asns,
        "role_ips": {role: f"10.{asn}.0.71" for role, asn in role_asns.items()},
        "topology": {
            "transit_asn": TRANSIT_ASN,
            "stub_asns": TOPOSHOT_ASNS,
            "base_ix": BASE_IX,
        },
        "runtime_driver": "measure.py",
        "measurement_idea": (
            "The runtime driver creates each reference overlay with admin_addPeer, "
            "then checks candidate edges using TopoShot's replacement-price isolation pattern: "
            "95% gas-price txB at the sink, 100% txC at blockers, and 105% txA at the source."
        ),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Build a SEED/Geth runtime scenario for TopoShot local parallel validation.")
    parser.add_argument("--accounts", type=int, default=2200)
    parser.add_argument("--output", default=str(SCRIPT_DIR / "output"))
    parser.add_argument("--manifest", default=str(SCRIPT_DIR / "results" / "runtime_scenario_manifest.json"))
    parser.add_argument("--dumpfile")
    parser.add_argument("--compile", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.accounts < 64:
        raise SystemExit("--accounts must be at least 64")
    emu = build_emulator(args.accounts)
    write_json(args.manifest, manifest(args.accounts))
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
