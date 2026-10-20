#!/usr/bin/env python3
# encoding: utf-8

from __future__ import annotations

import argparse
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from seedemu import Platform
from examples.ethereum.E01_ethereum_pos import ethereum_pos as e01_ethereum_pos


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the E04 Ethereum PoS EthExplorer example.")
    parser.add_argument(
        "legacy_args",
        nargs="*",
        help="legacy form: <beacon_node_count> [amd|arm]",
    )
    parser.add_argument("--platform", choices=["amd", "arm"])
    parser.add_argument("--output", default=str(SCRIPT_DIR / "output"))
    parser.add_argument("--dumpfile")
    parser.add_argument("--explorer-geth", help="Geth virtual node for EthExplorer (for example gethnode1)")
    parser.add_argument("--explorer-beacon", help="Beacon virtual node for EthExplorer (for example beaconnode1)")
    parser.add_argument(
        "--beacon-nodes",
        type=int,
        default=3,
        help="number of geth/beacon node pairs",
    )
    parser.add_argument(
        "--validators-per-beacon",
        type=int,
        default=3,
        help="validator clients per beacon node",
    )
    parser.add_argument("--override", dest="override", action="store_true", default=True)
    parser.add_argument("--no-override", dest="override", action="store_false")
    parser.add_argument("--skip-render", dest="render", action="store_false", default=True)
    args = parser.parse_args()

    if len(args.legacy_args) > 2:
        parser.error("legacy arguments must be: <beacon_node_count> [amd|arm]")

    legacy_platform = None
    if args.legacy_args:
        first = args.legacy_args[0].lower()
        if first in ("amd", "arm"):
            legacy_platform = first
        else:
            try:
                args.beacon_nodes = int(first)
            except ValueError:
                parser.error("legacy beacon node count must be an integer")

    if len(args.legacy_args) == 2:
        legacy_platform = args.legacy_args[1].lower()
        if legacy_platform not in ("amd", "arm"):
            parser.error("legacy platform must be amd or arm")

    args.platform = args.platform or legacy_platform or "amd"
    if args.beacon_nodes < 1:
        parser.error("--beacon-nodes must be >= 1")
    if args.validators_per_beacon < 1:
        parser.error("--validators-per-beacon must be >= 1")
    return args


def resolve_platform(name: str) -> Platform:
    return Platform.AMD64 if name == "amd" else Platform.ARM64


def run(
    dumpfile=None,
    total_beacon_nodes: int = 3,
    vc_per_beacon: int = 3,
    output=None,
    platform=Platform.AMD64,
    override: bool = True,
    render: bool = True,
    explorer_geth_vnode: str | None = None,
    explorer_beacon_vnode: str | None = None,
):
    e01_ethereum_pos.run(
        dumpfile=dumpfile,
        total_beacon_nodes=total_beacon_nodes,
        vc_per_beacon=vc_per_beacon,
        output=output,
        platform=platform,
        override=override,
        render=render,
        ether_view_enabled=True,
        explorer_geth_vnode=explorer_geth_vnode,
        explorer_beacon_vnode=explorer_beacon_vnode,
    )


def main() -> int:
    args = parse_args()
    run(
        dumpfile=args.dumpfile,
        total_beacon_nodes=args.beacon_nodes,
        vc_per_beacon=args.validators_per_beacon,
        output=str(Path(args.output).resolve()),
        platform=resolve_platform(args.platform),
        override=args.override,
        render=args.render,
        explorer_geth_vnode=args.explorer_geth,
        explorer_beacon_vnode=args.explorer_beacon,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
