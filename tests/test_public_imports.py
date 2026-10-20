import unittest


class PublicImportTests(unittest.TestCase):
    def test_extension_descriptor(self):
        from chainseed import ChainSeedDocker, descriptor

        self.assertEqual(descriptor.distribution, "chainseed")
        self.assertEqual(descriptor.extension_api_version, 1)
        self.assertEqual(ChainSeedDocker().getName(), "ChainSeedDocker")

    def test_chain_public_imports(self):
        from chainseed.services.chainlink import ChainlinkService
        from chainseed.services.ethereum import ConsensusMechanism, EthereumService
        from chainseed.visualization import EthExplorer
        from seedemu.containerBundle import ContainerBundle

        self.assertTrue(issubclass(EthExplorer, ContainerBundle))
        from chainseed.services.monero import MoneroService
        from chainseed.services.solana import SolanaService

        self.assertEqual(ConsensusMechanism.POS.value, "POS")
        self.assertTrue(
            all(
                service is not None
                for service in (
                    EthereumService,
                    EthExplorer,
                    MoneroService,
                    SolanaService,
                    ChainlinkService,
                )
            )
        )

    def test_chainseed_docker_system_mapping(self):
        from chainseed.common.systems import (
            CHAINLINK,
            CHAINSEED_SYSTEMS,
            ETHEREUM_LEGACY,
            ETHEREUM_POS,
        )
        from chainseed.compiler import ChainSeedDocker
        from chainseed.compiler.images import IMAGE_CATALOG
        from seedemu.compiler import Docker, Platform
        from seedemu.core import BaseSystem, Emulator, Node, SystemProfile
        from seedemu.core.enums import NodeRole

        pos_node = Node("pos", NodeRole.Host, 150)
        pos_node.setBaseSystem(ETHEREUM_POS)
        image, _ = ChainSeedDocker(platform=Platform.AMD64)._selectImageFor(pos_node)
        self.assertEqual(image.getName(), "handsonsecurity/seedemu-ethereum:pos2.0")

        self.assertEqual(
            ChainSeedDocker(Platform.ARM64).getName(),
            "ChainSeedDocker",
        )

        legacy_node = Node("legacy", NodeRole.Host, 151)
        legacy_node.setBaseSystem(ETHEREUM_LEGACY)
        image, _ = ChainSeedDocker(platform=Platform.ARM64)._selectImageFor(legacy_node)
        self.assertEqual(
            image.getName(),
            "handsonsecurity/seedemu-ethereum-arm64:legacy",
        )

        for platform in Platform:
            compiler = ChainSeedDocker(platform=platform)
            for index, system in enumerate(CHAINSEED_SYSTEMS):
                node = Node("mapped-{}".format(index), NodeRole.Host, 160 + index)
                node.setBaseSystem(system)
                image, _ = compiler._selectImageFor(node)
                self.assertEqual(
                    image.getName(), IMAGE_CATALOG[platform][system].getName()
                )

        forced = ChainSeedDocker(platform=Platform.AMD64)
        forced.forceImage("ubuntu:24.04")
        image, _ = forced._selectImageFor(pos_node)
        self.assertEqual(image.getName(), "ubuntu:24.04")

        self.assertIsInstance(ETHEREUM_POS, SystemProfile)
        self.assertTrue(ETHEREUM_POS.contains(BaseSystem.SEEDEMU_BASE))
        self.assertTrue(ETHEREUM_POS.contains(BaseSystem.UBUNTU_20_04))
        self.assertFalse(BaseSystem.SEEDEMU_BASE.contains(ETHEREUM_POS))
        self.assertFalse(CHAINLINK.contains(BaseSystem.UBUNTU_20_04))
        with self.assertRaises(TypeError):
            pos_node.setBaseSystem("chainseed.ethereum.pos")

        self.assertTrue(callable(Docker().addContainerBundle))
        self.assertFalse(hasattr(ChainSeedDocker, "enableEthExplorer"))
        self.assertFalse(hasattr(ChainSeedDocker, "addComponent"))
        self.assertFalse(hasattr(Docker(), "addComposeService"))
        self.assertFalse(hasattr(Docker(), "getComposeNetworkName"))

        with self.assertRaisesRegex(
            KeyError, "Docker does not support system profile chainseed.ethereum.pos"
        ):
            Docker(platform=Platform.AMD64)._selectImageFor(pos_node)

    def test_binding_profile_resolution(self):
        from chainseed.common.systems import ETHEREUM_POS, SOLANA
        from seedemu.core import (
            Action,
            BaseSystem,
            Binding,
            Emulator,
            Filter,
            Node,
            Server,
            Service,
            SystemProfile,
        )
        from seedemu.layers import Base

        class ProfileServer(Server):
            def install(self, node: Node):
                pass

        class ProfileService(Service):
            def __init__(self, name, profile):
                super().__init__()
                self._name = name
                self._profile = profile

            def getName(self):
                return self._name

            def _createServer(self):
                return ProfileServer().setBaseSystem(self._profile)

        def build(node_profile, server_profile):
            emulator = Emulator()
            base = Base()
            autonomous_system = base.createAutonomousSystem(1)
            autonomous_system.createNetwork("net0")
            host = autonomous_system.createHost("host").joinNetwork("net0")
            host.setBaseSystem(node_profile)
            service = ProfileService("ProfileService", server_profile)
            server = service.install("vnode")
            emulator.addLayer(base)
            emulator.addLayer(service)
            emulator.addBinding(
                Binding(
                    "vnode",
                    action=Action.FIRST,
                    filter=Filter(asn=1, nodeName="host"),
                )
            )
            return emulator, host, server

        emulator, host, server = build(BaseSystem.DEFAULT, ETHEREUM_POS)
        emulator.render()
        self.assertEqual(host.getBaseSystem(), ETHEREUM_POS)
        self.assertEqual(server.getBaseSystem(), ETHEREUM_POS)

        emulator, host, server = build(ETHEREUM_POS, BaseSystem.DEFAULT)
        emulator.render()
        self.assertEqual(host.getBaseSystem(), ETHEREUM_POS)
        self.assertEqual(server.getBaseSystem(), ETHEREUM_POS)

        enhanced_pos = SystemProfile(
            "test.ethereum.pos.tools", subset=ETHEREUM_POS
        )
        emulator, host, server = build(enhanced_pos, ETHEREUM_POS)
        emulator.render()
        self.assertEqual(host.getBaseSystem(), enhanced_pos)
        self.assertEqual(server.getBaseSystem(), enhanced_pos)

        emulator = Emulator()
        base = Base()
        autonomous_system = base.createAutonomousSystem(1)
        autonomous_system.createNetwork("net0")
        host = autonomous_system.createHost("host").joinNetwork("net0")
        special = ProfileService("Special", ETHEREUM_POS)
        special_server = special.install("special")
        generic = ProfileService("Generic", BaseSystem.DEFAULT)
        generic_server = generic.install("generic")
        emulator.addLayer(base)
        emulator.addLayer(special)
        emulator.addLayer(generic)
        shared = Filter(asn=1, nodeName="host", allowBound=True)
        emulator.addBinding(Binding("generic", action=Action.FIRST, filter=shared))
        emulator.addBinding(Binding("special", action=Action.FIRST, filter=shared))
        emulator.render()
        self.assertEqual(host.getBaseSystem(), ETHEREUM_POS)
        self.assertEqual(special_server.getBaseSystem(), ETHEREUM_POS)
        self.assertEqual(generic_server.getBaseSystem(), ETHEREUM_POS)

        emulator, _, _ = build(SOLANA, ETHEREUM_POS)
        with self.assertRaisesRegex(AssertionError, "failed to find binding"):
            emulator.render()

    def test_protocol_aware_test_runner_import(self):
        from chainseed.testing import BlockchainTestRunner, EthereumRuntimeTest

        self.assertEqual(BlockchainTestRunner.runner_name, "blockchain")
        self.assertIsNotNone(EthereumRuntimeTest)


if __name__ == "__main__":
    unittest.main()
