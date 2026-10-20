"""Compile real service configurations against the public SeedEmu contract."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from seedemu.core import Action, Binding, Emulator, Filter
from seedemu.layers import Base, Routing
from chainseed import ChainSeedDocker
from chainseed.services.ethereum import ConsensusMechanism, EthereumService


class PackageIntegrationTests(unittest.TestCase):
    def test_emulated_networks_allow_router_forwarding(self):
        from seedemu.core import Network, Registry
        from seedemu.core.enums import NetworkType

        compiler = ChainSeedDocker()
        self.assertNotIn("_compileNet", ChainSeedDocker.__dict__)
        for kind in (NetworkType.Local, NetworkType.InternetExchange):
            network = Network("net", kind, "10.250.0.0/24")
            Registry().register("250", "net", "net", network)
            fragment = yaml.safe_load(compiler._compileNet(network))
            options = next(iter(fragment.values()))["driver_opts"]
            self.assertEqual(
                options["com.docker.network.bridge.gateway_mode_ipv4"],
                "nat-unprotected",
            )
        bridge = Network("external", NetworkType.Bridge, "172.30.250.0/24")
        Registry().register("250", "net", "external", bridge)
        fragment = yaml.safe_load(compiler._compileNet(bridge))
        self.assertNotIn(
            "com.docker.network.bridge.gateway_mode_ipv4",
            next(iter(fragment.values()))["driver_opts"],
        )

    def make_emulator(self, names):
        emulator = Emulator()
        base = Base()
        system = base.createAutonomousSystem(150)
        system.createNetwork("net0")
        system.createRouter("router0").joinNetwork("net0")
        for name in names:
            system.createHost(name).joinNetwork("net0")
            emulator.addBinding(
                Binding(name, action=Action.FIRST, filter=Filter(asn=150, nodeName=name))
            )
        emulator.addLayer(base)
        emulator.addLayer(Routing())
        return emulator

    def compile(self, emulator, compiler=None):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                emulator.render()
                emulator.compile(compiler or ChainSeedDocker(), directory + "/output")
                compose = yaml.safe_load(Path(directory, "output/docker-compose.yml").read_text())
                dockerfiles = []
                for entry in compose["services"].values():
                    build = entry.get("build")
                    if isinstance(build, str):
                        context, filename = build, "Dockerfile"
                    elif isinstance(build, dict):
                        context = build.get("context", ".")
                        filename = build.get("dockerfile", "Dockerfile")
                    else:
                        continue
                    dockerfiles.append(Path(directory, "output", context, filename).read_text())
                self.compiled_dockerfiles = "\n".join(dockerfiles)
                self.assertTrue(compose["services"])
                return compose
            finally:
                os.chdir(original_cwd)

    def test_ethereum_pos_with_explorer(self):
        emulator = self.make_emulator(["geth", "beacon", "validator", "setup"])
        service = EthereumService()
        chain = service.createBlockchain("pos", ConsensusMechanism.POS)
        chain.createGethNode("geth").setBootNode(True).enableGethHttp()
        chain.createBeaconNode("beacon").setBootNode(True).connectToGethNode("geth")
        chain.createVcNode("validator").enablePOSValidatorAtGenesis().connectToBeaconNode("beacon")
        chain.createBeaconSetupNode("setup")
        emulator.addLayer(service)
        compose = self.compile(emulator, ChainSeedDocker().enableEthExplorer("pos"))
        self.assertIn("seedemu-ethexplorer-backend", compose["services"])

    def test_legacy_ethereum_and_custom_binary(self):
        for consensus in (ConsensusMechanism.POA, ConsensusMechanism.POW):
            with self.subTest(consensus=consensus), tempfile.TemporaryDirectory() as directory:
                binary = Path(directory, "custom geth")
                binary.write_text("custom-client-fixture\n")
                emulator = self.make_emulator(["geth"])
                service = EthereumService()
                chain = service.createBlockchain("legacy", consensus)
                chain.createNode("geth").setBootNode(True).startMiner().setCustomGeth(str(binary))
                emulator.addLayer(service)
                self.compile(emulator)
                host = emulator.getLayer("Base").getAutonomousSystem(150).getHost("geth")
                self.assertEqual(host.getImportedFiles()["/usr/bin/geth"], str(binary.resolve()))

    def test_monero(self):
        from chainseed.services.monero import MoneroService

        emulator = self.make_emulator(["seed", "client"])
        service = MoneroService()
        chain = service.createBlockchain("monero")
        chain.createSeedNode("seed")
        chain.createClientNode("client")
        emulator.addLayer(service)
        self.compile(emulator)

    def test_monero_custom_image_is_applied_by_plugin_compiler(self):
        from chainseed.services.monero import MoneroService

        emulator = self.make_emulator(["seed"])
        service = MoneroService()
        chain = service.createBlockchain("custom-monero")
        chain.setCustomBaseImage("chainseed-monero-fixture:static")
        chain.createSeedNode("seed")
        emulator.addLayer(service)
        compose = self.compile(emulator)
        self.assertIn("FROM chainseed-monero-fixture:static", self.compiled_dockerfiles)

    def test_monero_seed_connection_policies_reach_start_scripts(self):
        from chainseed.services.monero import MoneroSeedConnectionMode, MoneroService

        flags = {
            MoneroSeedConnectionMode.EXCLUSIVE: "--add-exclusive-node",
            MoneroSeedConnectionMode.PRIORITY: "--add-priority-node",
            MoneroSeedConnectionMode.SEED: "--seed-node",
        }
        names = ["seed1", "seed2", "client", "override", "pruned"]
        for mode, flag in flags.items():
            for builtin in (False, True):
                with self.subTest(mode=mode, builtin=builtin):
                    emulator = self.make_emulator(names)
                    service = MoneroService()
                    chain = service.createBlockchain("seed-policies")
                    chain.setSeedConnectionMode(mode).setUseDefaultSeedNodes(builtin)
                    servers = {
                        "seed1": chain.createSeedNode("seed1"),
                        "seed2": chain.createSeedNode("seed2"),
                        "client": chain.createClientNode("client"),
                        "override": chain.createClientNode(
                            "override", connect_mode=MoneroSeedConnectionMode.PRIORITY
                        ),
                        "pruned": chain.createPrunedNode("pruned"),
                    }
                    emulator.addLayer(service)
                    emulator.render()
                    system = emulator.getLayer("Base").getAutonomousSystem(150)
                    endpoints = {
                        name: "{}:{}".format(
                            system.getHost(name).getInterfaces()[0].getAddress(),
                            servers[name].get_p2p_port(),
                        )
                        for name in ("seed1", "seed2")
                    }
                    for name in names:
                        text = system.getHost(name).getFile(
                            "/usr/local/bin/seedemu-monero-node.sh"
                        ).get()[1]
                        actual = [
                            line.strip() for line in text.splitlines()
                            if any(line.strip().startswith('DAEMON_ARGS+=("' + f + '=')
                                   for f in flags.values())
                        ]
                        selected = flags[MoneroSeedConnectionMode.PRIORITY] if name == "override" else flag
                        expected = [] if builtin else [
                            'DAEMON_ARGS+=("{}={}")'.format(selected, endpoint)
                            for seed, endpoint in endpoints.items() if seed != name
                        ]
                        self.assertCountEqual(actual, expected)

    def test_solana(self):
        from chainseed.services.solana import SolanaService

        emulator = self.make_emulator(["bootstrap", "validator"])
        service = SolanaService()
        chain = service.createBlockchain("solana")
        chain.createBootstrapValidator("bootstrap")
        chain.createValidator("validator")
        emulator.addLayer(service)
        self.compile(emulator)

    def test_chainlink(self):
        from chainseed.services.chainlink import ChainlinkService

        emulator = self.make_emulator(["geth", "faucet", "utility", "oracle", "user"])
        ethereum = EthereumService()
        chain = ethereum.createBlockchain("poa", ConsensusMechanism.POA)
        chain.createNode("geth").setBootNode(True).startMiner().enableGethHttp()
        chain.createFaucetServer("faucet", 80, "geth")
        chain.createEthUtilityServer("utility", 5000, "geth", "faucet")
        emulator.addLayer(ethereum)
        service = ChainlinkService("geth", "faucet", "utility")
        service.install("oracle")
        service.installUserServer("user").setChainlinkServers(["oracle"])
        emulator.addLayer(service)
        self.compile(emulator)

    def test_incompatible_seedemu_reports_required_api(self):
        from seedemu.compiler import Docker
        from chainseed.extension import check_seedemu_compatibility

        # SeedEmu supplies the required hooks without an API version marker.
        check_seedemu_compatibility()
        with patch.object(Docker, "_getAdditionalComposeServices", None):
            with self.assertRaisesRegex(RuntimeError, "Docker branch"):
                check_seedemu_compatibility()


if __name__ == "__main__":
    unittest.main()
