#!/usr/bin/env python3
# encoding: utf-8

"""SolanaService example: a private, self-contained Solana cluster.

Topology: a small Internet (10 stub ASes) on top of which we deploy a private
Agave/Solana cluster consisting of one bootstrap (genesis) validator and nine
joining validators distributed across the stub Autonomous Systems.

This mirrors the structure of the Monero example (M00_monero): build the base
Internet with Makers, attach a blockchain service, bind its virtual nodes to
hosts, render, and compile to Docker.

The cluster runs natively on both amd64 and arm64: the seedemu-solana base image
downloads Agave's prebuilt binaries on amd64 and compiles them from source on
arm64. Build the base image once before compiling:

    docker build -t seedemu-solana ../../../docker_images/solana
"""

from __future__ import annotations

import platform as _platform
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
EXAMPLE_DIR = SCRIPT_PATH.parent
REPO_ROOT = SCRIPT_PATH.parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.ethereum.E00_ethereum_poa import mini_internet

from seedemu import Binding, Filter, Makers
from seedemu.compiler import Platform
from chainseed.compiler import ChainSeedDocker
from chainseed.services.solana import SolanaService


def _bind(emu, vnode: str, asn: int, host_index: int, display_name: str) -> None:
    """Bind a Solana virtual node to host_<host_index> and name the host."""
    emu.getLayer('Base').getAutonomousSystem(asn).getHost(
        f"host_{host_index}"
    ).setDisplayName(display_name)
    emu.addBinding(Binding(vnode, filter=Filter(asn=asn, nodeName=f"^host_{host_index}$")))


###############################################################################
# Select the platform. With no argument we detect the host architecture; the
# seedemu-solana image is built natively per-arch (prebuilt on amd64, compiled
# from source on arm64), so both are first-class.
script_name = SCRIPT_PATH.name


def _detect_platform() -> Platform:
    machine = _platform.machine().lower()
    return Platform.ARM64 if machine in ('arm64', 'aarch64') else Platform.AMD64


if len(sys.argv) == 1:
    platform = _detect_platform()
elif len(sys.argv) == 2:
    arg = sys.argv[1].lower()
    if arg == 'amd':
        platform = Platform.AMD64
    elif arg == 'arm':
        platform = Platform.ARM64
    else:
        print(f"Usage:  {script_name} [amd|arm]   (default: host architecture)")
        sys.exit(1)
else:
    print(f"Usage:  {script_name} [amd|arm]   (default: host architecture)")
    sys.exit(1)

###############################################################################
# Build the base topology: 10 stub ASes, each with 2 hosts.
hosts_per_stub_as = 2
emu = mini_internet.build_emulator(hosts_per_as=hosts_per_stub_as)

###############################################################################
# Create a private Solana cluster.
solana = SolanaService()
blockchain = solana.createBlockchain("seed-solana")

# AS150 / host_0: the bootstrap (genesis) validator. It builds the genesis
# ledger, runs the faucet, and is the gossip entrypoint for the rest of the
# cluster.
boot = blockchain.createBootstrapValidator("sol-boot-150")
boot.setDisplayName("Solana-Bootstrap-150")
_bind(emu, "sol-boot-150", asn=150, host_index=0, display_name="Solana-Bootstrap-150")

# Nine joining validators. AS150/host_1 is on-link with the bootstrap; the rest
# join over inter-domain (BGP) routing, demonstrating a larger private Solana
# cluster spread across the emulated Internet.
validator_bindings = [
    ("sol-validator-150b", "Solana-Validator-150b", 150, 1),
    ("sol-validator-151", "Solana-Validator-151", 151, 0),
    ("sol-validator-152", "Solana-Validator-152", 152, 0),
    ("sol-validator-153", "Solana-Validator-153", 153, 0),
    ("sol-validator-154", "Solana-Validator-154", 154, 0),
    ("sol-validator-160", "Solana-Validator-160", 160, 0),
    ("sol-validator-161", "Solana-Validator-161", 161, 0),
    ("sol-validator-162", "Solana-Validator-162", 162, 0),
    ("sol-validator-163", "Solana-Validator-163", 163, 0),
]

for vnode, display_name, asn, host_index in validator_bindings:
    validator = blockchain.createValidator(vnode)
    validator.setDisplayName(display_name)
    _bind(emu, vnode, asn=asn, host_index=host_index, display_name=display_name)

###############################################################################
# Add the Solana service as a layer, then render.
emu.addLayer(solana)
emu.render()

###############################################################################
# Compile docker-compose and the build context into ./output.
docker = ChainSeedDocker(internetMapEnabled=True, platform=platform)
emu.compile(docker, str(EXAMPLE_DIR / "output"), override=True)
