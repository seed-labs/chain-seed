#!/usr/bin/env python3
"""Run the E01 PoS network with a global Ethereum Lookingglass Server."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from seedemu.compiler import Platform
from seedemu.core import Action, Binding, Filter
from chainseed import ChainSeedDocker
from chainseed.services.ethereum import PoSBeaconServer
from examples.ethereum.E01_ethereum_pos import ethereum_pos as e01


def build_emulator():
    emu = e01.build_emulator()
    ethereum = emu.getLayer("EthereumService")

    # The viewer uses its defaults. Client APIs remain explicit client settings.
    for server in ethereum.getPendingTargets().values():
        if isinstance(server, PoSBeaconServer):
            server.enableMetrics()

    ethereum.createLookingglassServer()
    system = emu.getLayer("Base").getAutonomousSystem(150)
    system.createHost("lookingglass").joinNetwork("net0")
    emu.addBinding(Binding(
        "lookingglass", action=Action.FIRST,
        filter=Filter(asn=150, nodeName="^lookingglass$"),
    ))
    return emu


def run(output=None, platform=Platform.AMD64, override=False):
    emu = build_emulator()
    emu.render()
    output = Path(output or SCRIPT_DIR / "output").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    emu.compile(ChainSeedDocker(platform=platform, internetMapEnabled=True),
                str(output), override=override)
    return emu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("amd", "arm"), default="amd")
    parser.add_argument("--output", type=Path, default=SCRIPT_DIR / "output")
    parser.add_argument("--override", action="store_true")
    args = parser.parse_args()
    run(args.output, Platform.AMD64 if args.platform == "amd" else Platform.ARM64,
        override=args.override)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
