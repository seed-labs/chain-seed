import unittest


class PublicImportTests(unittest.TestCase):
    def test_extension_descriptor(self):
        from chainseed import descriptor
        from seedemu.compiler import Docker

        self.assertEqual(descriptor.distribution, "chainseed")
        self.assertEqual(descriptor.extension_api_version, 1)
        self.assertEqual(Docker().getName(), "Docker")

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

    def test_service_docker_system_mapping(self):
        from chainseed.common.systems import (
            CHAINLINK, CHAINSEED_SYSTEMS, ETHEREUM_LEGACY, ETHEREUM_POS,
        )
        from chainseed.services.ethereum import EthereumService
        from chainseed.services.monero import MoneroService
        from chainseed.services.solana import SolanaService
        from chainseed.services.chainlink import ChainlinkService
        from seedemu.compiler import Docker, Platform
        from seedemu.core import BaseSystem, Emulator, Node, SystemProfile
        from seedemu.core.enums import NodeRole

        emulator = Emulator()
        services = [EthereumService(), MoneroService(), SolanaService(), ChainlinkService()]
        for service in services:
            emulator.addLayer(service)
        for platform in Platform:
            compiler = Docker(platform=platform)
            compiler._collectServiceImages(emulator)
            expected = {}
            for service in services:
                expected.update(service.getDockerImages(platform))
            for index, system in enumerate(CHAINSEED_SYSTEMS):
                node = Node("mapped-{}".format(index), NodeRole.Host, 160 + index)
                node.setBaseSystem(system)
                image, _ = compiler._selectImageFor(node)
                self.assertEqual(image.getName(), expected[system].getName())
            legacy = Node("legacy", NodeRole.Host, 151).setBaseSystem(ETHEREUM_LEGACY)
            image, _ = compiler._selectImageFor(legacy)
            self.assertEqual(image.getName(), "handsonsecurity/seedemu-ethereum{}:legacy".format(
                "-arm64" if platform == Platform.ARM64 else ""))

        pos = Node("pos", NodeRole.Host, 150).setBaseSystem(ETHEREUM_POS)
        compiler = Docker(platform=Platform.AMD64)
        compiler._collectServiceImages(emulator)
        compiler.forceImage("ubuntu:24.04")
        self.assertEqual(compiler._selectImageFor(pos)[0].getName(), "ubuntu:24.04")
        compiler.forceImage(None)
        compiler.setImageOverride(pos, "ubuntu:24.04")
        self.assertEqual(compiler._selectImageFor(pos)[0].getName(), "ubuntu:24.04")

        self.assertIsInstance(ETHEREUM_POS, SystemProfile)
        self.assertTrue(ETHEREUM_POS.contains(BaseSystem.SEEDEMU_BASE))
        self.assertTrue(ETHEREUM_POS.contains(BaseSystem.UBUNTU_20_04))
        self.assertFalse(BaseSystem.SEEDEMU_BASE.contains(ETHEREUM_POS))
        self.assertFalse(CHAINLINK.contains(BaseSystem.UBUNTU_20_04))
        with self.assertRaises(TypeError):
            pos.setBaseSystem("chainseed.ethereum.pos")
        with self.assertRaisesRegex(KeyError, "does not support system profile chainseed.ethereum.pos"):
            Docker()._selectImageFor(pos)

    def test_service_image_defaults_and_instance_overrides(self):
        from seedemu.core import Service
        from seedemu.compiler import DockerImage, Platform
        from chainseed.common.systems import ETHEREUM_POS
        from chainseed.services.ethereum import EthereumService
        from chainseed.services.monero import MoneroService
        from chainseed.services.solana import SolanaService
        from chainseed.services.chainlink import ChainlinkService

        for service_type in (EthereumService, MoneroService, SolanaService, ChainlinkService):
            self.assertIs(service_type.getDockerImages, Service.getDockerImages)

        first, second = EthereumService(), EthereumService()
        defaults = first.getDockerImages(Platform.AMD64)
        defaults[ETHEREUM_POS].addSoftwares(["example-package"])
        defaults.clear()
        for service in (first, second):
            image = service.getDockerImages(Platform.AMD64)[ETHEREUM_POS]
            self.assertNotIn("example-package", image.getSoftware())
        override = DockerImage("example:pos", [])
        first.setDockerImage(ETHEREUM_POS, override, Platform.AMD64)
        self.assertIs(first.getDockerImages(Platform.AMD64)[ETHEREUM_POS], override)
        self.assertEqual(second.getDockerImages(Platform.AMD64)[ETHEREUM_POS].getName(),
                         "handsonsecurity/seedemu-ethereum:pos2.0")
        self.assertEqual(first.getDockerImages(Platform.ARM64)[ETHEREUM_POS].getName(),
                         "handsonsecurity/seedemu-ethereum:pos2.0")

    def test_monero_custom_image_registration_preserves_override(self):
        from seedemu.compiler import DockerImage, Platform
        from chainseed.services.monero import MoneroService, MoneroNetworkDefaults

        service = MoneroService()
        chain = service.createBlockchain("custom", defaults=MoneroNetworkDefaults(
            custom_base_image="example:monero"))
        profile = chain.getSystemProfile()
        for platform in Platform:
            self.assertEqual(service.getDockerImages(platform)[profile].getName(), "example:monero")
        override = DockerImage("example:override", [])
        service.setDockerImage(profile, override, Platform.AMD64)
        chain.setCustomBaseImage("example:monero")
        self.assertIs(service.getDockerImages(Platform.AMD64)[profile], override)
        service.createBlockchain("other").setCustomBaseImage("example:monero")
        self.assertIs(service.getDockerImages(Platform.AMD64)[profile], override)

    def test_service_image_registration_rejects_invalid_arguments(self):
        from seedemu.core import Service, SystemProfile
        from seedemu.compiler import DockerImage, Platform

        service = Service()
        profile = SystemProfile("example.custom")
        original = DockerImage("example:original", [])
        replacement = DockerImage("example:replacement", [])
        self.assertIs(service.setDockerImage(profile, original, Platform.AMD64), service)

        for platform in ("amd", "amd64", None, 1):
            with self.subTest(platform=platform):
                with self.assertRaisesRegex(TypeError, "platform must be a Platform"):
                    service.setDockerImage(profile, replacement, platform)
        for image in ("example:replacement", None):
            with self.subTest(image=image):
                with self.assertRaisesRegex(TypeError, "image must be a DockerImage"):
                    service.setDockerImage(profile, image, Platform.AMD64)
        for invalid_profile in ("example.custom", None):
            with self.subTest(profile=invalid_profile):
                with self.assertRaisesRegex(TypeError, "profile must be a SystemProfile"):
                    service.setDockerImage(invalid_profile, replacement, Platform.AMD64)

        self.assertIs(service.getDockerImages(Platform.AMD64)[profile], original)
        self.assertEqual(service.getDockerImages(Platform.ARM64), {})
        service.setDockerImage(profile, replacement, Platform.ARM64)
        self.assertIs(service.getDockerImages(Platform.ARM64)[profile], replacement)
        self.assertIs(service.getDockerImages(Platform.AMD64)[profile], original)

    def test_profile_alias_definitions_include_ancestor_consistency(self):
        from seedemu.core import BaseSystem, SystemProfile
        from chainseed.common.systems import ETHEREUM_POS, MONERO

        original = SystemProfile("example.runtime", subset=ETHEREUM_POS)
        equivalent = SystemProfile("example.runtime", subset=ETHEREUM_POS)
        SystemProfile.validateProfiles([original, equivalent, original])
        with self.assertRaisesRegex(ValueError, "Conflicting system profile definitions for example.runtime"):
            SystemProfile.validateProfiles([
                original, SystemProfile("example.runtime", subset=MONERO),
            ])
        # The direct parent aliases agree, but their own definitions do not.
        first_parent = SystemProfile("example.parent", subset=BaseSystem.SEEDEMU_BASE)
        other_parent = SystemProfile("example.parent")
        with self.assertRaisesRegex(ValueError, "Conflicting system profile definitions for example.parent"):
            SystemProfile.validateProfiles([
                SystemProfile("example.child", subset=first_parent),
                SystemProfile("example.child", subset=other_parent),
            ])
        with self.assertRaisesRegex(ValueError, "inheritance contains a cycle"):
            SystemProfile.validateProfiles([
                SystemProfile("example.cycle", subset=SystemProfile("example.cycle")),
            ])

    def test_service_image_registration_rejects_conflicting_aliases(self):
        from seedemu.core import Service, SystemProfile
        from seedemu.compiler import DockerImage, Platform
        from chainseed.services.ethereum import EthereumService
        from chainseed.common.systems import ETHEREUM_POS, MONERO

        first = SystemProfile("example.runtime", subset=ETHEREUM_POS)
        conflicting = SystemProfile("example.runtime", subset=MONERO)
        image = DockerImage("example:runtime", [])
        service = Service()
        service.setDockerImage(first, image, Platform.AMD64)
        for platform in Platform:
            with self.subTest(platform=platform):
                with self.assertRaisesRegex(ValueError, "Conflicting system profile definitions"):
                    service.setDockerImage(conflicting, image, platform)
        self.assertEqual(service.getDockerImages(Platform.ARM64), {})
        self.assertIs(service.getDockerImages(Platform.AMD64)[first], image)

        # Default declarations must not be silently overwritten under the same alias.
        ethereum = EthereumService()
        with self.assertRaisesRegex(ValueError, "Conflicting system profile definitions"):
            ethereum.setDockerImage(
                SystemProfile(ETHEREUM_POS.name, subset=MONERO), image, Platform.AMD64,
            )

    def test_compiler_rejects_conflicting_profile_definitions(self):
        from seedemu.core import Emulator, Service, SystemProfile, Node
        from seedemu.core.enums import NodeRole
        from seedemu.compiler import Docker, DockerImage
        from chainseed.common.systems import ETHEREUM_POS, MONERO

        class ImageService(Service):
            def __init__(self, name, profile):
                super().__init__()
                self.name, self.profile = name, profile

            def getName(self):
                return self.name

            def getDockerImages(self, platform):
                return {self.profile: DockerImage("example:runtime", [])}

        original = SystemProfile("example.runtime", subset=ETHEREUM_POS)
        conflicting = SystemProfile("example.runtime", subset=MONERO)
        emulator = Emulator()
        emulator.addLayer(ImageService("First", original))
        other = Emulator()
        other.addLayer(ImageService("Second", conflicting))
        emulator = emulator.merge(other)
        with self.assertRaisesRegex(ValueError, "Conflicting system profile definitions"):
            Docker()._collectServiceImages(emulator)

        # A conflicting declaration on a Node must also be checked against the catalog.
        emulator = Emulator()
        emulator.addLayer(ImageService("First", original))
        node = Node("host", NodeRole.Host, 150).setBaseSystem(conflicting)
        emulator.getRegistry().register("150", "hnode", "host", node)
        with self.assertRaisesRegex(ValueError, "Conflicting system profile definitions"):
            Docker()._collectServiceImages(emulator)

    def test_service_image_conflicts_and_deduplication(self):
        from seedemu.core import Emulator, Service, SystemProfile, Node
        from seedemu.core.enums import NodeRole
        from seedemu.compiler import Docker, DockerImage, Platform

        class ImageService(Service):
            def __init__(self, name):
                super().__init__()
                self.name = name

            def getName(self):
                return self.name

        profile = SystemProfile("example.custom")
        first = ImageService("First")
        first.setDockerImage(profile, DockerImage("example:one", []), Platform.AMD64)
        second = ImageService("Second")
        second.setDockerImage(profile, DockerImage("example:two", []), Platform.AMD64)
        emulator = Emulator()
        emulator.addLayer(first)
        emulator.addLayer(second)
        compiler = Docker()
        with self.assertRaisesRegex(ValueError, "Conflicting Docker images.*example.custom"):
            compiler._collectServiceImages(emulator)
        # Equal declarations from independent instances are allowed.
        second.setDockerImage(profile, DockerImage("example:one", []), Platform.AMD64)
        alias = SystemProfile("example.alias")
        second.setDockerImage(alias, DockerImage("example:one", []), Platform.AMD64)
        compiler = Docker()
        compiler._collectServiceImages(emulator)
        node = Node("test", NodeRole.Host, 150).setBaseSystem(profile)
        self.assertEqual(compiler._selectImageFor(node)[0].getName(), "example:one")
        alias_node = Node("alias", NodeRole.Host, 150).setBaseSystem(alias)
        self.assertIs(
            compiler._selectImageFor(node)[0],
            compiler._selectImageFor(alias_node)[0],
        )
        self.assertEqual(first.getDockerImages(Platform.ARM64), {})
        arm = Docker(platform=Platform.ARM64)
        arm._collectServiceImages(emulator)
        with self.assertRaisesRegex(KeyError, "does not support system profile"):
            arm._selectImageFor(node)
        with self.assertRaises(KeyError):
            Docker()._selectImageFor(node)
        # One image tag cannot claim inconsistent installed software.
        second.setDockerImage(SystemProfile("example.other"), DockerImage("example:one", ["geth"]), Platform.AMD64)
        with self.assertRaisesRegex(ValueError, "Conflicting Docker image definitions"):
            Docker()._collectServiceImages(emulator)

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

        emulator, _, _ = build(
            enhanced_pos, SystemProfile(enhanced_pos.name, subset=SOLANA),
        )
        with self.assertRaisesRegex(ValueError, "Conflicting system profile definitions"):
            emulator.render()

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
