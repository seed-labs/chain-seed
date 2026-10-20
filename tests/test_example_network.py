"""Check reusable network definitions and unrendered network dump round trips."""

import os
from pathlib import Path
import tempfile
import unittest

from seedemu.core import Emulator
from examples.ethereum.E00_ethereum_poa import mini_internet, ethereum_poa


class ExampleNetworkTests(unittest.TestCase):
    def test_mini_and_hybrid_topologies(self):
        mini = mini_internet.build_emulator(hosts_per_as=1)
        self.assertFalse(mini.rendered())
        mini.getLayer("Base").getAutonomousSystem(164).getHost("host_0")
        hybrid = mini_internet.build_emulator(hosts_per_as=1, topology="hybrid")
        for asn in (170, 171, 11872, 99999):
            hybrid.getLayer("Base").getAutonomousSystem(asn)
        self.assertNotIn("EthereumService", [layer.getName() for layer in hybrid.getLayers()])

    def test_network_dump_can_be_reused_for_a_chain(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                network = Path(directory, "network.bin")
                mini_internet.run(network, hosts_per_as=1, topology="hybrid")
                restored = Emulator()
                restored.load(str(network))
                self.assertFalse(restored.rendered())
                restored.getLayer("Base").getAutonomousSystem(171)
                ethereum_poa.run(
                    dumpfile="chain.bin", total_eth_nodes=7,
                    total_accounts_per_node=1, network_dumpfile=network,
                )
                chain = Emulator()
                chain.load(str(Path(directory, "chain.bin")))
                chain.render()
                self.assertTrue(chain.rendered())
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
