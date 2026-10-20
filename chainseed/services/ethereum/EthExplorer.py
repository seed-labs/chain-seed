"""Docker deployment integration for the ChainSeed Ethereum explorer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Tuple

from seedemu.core import Emulator, Network, Node
from seedemu.core.enums import NetworkType

from ...common.labels import CHAINSEED_LABEL_PREFIX
from .EthereumServer import PoSBeaconServer, PoSGethServer
from .EthereumService import EthereumService


ETH_EXPLORER_COMPONENT_LABEL = CHAINSEED_LABEL_PREFIX + "component"
ETH_EXPLORER_BACKEND_IMAGE = "handsonsecurity/seedemu-ethexplorer-backend:1.0"
ETH_EXPLORER_WEB_IMAGE = "handsonsecurity/seedemu-ethexplorer-web:1.0"

ETH_EXPLORER_SERVICE_NAMES = (
    "clickhouse",
    "postgres",
    "alloy",
    "redis",
    "littlebigtable",
    "rawbigtable",
    "seedemu-ethexplorer-backend",
    "seedemu-ethexplorer-web",
)


@dataclass(frozen=True)
class _Endpoint:
    address: str
    network: Network
    port: int


class EthExplorer:
    """Attach the ChainSeed EthExplorer stack to a rendered Ethereum PoS chain."""

    def __init__(
        self,
        chain_name: str,
        port: int = 5000,
        backend_image: str = ETH_EXPLORER_BACKEND_IMAGE,
        web_image: str = ETH_EXPLORER_WEB_IMAGE,
        *,
        geth_vnode: str | None = None,
        beacon_vnode: str | None = None,
    ):
        if not isinstance(chain_name, str) or not chain_name.strip():
            raise ValueError("chain_name must be a non-empty string")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")
        if not isinstance(backend_image, str) or not backend_image.strip():
            raise ValueError("backend_image must be a non-empty string")
        if not isinstance(web_image, str) or not web_image.strip():
            raise ValueError("web_image must be a non-empty string")
        for name, value in (("geth_vnode", geth_vnode), ("beacon_vnode", beacon_vnode)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty virtual node name or None")

        self.__chain_name = chain_name
        self.__port = port
        self.__backend_image = backend_image
        self.__web_image = web_image
        self.__geth_vnode = geth_vnode
        self.__beacon_vnode = beacon_vnode

    def getComposeServices(
        self,
        emulator: Emulator,
        network_name: Callable[[Network], str],
    ) -> Mapping[str, Dict[str, object]]:
        """Build the Explorer's auxiliary Compose service definitions."""

        if not isinstance(emulator, Emulator):
            raise TypeError("emulator must be an Emulator")
        if not callable(network_name):
            raise TypeError("network_name must be callable")
        if not emulator.rendered():
            raise RuntimeError("the emulator must be rendered before attaching EthExplorer")

        ethereum = emulator.getLayer("EthereumService")
        if not isinstance(ethereum, EthereumService):
            raise RuntimeError("EthereumService is not installed in the emulator")

        geth, geth_node = self.__select_target(ethereum, PoSGethServer, "Geth", self.__geth_vnode)
        _, beacon_node = self.__select_target(ethereum, PoSBeaconServer, "Beacon", self.__beacon_vnode)
        geth_endpoint = self.__endpoint(geth_node, geth.getGethHttpPort())
        # The Beacon HTTP API currently has a fixed port in the client template.
        beacon_endpoint = self.__endpoint(beacon_node, 8000)

        emulated_networks = []
        for network in (geth_endpoint.network, beacon_endpoint.network):
            name = network_name(network)
            if name not in emulated_networks:
                emulated_networks.append(name)

        return self.__services(
            geth_endpoint,
            beacon_endpoint,
            tuple(emulated_networks),
        )

    def __select_target(self, ethereum: EthereumService, server_type, role: str,
                        vnode: str | None):
        if vnode is not None:
            server = ethereum.getPendingTargets().get(vnode)
            if server is None:
                raise ValueError(f"EthExplorer {role} virtual node {vnode!r} does not exist")
            if not isinstance(server, server_type):
                raise ValueError(f"EthExplorer virtual node {vnode!r} must be a PoS {role} server")
            if server.getBlockchain().getChainName() != self.__chain_name:
                raise ValueError(f"EthExplorer virtual node {vnode!r} is not in chain {self.__chain_name!r}")
            self.__require_capability(server, role, vnode)
            for target_server, node in ethereum.getTargets():
                if target_server is server:
                    return server, node
            raise RuntimeError(f"EthExplorer virtual node {vnode!r} has no rendered target")

        targets = [
            (server, node)
            for server, node in ethereum.getTargets()
            if isinstance(server, server_type)
            and server.getBlockchain().getChainName() == self.__chain_name
        ]
        if not targets:
            raise RuntimeError(
                "EthExplorer chain {} has no rendered PoS {} node".format(
                    self.__chain_name,
                    role,
                )
            )
        targets = [(server, node) for server, node in targets if self.__capable(server, role)]
        if not targets:
            requirement = ("enableGethHttp()" if role == "Geth" else
                           "setReconstructHistoricStates(True)")
            raise ValueError(f"EthExplorer chain {self.__chain_name!r} needs a {role} server with {requirement}")
        targets.sort(
            key=lambda target: (
                target[1].getRegistryInfo(),
                target[0].getId(),
            )
        )
        return targets[0]

    @staticmethod
    def __capable(server, role):
        return (server.isGethHttpEnabled() if role == "Geth" else
                server.isReconstructHistoricStatesEnabled())

    def __require_capability(self, server, role, vnode):
        if not self.__capable(server, role):
            requirement = ("enableGethHttp()" if role == "Geth" else
                           "setReconstructHistoricStates(True)")
            raise ValueError(f"EthExplorer virtual node {vnode!r} requires {requirement} before render()")

    def __endpoint(self, node: Node, port: int) -> _Endpoint:
        interfaces = [
            interface
            for interface in node.getInterfaces()
            if interface.getNet().getType() == NetworkType.Local
        ]
        if not interfaces:
            raise RuntimeError(
                "EthExplorer endpoint as{}/{} has no local network interface".format(
                    node.getAsn(),
                    node.getName(),
                )
            )
        interface = interfaces[0]
        address = interface.getAddress()
        if address is None:
            raise RuntimeError(
                "EthExplorer endpoint as{}/{} has no IP address".format(
                    node.getAsn(),
                    node.getName(),
                )
            )
        return _Endpoint(str(address), interface.getNet(), port)

    def __services(
        self,
        execution: _Endpoint,
        consensus: _Endpoint,
        emulated_networks: Tuple[str, ...],
    ) -> Mapping[str, Dict[str, object]]:
        explorer_networks = {"default": {}}
        explorer_networks.update({name: {} for name in emulated_networks})

        postgres_healthcheck = {
            "test": ["CMD-SHELL", "pg_isready -U postgres"],
            "interval": "30s",
            "timeout": "10s",
            "retries": 5,
        }

        services = {
            "clickhouse": {
                "image": "clickhouse/clickhouse-server:latest",
                "container_name": "clickhouse",
                "restart": "unless-stopped",
                "environment": {
                    "CLICKHOUSE_DB": "beaconchain",
                    "CLICKHOUSE_USER": "beacon",
                    "CLICKHOUSE_PASSWORD": "pass",
                },
                "healthcheck": {
                    "test": ["CMD", "wget", "--spider", "-q", "http://localhost:8123/ping"],
                    "interval": "30s",
                    "timeout": "10s",
                    "retries": 3,
                },
            },
            "postgres": {
                "image": "postgres:15.2-alpine",
                "container_name": "postgres",
                "restart": "unless-stopped",
                "environment": {
                    "POSTGRES_PASSWORD": "pass",
                    "POSTGRES_DB": "db",
                    "POSTGRES_USER": "postgres",
                },
                "healthcheck": postgres_healthcheck,
            },
            "alloy": {
                "image": "postgres:15.2-alpine",
                "container_name": "alloy",
                "restart": "unless-stopped",
                "environment": {
                    "POSTGRES_PASSWORD": "pass",
                    "POSTGRES_DB": "db",
                    "POSTGRES_USER": "postgres",
                },
                "healthcheck": postgres_healthcheck,
            },
            "redis": {
                "image": "redis:7-alpine",
                "container_name": "redis",
                "restart": "unless-stopped",
                "command": "redis-server --appendonly yes",
                "healthcheck": {
                    "test": ["CMD", "redis-cli", "ping"],
                    "interval": "30s",
                    "timeout": "10s",
                    "retries": 3,
                },
            },
            "littlebigtable": {
                "image": "gobitfly/little_bigtable:latest",
                "container_name": "littlebigtable",
                "restart": "unless-stopped",
                "depends_on": ["postgres"],
            },
            "rawbigtable": {
                "image": "gobitfly/little_bigtable:latest",
                "container_name": "rawbigtable",
                "restart": "unless-stopped",
                "depends_on": ["alloy"],
            },
            "seedemu-ethexplorer-backend": {
                "image": self.__backend_image,
                "container_name": "seedemu_ethexplorer_backend",
                "cap_add": ["ALL"],
                "pid": "host",
                "privileged": True,
                "healthcheck": {
                    "test": [
                        "CMD-SHELL",
                        (
                            "PGPASSWORD=pass psql -h postgres -U postgres -d db -tAc "
                            "\"SELECT 1 FROM information_schema.tables "
                            "WHERE table_name='blocks';\" | grep -q 1"
                        ),
                    ],
                    "interval": "5s",
                    "timeout": "3s",
                    "retries": 60,
                    "start_period": "10s",
                },
                "depends_on": {
                    "clickhouse": {"condition": "service_healthy"},
                    "postgres": {"condition": "service_healthy"},
                    "alloy": {"condition": "service_healthy"},
                    "redis": {"condition": "service_healthy"},
                    "littlebigtable": {"condition": "service_started"},
                    "rawbigtable": {"condition": "service_started"},
                },
                "environment": [
                    "EL_HOST={}".format(execution.address),
                    "EL_PORT={}".format(execution.port),
                    "CL_HOST={}".format(consensus.address),
                    "CL_PORT={}".format(consensus.port),
                ],
                "networks": explorer_networks,
            },
            "seedemu-ethexplorer-web": {
                "image": self.__web_image,
                "container_name": "seedemu_ethexplorer_web",
                "cap_add": ["ALL"],
                "pid": "host",
                "privileged": True,
                "depends_on": {
                    "clickhouse": {"condition": "service_healthy"},
                    "postgres": {"condition": "service_healthy"},
                    "alloy": {"condition": "service_healthy"},
                    "redis": {"condition": "service_healthy"},
                    "littlebigtable": {"condition": "service_started"},
                    "rawbigtable": {"condition": "service_started"},
                    "seedemu-ethexplorer-backend": {"condition": "service_healthy"},
                },
                "environment": [
                    "EL_HOST={}".format(execution.address),
                    "EL_PORT={}".format(execution.port),
                    "CL_HOST={}".format(consensus.address),
                    "CL_PORT={}".format(consensus.port),
                ],
                "ports": ["{}:5000/tcp".format(self.__port)],
                "networks": explorer_networks,
            },
        }

        for service in services.values():
            service["labels"] = {ETH_EXPLORER_COMPONENT_LABEL: "ethexplorer"}
        return services


__all__ = [
    "ETH_EXPLORER_BACKEND_IMAGE",
    "ETH_EXPLORER_COMPONENT_LABEL",
    "ETH_EXPLORER_SERVICE_NAMES",
    "ETH_EXPLORER_WEB_IMAGE",
    "EthExplorer",
]
