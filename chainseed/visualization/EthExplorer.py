"""Ethereum explorer deployed through SeedEmu's ContainerBundle interface."""

from copy import deepcopy
from dataclasses import dataclass

from seedemu.containerBundle import ContainerBundle
from seedemu.core import Emulator, Network, Node
from seedemu.core.enums import NetworkType

from ..common.labels import CHAINSEED_LABEL_PREFIX
from ..services.ethereum.EthereumServer import PoSBeaconServer, PoSGethServer
from ..services.ethereum.EthereumService import EthereumService


ETH_EXPLORER_COMPONENT_LABEL = CHAINSEED_LABEL_PREFIX + "component"
ETH_EXPLORER_SERVICE_NAMES = (
    "clickhouse", "postgres", "redis", "littlebigtable", "rawbigtable",
    "seedemu-ethexplorer-backend", "seedemu-ethexplorer-web",
)


ETH_EXPLORER_BACKEND_IMAGE = "handsonsecurity/seedemu-ethexplorer-backend:1.0"
ETH_EXPLORER_WEB_IMAGE = "handsonsecurity/seedemu-ethexplorer-web:1.0"
CLICKHOUSE_IMAGE = "clickhouse/clickhouse-server:25.11"
POSTGRES_IMAGE = "postgres:15.2-alpine"
REDIS_IMAGE = "redis:7-alpine"
LITTLE_BIGTABLE_IMAGE = "gobitfly/little_bigtable:latest"

ETH_EXPLORER_WEB_INTERNAL_PORT = 5000

DOCKER_LOGGING = {
    "driver": "json-file",
    "options": {"max-size": "200m", "max-file": "1"},
}

DEFAULT_NETWORK = {
    "name": "ethExplorer_network",
    "prefix": ".eth",
    "ip_addresses": [
        "172.20.0.10",
        "172.20.0.11",
        "172.20.0.12",
        "172.20.0.13",
        "172.20.0.14",
        "172.20.0.15",
        "172.20.0.16",
    ],
    "network_config": {
        "driver": "bridge",
        "ipam": {"config": [{"subnet": "172.20.0.0/24", "gateway": "172.20.0.1"}]},
    },
}

BACKEND_START_SH = [
    "#!/bin/sh",
    'DEFAULT_ROUTE="{default_route}"',
    'IFACE=$(ip route get "$DEFAULT_ROUTE" | awk \'{for (i=1;i<=NF;i++) if ($i=="dev") print $(i+1); exit}\')',
    'echo "gateway=$DEFAULT_ROUTE interface=$IFACE"',
    "ip route del default 2>/dev/null || true",
    'ip route add default via "$DEFAULT_ROUTE" dev "$IFACE"',
    "stopit() {",
    '  echo "trapped SIGINT"',
    "  exit 0",
    "}",
    "trap stopit SIGINT",
    'echo "run provision-explorer-config-custom.sh ..."',
    "cd /app/local_deployment",
    "chmod +x provision-explorer-config-custom.sh",
    "./provision-explorer-config-custom.sh",
    "if [ $? -eq 0 ]; then",
    '  echo "SUCCESS: script executed normally"',
    "else",
    '  echo "ERROR: script failed"',
    "  exit 1",
    "fi",
    # Replace service hosts while preserving values resolved by provisioning.
    "sed -i "
    "-e '/^[[:space:]]*readerDatabase:/,/^[[:space:]]*host:/ s|^\\([[:space:]]*host:\\).*|\\1 {POSTGRES_HOST}|' "
    "-e '/^[[:space:]]*writerDatabase:/,/^[[:space:]]*host:/ s|^\\([[:space:]]*host:\\).*|\\1 {POSTGRES_HOST}|' "
    "-e '/^alloyReader:/,/^[[:space:]]*host:/ s|^\\([[:space:]]*host:\\).*|\\1 {POSTGRES_HOST}|' "
    "-e '/^alloyWriter:/,/^[[:space:]]*host:/ s|^\\([[:space:]]*host:\\).*|\\1 {POSTGRES_HOST}|' "
    "-e '/^clickhouse:/,/^[^[:space:]#]/ s|^\\([[:space:]]*host:\\).*|\\1 {CLICKHOUSE_HOST}|' "
    "-e '/^bigtable:/,/^[[:space:]]*emulatorHost:/ s|^\\([[:space:]]*emulatorHost:\\).*|\\1 {LBT_HOST}|' "
    "-e '/^rawBigtable:/,/^[[:space:]]*emulatorHost:/ s|^\\([[:space:]]*emulatorHost:\\).*|\\1 {RBT_HOST}|' "
    "-e \"s|^redisCacheEndpoint: '.*:|redisCacheEndpoint: '{REDIS_HOST}:|\" "
    "-e \"s|^redisSessionStoreEndpoint: '.*:|redisSessionStoreEndpoint: '{REDIS_HOST}:|\" "
    "/app/local_deployment/config.yml || exit 1",
    "cd /app",
    'echo "start ..."',
    'echo "run eth1indexer"',
    "bc eth1indexer -config /app/local_deployment/config.yml -concurrency 1 -blocks.tracemode 'geth' &",
    'echo "run rewards-exporter"',
    "bc rewards-exporter -config /app/local_deployment/config.yml &",
    'echo "run statistics"',
    "bc statistics -config /app/local_deployment/config.yml --charts.enabled --graffiti.enabled -validators.enabled -deposits.enabled &",
    'echo "end."',
    "while true; do",
    "  date",
    "  sleep 1",
    "done",
]
FRONTEND_START_SH = [
    "#!/bin/bash",
    'DEFAULT_ROUTE="{default_route}"',
    'IFACE=$(ip route get "$DEFAULT_ROUTE" | awk \'{for (i=1;i<=NF;i++) if ($i=="dev") print $(i+1); exit}\')',
    'echo "gateway=$DEFAULT_ROUTE interface=$IFACE"',
    "ip route del default 2>/dev/null || true",
    'ip route add default via "$DEFAULT_ROUTE" dev "$IFACE"',
    "stopit() {",
    '  echo "trapped SIGINT"',
    "  exit 0",
    "}",
    "trap stopit SIGINT",
    'echo "run provision-explorer-config-custom.sh ..."',
    "cd /app/local-deployment",
    "chmod +x provision-explorer-config-custom.sh",
    "./provision-explorer-config-custom.sh",
    "if [ $? -eq 0 ]; then",
    '  echo "SUCCESS: script executed normally"',
    "else",
    '  echo "ERROR: script failed"',
    "  exit 1",
    "fi",
    # Replace service hosts while preserving values resolved by provisioning.
    "sed -i "
    "-e '/^[[:space:]]*readerDatabase:/,/^[[:space:]]*host:/ s|^\\([[:space:]]*host:\\).*|\\1 {POSTGRES_HOST}|' "
    "-e '/^[[:space:]]*writerDatabase:/,/^[[:space:]]*host:/ s|^\\([[:space:]]*host:\\).*|\\1 {POSTGRES_HOST}|' "
    "-e '/^alloyReader:/,/^[[:space:]]*host:/ s|^\\([[:space:]]*host:\\).*|\\1 {POSTGRES_HOST}|' "
    "-e '/^alloyWriter:/,/^[[:space:]]*host:/ s|^\\([[:space:]]*host:\\).*|\\1 {POSTGRES_HOST}|' "
    "-e '/^clickhouse:/,/^[^[:space:]#]/ s|^\\([[:space:]]*host:\\).*|\\1 {CLICKHOUSE_HOST}|' "
    "-e '/^bigtable:/,/^[[:space:]]*emulatorHost:/ s|^\\([[:space:]]*emulatorHost:\\).*|\\1 {LBT_HOST}|' "
    "-e '/^rawBigtable:/,/^[[:space:]]*emulatorHost:/ s|^\\([[:space:]]*emulatorHost:\\).*|\\1 {RBT_HOST}|' "
    "-e \"s|^redisCacheEndpoint: '.*:|redisCacheEndpoint: '{REDIS_HOST}:|\" "
    "-e \"s|^redisSessionStoreEndpoint: '.*:|redisSessionStoreEndpoint: '{REDIS_HOST}:|\" "
    "/app/local-deployment/config.yml || exit 1",
    "cd /app",
    'echo "start ..."',
    'echo "run explorer"',
    "/app/explorer -config /app/local-deployment/config.yml &",
    'echo "run validator-tagger"',
    "/app/validator-tagger -config /app/local-deployment/config.yml -schedule true &",
    'echo "run frontend-data-updater"',
    "/app/frontend-data-updater -config /app/local-deployment/config.yml &",
    'echo "end."',
    "while true; do",
    "  date",
    "  sleep 1",
    "done",
]


@dataclass(frozen=True)
class _Endpoint:
    address: str
    network: Network
    port: int


class EthExplorer(ContainerBundle):
    """Attach an explorer bundle to selected Ethereum PoS clients."""

    def __init__(self, emulator: Emulator, suffix: str = "eth.explorer", *,
                 chain_name: str | None = None, port: int = 5000,
                 backend_image: str = ETH_EXPLORER_BACKEND_IMAGE,
                 web_image: str = ETH_EXPLORER_WEB_IMAGE,
                 geth_vnode: str | None = None, beacon_vnode: str | None = None):
        if not isinstance(emulator, Emulator):
            raise TypeError("emulator must be an Emulator")
        if chain_name is not None and (not isinstance(chain_name, str) or not chain_name.strip()):
            raise ValueError("chain_name must be a non-empty string")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")
        for name, value in (("backend_image", backend_image), ("web_image", web_image)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name, value in (("geth_vnode", geth_vnode), ("beacon_vnode", beacon_vnode)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty virtual node name or None")
        super().__init__(emulator=emulator, suffix=suffix)
        self.__chain_name = chain_name
        self.__backend_image = backend_image
        self.__web_image = web_image
        self.__geth_vnode = geth_vnode
        self.__beacon_vnode = beacon_vnode
        self.__beacon_host = self.__geth_host = ""
        self._default_network = deepcopy(DEFAULT_NETWORK)
        self.setPorts([port])
        for service_name in ETH_EXPLORER_SERVICE_NAMES:
            self._createContainer(service_name, suffix)

    def configure(self) -> None:
        self._required_port_number = 1
        super().configure()

        if not self._emulator.rendered():
            raise RuntimeError("the emulator must be rendered before configuring EthExplorer")
        if len(self._ports) != 1 or type(self._ports[0]) is not int or not 1 <= self._ports[0] <= 65535:
            raise ValueError("EthExplorer requires one valid published port")
        eth = self._emulator.getLayer("EthereumService")
        if not isinstance(eth, EthereumService):
            raise RuntimeError("EthereumService is not installed in the emulator")
        if self.__chain_name is None:
            chains = eth.getBlockchainNames()
            if len(chains) != 1:
                raise ValueError("EthExplorer requires chain_name when multiple chains exist")
            self.__chain_name = chains[0]
        if self.__chain_name not in eth.getBlockchainNames():
            raise ValueError(f"EthExplorer chain {self.__chain_name!r} does not exist")
        geth, geth_node = self.__select_target(eth, PoSGethServer, "Geth", self.__geth_vnode)
        _, beacon_node = self.__select_target(eth, PoSBeaconServer, "Beacon", self.__beacon_vnode)
        execution = self.__endpoint(geth_node, geth.getGethHttpPort())
        consensus = self.__endpoint(beacon_node, 8000)
        if not self.__geth_host:
            self.__geth_host = execution.address
        if not self.__beacon_host:
            self.__beacon_host = consensus.address
        network = execution.network
        scope, _, _ = network.getRegistryInfo()
        router = network.getDefaultRouter()
        if router is None:
            raise RuntimeError("EthExplorer's emulated network needs a default router")
        self._emu_internal_network = dict(network=f"net_{scope}_{network.getName()}",
            hostname=geth_node.getName(), ip_address=execution.address,
            default_route=str(router))
        environment = dict(CL_HOST=self.__beacon_host, CL_PORT=str(consensus.port),
                           EL_HOST=self.__geth_host, EL_PORT=str(execution.port))

        default_network_name = self._default_network["name"]
        ip_addresses = self._default_network["ip_addresses"]
        for index, container in enumerate(self._containers.values()):
            container.joinExternalNetwork(
                default_network_name, container.getHostname(), ip_addresses[index]
            )

        clickhouse = self._containers["clickhouse"]
        clickhouse.setContentAttribute(
            {
                "image": CLICKHOUSE_IMAGE,
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
            }
        )

        postgres = self._containers["postgres"]
        postgres.setContentAttribute(
            {
                "image": POSTGRES_IMAGE,
                "environment": {
                    "POSTGRES_DB": "db",
                    "POSTGRES_USER": "postgres",
                    "POSTGRES_PASSWORD": "pass",
                },
                "healthcheck": {
                    "test": ["CMD-SHELL", "pg_isready -U postgres"],
                    "interval": "30s",
                    "timeout": "10s",
                    "retries": 5,
                },
            }
        )

        redis = self._containers["redis"]
        redis.setContentAttribute(
            {
                "image": REDIS_IMAGE,
                "command": "redis-server --appendonly yes",
                "healthcheck": {
                    "test": ["CMD", "redis-cli", "ping"],
                    "interval": "30s",
                    "timeout": "10s",
                    "retries": 3,
                },
            }
        )

        littlebigtable = self._containers["littlebigtable"]
        littlebigtable.setContentAttribute(
            {
                "image": LITTLE_BIGTABLE_IMAGE,
                "depends_on": [postgres.getName()],
            }
        )

        rawbigtable = self._containers["rawbigtable"]
        rawbigtable.setContentAttribute(
            {
                "image": LITTLE_BIGTABLE_IMAGE,
                "depends_on": [postgres.getName()],
            }
        )

        clickhouse_ip = clickhouse.service["networks"][default_network_name]["ipv4_address"]
        postgres_ip = postgres.service["networks"][default_network_name]["ipv4_address"]
        redis_ip = redis.service["networks"][default_network_name]["ipv4_address"]
        littlebigtable_ip = littlebigtable.service["networks"][default_network_name][
            "ipv4_address"
        ]
        rawbigtable_ip = rawbigtable.service["networks"][default_network_name]["ipv4_address"]

        seedemu_ethexplorer_backend = self._containers["seedemu-ethexplorer-backend"]
        seedemu_ethexplorer_backend.setContentAttribute(
            {
                "image": self.__backend_image,
                "privileged": True,
                "pid": "host",
                "cap_add": ["ALL"],
                "healthcheck": {
                    "test": [
                        "CMD-SHELL",
                        """PGPASSWORD=pass psql -h postgres -U postgres -d db -tAc "SELECT 1 FROM information_schema.tables WHERE table_name='blocks';" | grep -q 1""",
                    ],
                    "interval": "5s",
                    "timeout": "3s",
                    "retries": 60,
                    "start_period": "10s",
                },
                "depends_on": {
                    "clickhouse": {"condition": "service_healthy"},
                    "postgres": {"condition": "service_healthy"},
                    "redis": {"condition": "service_healthy"},
                    "littlebigtable": {"condition": "service_started"},
                    "rawbigtable": {"condition": "service_started"},
                },
                "environment": environment.copy(),
                "build": f"./{seedemu_ethexplorer_backend.getHostname()}",
                "logging": DOCKER_LOGGING,
            }
        )
        seedemu_ethexplorer_backend.joinInternalNetwork(**self._emu_internal_network)
        backend_start_commands = BACKEND_START_SH.copy()
        backend_start_commands[1] = backend_start_commands[1].format(
            default_route=self._emu_internal_network["default_route"]
        )
        backend_start_commands = [
            command.format(
                POSTGRES_HOST=postgres_ip,
                CLICKHOUSE_HOST=clickhouse_ip,
                LBT_HOST=littlebigtable_ip,
                RBT_HOST=rawbigtable_ip,
                REDIS_HOST=redis_ip,
            ) if command.startswith("sed -i ") else command
            for command in backend_start_commands
        ]
        seedemu_ethexplorer_backend._start_commands = backend_start_commands

        seedemu_ethexplorer_web = self._containers["seedemu-ethexplorer-web"]
        seedemu_ethexplorer_web.setContentAttribute(
            {
                "image": self.__web_image,
                "privileged": True,
                "pid": "host",
                "cap_add": ["ALL"],
                "depends_on": {
                    "clickhouse": {"condition": "service_healthy"},
                    "postgres": {"condition": "service_healthy"},
                    "redis": {"condition": "service_healthy"},
                    "littlebigtable": {"condition": "service_started"},
                    "rawbigtable": {"condition": "service_started"},
                    seedemu_ethexplorer_backend.getName(): {"condition": "service_healthy"},
                },
                "environment": environment.copy(),
                "ports": [f"{self._ports[0]}:{ETH_EXPLORER_WEB_INTERNAL_PORT}"],
                "build": f"./{seedemu_ethexplorer_web.getHostname()}",
                "logging": DOCKER_LOGGING,
            }
        )
        seedemu_ethexplorer_web.joinInternalNetwork(**self._emu_internal_network)
        frontend_start_commands = FRONTEND_START_SH.copy()
        frontend_start_commands[1] = frontend_start_commands[1].format(
            default_route=self._emu_internal_network["default_route"]
        )
        frontend_start_commands = [
            command.format(
                POSTGRES_HOST=postgres_ip,
                CLICKHOUSE_HOST=clickhouse_ip,
                LBT_HOST=littlebigtable_ip,
                RBT_HOST=rawbigtable_ip,
                REDIS_HOST=redis_ip,
            ) if command.startswith("sed -i ") else command
            for command in frontend_start_commands
        ]
        seedemu_ethexplorer_web._start_commands = frontend_start_commands

        for container in self._containers.values():
            container.service["labels"] = {ETH_EXPLORER_COMPONENT_LABEL: "ethexplorer"}

    def getBeaconHost(self) -> str:
        return self.__beacon_host

    def getGethHost(self) -> str:
        return self.__geth_host

    def setBeaconHost(self, beacon_host) -> None:
        self.__beacon_host = beacon_host

    def setGethHost(self, geth_host) -> None:
        self.__geth_host = geth_host


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
