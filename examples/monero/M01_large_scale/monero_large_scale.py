#!/usr/bin/env python3
"""Compile a Monero network with six seeds and one bootstrap miner."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(REPO_ROOT))

import mini_internet
from seedemu import Binding, Emulator, Filter
from seedemu.compiler import BASE_IMAGE, DockerImage, Platform
from chainseed import ChainSeedDocker
from chainseed.monero import (MoneroMiningTrigger, MoneroSeedConnectionMode,
                             MoneroService)
from tools.blockchain.lib.runtime_mounts import patch_output

DEFAULT_IMAGE = "handsonsecurity/seedemu-monero:latest"
SEED_COUNT = 6
BOOTSTRAP_MINER = SEED_COUNT


def plan_nodes(nodes: int, stub_as_count: int | None = None) -> list[dict]:
    if nodes < SEED_COUNT + 2:
        raise ValueError("At least 8 nodes are required: six seeds, one miner and one full node")
    counts = mini_internet.host_counts(nodes, stub_as_count)
    asns = list(counts)
    return [dict(index=i, asn=asns[i % len(asns)], host=f"host_{i // len(asns)}",
                 ip=f"10.{asns[i % len(asns)]}.0.{71 + i // len(asns)}",
                 role="seed" if i < SEED_COUNT else "miner" if i == BOOTSTRAP_MINER else "full",
                 rpc_port=28081) for i in range(nodes)]


def add_monero_layer(emu: Emulator, records: list[dict], image: str,
                     tx_wallets: int = 0) -> list[dict]:
    """Configure the initial deployment; later tools control additional miners."""
    if tx_wallets < 0 or tx_wallets == 1 or tx_wallets > len(records) - SEED_COUNT - 1:
        raise ValueError("tx_wallets must be 0 or between 2 and nodes - 7")
    base = emu.getLayer("Base")
    for record in records:
        base.getAutonomousSystem(record["asn"]).getHost(record["host"])
    service = MoneroService()
    chain = service.createBlockchain("final-monero")
    chain.setCustomBaseImage(image)
    chain.setDefaultLogLevel(0)
    chain.setSeedConnectionMode(MoneroSeedConnectionMode.SEED)
    rpc_password = secrets.token_hex(24)
    wallets = []
    for record in records:
        index, role = record["index"], record["role"]
        vnode = f"monero-{index}"
        create = chain.createSeedNode if role == "seed" else chain.createClientNode
        node = create(vnode)
        node.setWaitForSeed(False).setPersistData(False)
        node.setExtraDaemonArgs(
            ["--max-log-file-size=10485760", "--max-log-files=2"]
        )
        if index == BOOTSTRAP_MINER:
            node.enableMining(threads=1, trigger=MoneroMiningTrigger.AFTER_SEED_REACHABLE)
        else:
            node.disableWallet()
        if tx_wallets and (index == BOOTSTRAP_MINER or index >= len(records) - tx_wallets):
            node.enableWalletRpc(user="d61tx", password=rpc_password,
                bind_ip="0.0.0.0", bind_port=28083, allow_external=True)
            wallets.append(dict(index=index, role="funder" if index == BOOTSTRAP_MINER else "sender",
                url=f'http://{record["ip"]}:28083/json_rpc', user="d61tx", password=rpc_password))
        node.setDisplayName(f"Monero-{role}-{index:04d}")
        emu.addBinding(Binding(vnode, filter=Filter(asn=record["asn"], nodeName=f'^{record["host"]}$')))
    emu.addLayer(service)
    return wallets


def compile_network(output: Path, nodes: int = 1200, stub_as_count: int | None = None,
                    image: str = DEFAULT_IMAGE, tx_wallets: int = 0,
                    network: Path | None = None, dry_run: bool = False) -> dict:
    records = plan_nodes(nodes, stub_as_count)
    if tx_wallets < 0 or tx_wallets == 1 or tx_wallets > nodes - SEED_COUNT - 1:
        raise ValueError("tx_wallets must be 0 or between 2 and nodes - 7")
    config = dict(nodes=nodes, stub_as_count=len({r["asn"] for r in records}),
        seeds=SEED_COUNT, initial_miners=1, bootstrap_miner_index=BOOTSTRAP_MINER,
        mining_threads=1, fixed_difficulty=None, tx_wallets=tx_wallets,
        image=image, network=str(network.resolve()) if network else None)
    if dry_run:
        print(json.dumps(config, indent=2))
        return config
    output = output.resolve()
    if output.exists():
        raise ValueError(f"Output exists: {output}; choose a new directory")
    if network:
        emu = Emulator().load(str(network.resolve()))
        if {layer.getName() for layer in emu.getLayers()} != {"Base", "Routing", "Ebgp", "Ibgp", "Ospf"}:
            raise ValueError("Load an unrendered network containing only the five network layers")
    else:
        emu = mini_internet.build_emulator(nodes, stub_as_count)
    wallets = add_monero_layer(emu, records, image, tx_wallets)
    emu.render()
    base = emu.getLayer("Base")
    for record in records:
        host = base.getAutonomousSystem(record["asn"]).getHost(record["host"])
        if str(host.getInterfaces()[0].getAddress()) != record["ip"]:
            raise ValueError(f'Network address differs from the deployment plan for monero-{record["index"]}')
    output.parent.mkdir(parents=True, exist_ok=True)
    compiler = ChainSeedDocker(internetMapEnabled=False, platform=Platform.AMD64)
    # The shared Monero image extends the SeedEmu base and contains its tools.
    if image not in {candidate.getName() for candidate, _ in compiler.getImages()}:
        compiler.addImage(DockerImage(name=image, software=[], subset=BASE_IMAGE))
    emu.compile(compiler, str(output), override=False)
    compose = output / "docker-compose.yml"
    patch_output(output, compose, "/seedemu-node", 524288, False, False)
    # Bound daemon and container logs, as in the imported large-scale run.
    payload = yaml.safe_load(compose.read_text())
    for service in payload["services"].values():
        service["logging"] = dict(driver="json-file", options={"max-size": "10m", "max-file": "2"})
    compose.write_text(yaml.safe_dump(payload, sort_keys=False))
    (output / "nodes.json").write_text(json.dumps(records, indent=2) + "\n")
    (output / "deployment.json").write_text(json.dumps(config, indent=2) + "\n")
    if wallets:
        with open(output / "wallets.json", "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
            json.dump(wallets, handle, indent=2)
            handle.write("\n")
    print(f"Runnable output: {output} ({nodes} Monero nodes, six seeds, one initial miner)")
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=1200)
    parser.add_argument("--stub-as-count", type=int, help="Default: min(100, nodes)")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Compatible Monero base image (default: %(default)s)")
    parser.add_argument("--tx-wallets", type=int, default=0, help="Sender wallets, in addition to the bootstrap funding wallet")
    parser.add_argument("--network", type=Path, help="Unrendered network.bin generated by mini_internet.py")
    parser.add_argument("--output", type=Path, default=SCRIPT_DIR / "output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compile_network(args.output, args.nodes, args.stub_as_count, args.image,
                    args.tx_wallets, args.network, args.dry_run)


if __name__ == "__main__":
    main()
