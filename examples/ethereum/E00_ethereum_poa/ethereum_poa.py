#!/usr/bin/env python3
# encoding: utf-8

from __future__ import annotations

import os
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chainseed.compiler import ChainSeedDocker
from seedemu import *
from examples.ethereum.E00_ethereum_poa import mini_internet
from chainseed.ethereum import *
from examples.ethereum.E00_ethereum_poa import component_poa

def run(dumpfile=None, hosts_per_as=3, total_eth_nodes=20, total_accounts_per_node=2, network_dumpfile=None):
    ###############################################################################
    # Set the platform information
    if dumpfile is None:
        script_name = os.path.basename(__file__)

        if len(sys.argv) == 1:
            platform = Platform.AMD64
        elif len(sys.argv) == 2:
            if sys.argv[1].lower() == 'amd':
                platform = Platform.AMD64
            elif sys.argv[1].lower() == 'arm':
                platform = Platform.ARM64
            else:
                print(f"Usage:  {script_name} amd|arm")
                sys.exit(1)
        else:
            print(f"Usage:  {script_name} amd|arm")
            sys.exit(1)
            
    # Run and load the pre-built Internet component
    if network_dumpfile is None:
        emuA = mini_internet.build_emulator(hosts_per_as=hosts_per_as, topology="hybrid")
    else:
        emuA = Emulator()
        emuA.load(str(Path(network_dumpfile).resolve()))

    # Run and load the pre-built Ethereum component
    emuB = Emulator()
    component_poa.run(dumpfile='./component_poa.bin', 
                      total_eth_nodes=total_eth_nodes, 
                      total_accounts_per_node=total_accounts_per_node)
    emuB.load('./component_poa.bin')

    # Merge the two pre-built components
    emu = emuA.merge(emuB, DEFAULT_MERGERS)

    # Binding all the virtual nodes to physical nodes
    eth:EthereumService = emu.getLayer('EthereumService')
    blockchain: Blockchain =  eth.getBlockchainByName(eth.getBlockchainNames()[0])
    for _, servers in blockchain.getAllServerNames().items():
        for server in servers:
            # Bind to the physical nodes starting with "host_" 
            emu.addBinding(Binding(server, filter = Filter(nodeName="host_*"),
                           action = Action.FIRST))

    # Add this layer to set the /etc/hosts file on all the nodes
    emu.addLayer(EtcHosts())  

    # Generate output
    if dumpfile is not None:
        emu.dump(dumpfile)
    else:
        emu.render()
        docker = ChainSeedDocker(platform=platform)
        emu.compile(docker, './output', override=True)

if __name__ == "__main__":
    run()
