#!/usr/bin/env python3
# encoding: utf-8

from __future__ import annotations

import argparse
import importlib
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from seedemu import *
from chainseed.compiler import ChainSeedDocker
from chainseed.ethereum import *
from examples.ethereum.E01_ethereum_pos import ethereum_pos


def make_post_genesis_deposits_practical() -> None:
    # E09 submits deposits after genesis; the mainnet follow distance would make
    # a local devnet wait for hours before the beacon chain processes them.
    ethereum_server = importlib.import_module("chainseed.ethereum.EthereumServer")

    ethereum_server.BEACON_GENESIS = ethereum_server.BEACON_GENESIS.replace(
        "ETH1_FOLLOW_DISTANCE: 2048",
        "ETH1_FOLLOW_DISTANCE: 1\nEPOCHS_PER_ETH1_VOTING_PERIOD: 1",
    )
    if "--eth1-cache-follow-distance" not in ethereum_server.LIGHTHOUSE_BN_CMD:
        ethereum_server.LIGHTHOUSE_BN_CMD = ethereum_server.LIGHTHOUSE_BN_CMD.replace(
            " --execution-jwt /tmp/jwt.hex  {bootnodes_flag}",
            " --execution-jwt /tmp/jwt.hex --eth1-cache-follow-distance 1 --eth1-blocks-per-log-query 1  {bootnodes_flag}",
        )


@contextmanager
def pushd(directory: Path):
    previous = Path.cwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(previous)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the E09 validator-at-running example.")
    parser.add_argument("legacy_platform", nargs="?", choices=["amd", "arm"])
    parser.add_argument("--platform", choices=["amd", "arm"])
    parser.add_argument("--output", default=str(SCRIPT_DIR / "output"))
    parser.add_argument("--dumpfile")
    parser.add_argument(
        "--beacon-nodes",
        type=int,
        default=3,
        help="number of geth/beacon node pairs inherited from E01",
    )
    parser.add_argument(
        "--validators-per-beacon",
        type=int,
        default=3,
        help="genesis validator clients per beacon node inherited from E01",
    )
    parser.add_argument(
        "--eth-explorer",
        "--ether-view",
        dest="ether_view_enabled",
        action="store_true",
        default=True,
        help="enable ChainSeed EthExplorer (default)",
    )
    parser.add_argument(
        "--no-eth-explorer",
        "--no-ether-view",
        dest="ether_view_enabled",
        action="store_false",
        help="disable ChainSeed EthExplorer; useful for CI builds",
    )
    parser.add_argument("--override", dest="override", action="store_true", default=True)
    parser.add_argument("--no-override", dest="override", action="store_false")
    parser.add_argument("--skip-render", dest="render", action="store_false", default=True)
    args = parser.parse_args()
    args.platform = args.platform or args.legacy_platform or "amd"
    if args.beacon_nodes < 1:
        parser.error("--beacon-nodes must be >= 1")
    if args.validators_per_beacon < 1:
        parser.error("--validators-per-beacon must be >= 1")
    return args


def resolve_platform(name: str) -> Platform:
    return Platform.AMD64 if name == "amd" else Platform.ARM64


def load_base_pos(total_beacon_nodes: int, vc_per_beacon: int) -> Emulator:
    emu = Emulator()
    with tempfile.TemporaryDirectory(prefix="seedemu-e09-") as tempdir:
        temp_path = Path(tempdir)
        dump_path = temp_path / "blockchain_pos.bin"
        with pushd(temp_path):
            ethereum_pos.run(
                dumpfile=str(dump_path),
                total_beacon_nodes=total_beacon_nodes,
                vc_per_beacon=vc_per_beacon,
            )
        emu.load(str(dump_path))
    return emu


def build_emulator(total_beacon_nodes: int = 3, vc_per_beacon: int = 3) -> Emulator:
    emu = load_base_pos(total_beacon_nodes=total_beacon_nodes, vc_per_beacon=vc_per_beacon)

    eth = emu.getLayer("EthereumService")
    blockchain = eth.getBlockchainByName(eth.getBlockchainNames()[0])

    vc_at_running: PoSVcServer = blockchain.createVcNode("vcnodeAtRunning")
    vc_at_running.appendClassName("Ethereum-POS-Validator-AtRunning")
    vc_at_running.setDisplayName("Ethereum-POS-Validator-AtRunning-1")
    vc_at_running.connectToBeaconNode("beaconnode0")
    vc_at_running.enablePOSValidatorAtRunning()
    emu.getVirtualNode("vcnodeAtRunning").setDisplayName("Ethereum-POS-Validator-AtRunning-1")

    emu.addBinding(Binding("vcnodeAtRunning", filter=Filter(nodeName="host_*"), action=Action.FIRST))
    return emu


def run(
    dumpfile=None,
    total_beacon_nodes: int = 3,
    vc_per_beacon: int = 3,
    output=None,
    platform=Platform.AMD64,
    override: bool = True,
    render: bool = True,
    ether_view_enabled: bool = True,
):
    make_post_genesis_deposits_practical()
    emu = build_emulator(total_beacon_nodes=total_beacon_nodes, vc_per_beacon=vc_per_beacon)
    if dumpfile is not None:
        emu.dump(dumpfile)
        return

    if render:
        emu.render()

    output_dir = Path(output or SCRIPT_DIR / "output").resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    docker = ChainSeedDocker(internetMapEnabled=True, platform=platform)
    if ether_view_enabled:
        docker.enableEthExplorer(chain_name="pos")

    emu.compile(docker, str(output_dir), override=override)


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
        ether_view_enabled=args.ether_view_enabled,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
