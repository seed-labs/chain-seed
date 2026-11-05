"""Ethereum explorer deployed through SeedEmu's ContainerBundle interface."""

from copy import deepcopy
from dataclasses import dataclass

from seedemu.containerBundle import ContainerBundle

CLICKHOUSE = "clickhouse"
POSTGRES = "postgres"
REDIS = "redis"
LITTLEBIGTABLE = "littlebigtable"
RAWBIGTABLE = "rawbigtable"
ETHEXPLORER_API_SERVER = "ethexplorer-api-server"
ETHEXPLORER_WEB = "ethexplorer-web"

SEEDEMU_ETH_EXPLORER_BACKEND_IMAGE = "handsonsecurity/seedemu-ethexplorer-backend:1.0"
SEEDEMU_ETH_EXPLORER_WEB_IMAGE = "handsonsecurity/seedemu-ethexplorer-web:1.0"
CLICKHOUSE_IMAGE = "clickhouse/clickhouse-server:25.11"
POSTGRES_IMAGE = "postgres:15.2-alpine"
REDIS_IMAGE = "redis:7-alpine"
LITTLE_BIGTABLE_IMAGE = "gobitfly/little_bigtable:latest"

SEEDEMU_ETH_EXPLORER_WEB_INTERNAL_PORT = 5000
DOCKER_LOGGOING_CONFIG = {
    "driver": "json-file",
    "options": {"max-size": "200m", "max-file": 1},
}
DEFAULT_EXTERNAL_NETWORK = {
    "network_name": "ethExplorer_network",
    "prefix": "172.20.0.0/24",
    "ip_addresses": [f"172.20.0.{i}" for i in range(10, 17)],
    "default_route": "172.20.0.1",
    "type": "bridge",
    "network_config": {
        "driver": "bridge",
        "ipam": {
            "config": [
                {
                    "subnet": "172.20.0.0/24",
                    "gateway": "172.20.0.1",
                }
            ]
        },
    },
}
BACKEND_START_SH = [
    "#!/bin/sh",
    "stopit() {",
    '  echo "trapped SIGINT"',
    "  exit 0",
    "}",
    "trap stopit SIGINT",
    'echo "run provision-explorer-config-custom.sh ..."',
    "cd /app/local_deployment",
    # Replace service hosts while preserving values resolved by provisioning.
    "sed -i "
    "-e '/^clickhouse:/,/^[^[:space:]#]/ s|^\\([[:space:]]*host:\\).*|\\1 {CLICKHOUSE_HOST}|' "
    "-e '/^bigtable:/,/^[[:space:]]*emulatorHost:/ s|^\\([[:space:]]*emulatorHost:\\).*|\\1 {LBT_HOST}|' "
    "-e '/^rawBigtable:/,/^[[:space:]]*emulatorHost:/ s|^\\([[:space:]]*emulatorHost:\\).*|\\1 {RBT_HOST}|' "
    "-e \"s|^redisCacheEndpoint: '.*:|redisCacheEndpoint: '{REDIS_HOST}:|\" "
    "-e \"s|^redisSessionStoreEndpoint: '.*:|redisSessionStoreEndpoint: '{REDIS_HOST}:|\" "
    "/app/local_deployment/provision-explorer-config-custom.sh || exit 1",
    "chmod +x provision-explorer-config-custom.sh",
    "./provision-explorer-config-custom.sh",
    "if [ $? -eq 0 ]; then",
    '  echo "SUCCESS: script executed normally"',
    "else",
    '  echo "ERROR: script failed"',
    "  exit 1",
    "fi",
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
    "stopit() {",
    '  echo "trapped SIGINT"',
    "  exit 0",
    "}",
    "trap stopit SIGINT",
    'echo "run provision-explorer-config-custom.sh ..."',
    "cd /app/local-deployment",
    # Replace service hosts while preserving values resolved by provisioning.
    "sed -i "
    "-e '/^clickhouse:/,/^[^[:space:]#]/ s|^\\([[:space:]]*host:\\).*|\\1 {CLICKHOUSE_HOST}|' "
    "-e '/^bigtable:/,/^[[:space:]]*emulatorHost:/ s|^\\([[:space:]]*emulatorHost:\\).*|\\1 {LBT_HOST}|' "
    "-e '/^rawBigtable:/,/^[[:space:]]*emulatorHost:/ s|^\\([[:space:]]*emulatorHost:\\).*|\\1 {RBT_HOST}|' "
    "-e \"s|^redisCacheEndpoint: '.*:|redisCacheEndpoint: '{REDIS_HOST}:|\" "
    "-e \"s|^redisSessionStoreEndpoint: '.*:|redisSessionStoreEndpoint: '{REDIS_HOST}:|\" "
    "/app/local-deployment/provision-explorer-config-custom.sh || exit 1",
    "chmod +x provision-explorer-config-custom.sh",
    "./provision-explorer-config-custom.sh",
    "if [ $? -eq 0 ]; then",
    '  echo "SUCCESS: script executed normally"',
    "else",
    '  echo "ERROR: script failed"',
    "  exit 1",
    "fi",
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


class EthExplorer(ContainerBundle):
    """!
    @brief Bundle for the Ethereum Beacon Chain explorer stack.

    Includes PostgreSQL, ClickHouse, Redis, two Bigtable emulators, an indexing
    backend, and the Web frontend.
    """

    def __init__(self, emulator, suffix="eth.explorer"):
        """!
        @brief Create an explorer bundle for an Ethereum emulator.

        @param emulator emulator containing ``EthereumService`` and a usable
            emulated host network.
        @param suffix suffix appended to generated container hostnames.
        """
        super().__init__(emulator=emulator, suffix=suffix)
        self._default_external_network = DEFAULT_EXTERNAL_NETWORK
        service_names = [
            CLICKHOUSE,
            POSTGRES,
            REDIS,
            LITTLEBIGTABLE,
            RAWBIGTABLE,
            ETHEXPLORER_API_SERVER,
            ETHEXPLORER_WEB,
        ]
        for service_name in service_names:
            self._createContainer(service_name, suffix)
        self._required_port_count = 1
        self._required_internal_address_count = 2
        self.__beacon_host = self.__geth_host = ""

    def configure(self) -> None:
        """!
        @brief Validate settings and configure explorer services.

        @raises ValueError when the required host port is unavailable.
        """
        super().configure()

        eth = self._emulator.getLayer("EthereumService")
        blockchain = eth.getBlockchainByName(eth.getBlockchainNames()[0])
        if not self.__beacon_host:
            self.__beacon_host = blockchain.getBeaconBootNodeIP()[0]
        if not self.__geth_host:
            self.__geth_host = blockchain.getGethBootNodeIP()[0]

        if not self._external_networks:
            self._external_networks.append(DEFAULT_EXTERNAL_NETWORK)
        external_network = self._external_networks[0]
        external_network_name = external_network["network_name"]
        ip_addresses = external_network["ip_addresses"]
        for index, container in enumerate(self._containers.values()):
            container.joinExternalNetwork(
                network_name=external_network_name,
                hostname=container.getHostname(),
                ip_address=ip_addresses[index],
            )
            if container.getName() in [ETHEXPLORER_API_SERVER, ETHEXPLORER_WEB]:
                self.addEtcHostsRecord(container.getName() + '-e' + self._suffix, ip_addresses[0])

        clickhouse = self._containers[CLICKHOUSE]
        clickhouse.setStartScriptName('')
        clickhouse.updateServiceConfig(
            {
                "image": CLICKHOUSE_IMAGE,
                "environment": {
                    "CLICKHOUSE_DB": "beaconchain",
                    "CLICKHOUSE_USER": "beacon",
                    "CLICKHOUSE_PASSWORD": "pass",
                },
                "healthcheck": {
                    "test": [
                        "CMD",
                        "wget",
                        "--spider",
                        "-q",
                        "http://localhost:8123/ping",
                    ],
                    "interval": "30s",
                    "timeout": "10s",
                    "retries": 3,
                },
            }
        )

        postgres = self._containers[POSTGRES]
        postgres.setStartScriptName('')
        postgres.updateServiceConfig(
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

        redis = self._containers[REDIS]
        redis.setStartScriptName('')
        redis.updateServiceConfig(
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

        littlebigtable = self._containers[LITTLEBIGTABLE]
        littlebigtable.setStartScriptName('')
        littlebigtable.updateServiceConfig(
            {
                "image": LITTLE_BIGTABLE_IMAGE,
                "depends_on": [postgres.getHostname()],
            }
        )

        rawbigtable = self._containers[RAWBIGTABLE]
        rawbigtable.setStartScriptName('')
        rawbigtable.updateServiceConfig(
            {
                "image": LITTLE_BIGTABLE_IMAGE,
                "depends_on": [postgres.getHostname()],
            }
        )

        clickhouse_ip = clickhouse._service["networks"][external_network_name][
            "ipv4_address"
        ]
        postgres_ip = postgres._service["networks"][external_network_name][
            "ipv4_address"
        ]
        redis_ip = redis._service["networks"][external_network_name]["ipv4_address"]
        littlebigtable_ip = littlebigtable._service["networks"][external_network_name][
            "ipv4_address"
        ]
        rawbigtable_ip = rawbigtable._service["networks"][external_network_name][
            "ipv4_address"
        ]

        assert self._internal_networks, "The emulator network must be added."
        internal_network = self._internal_networks[0]
        
        ethexplorer_api_server = self._containers[ETHEXPLORER_API_SERVER]
        ethexplorer_api_server.updateServiceConfig(
            {
                "image": SEEDEMU_ETH_EXPLORER_BACKEND_IMAGE,
                "privileged": True,
                "pid": "host",
                "cap_add": ["ALL"],
                "healthcheck": {
                    "test": [
                        "CMD-SHELL",
                        f"""PGPASSWORD=pass psql -h {postgres.getHostname()} -U postgres -d db -tAc "SELECT 1 FROM information_schema.tables WHERE table_name='blocks';" | grep -q 1""",
                    ],
                    "interval": "5s",
                    "timeout": "3s",
                    "retries": 20,
                    "start_period": "10s",
                },
                "depends_on": {
                    clickhouse.getHostname(): {"condition": "service_healthy"},
                    postgres.getHostname(): {"condition": "service_healthy"},
                    redis.getHostname(): {"condition": "service_healthy"},
                    littlebigtable.getHostname(): {"condition": "service_started"},
                    rawbigtable.getHostname(): {"condition": "service_started"},
                },
                "environment": {
                    "CL_HOST": self.__beacon_host,
                    "EL_HOST": self.__geth_host,
                    "POSTGRES_HOST": postgres_ip,
                },
                "build": f"./{ethexplorer_api_server.getHostname()}",
                "logging": DOCKER_LOGGOING_CONFIG,
            }
        )
        ethexplorer_api_server.joinInternalNetwork(
            asn=internal_network["asn"],
            network_name=internal_network["network_name"],
            hostname=ethexplorer_api_server.getHostname(),
            ip_address=internal_network["ip_addresses"][0],
            default_route=internal_network["default_route"],
        )
        # Set "hostname" as an alias, which is concise and convenient for accessing the ethexplorer_api_server container in the emulator.
        self.addEtcHostsRecord(ethexplorer_api_server.getHostname(), ip_addresses[0])
        backend_start_commands = BACKEND_START_SH.copy()
        backend_start_commands = [
            (
                command.format(
                    CLICKHOUSE_HOST=clickhouse_ip,
                    LBT_HOST=littlebigtable_ip,
                    RBT_HOST=rawbigtable_ip,
                    REDIS_HOST=redis_ip,
                )
                if command.startswith("sed -i ")
                else command
            )
            for command in backend_start_commands
        ]
        ethexplorer_api_server._start_commands = backend_start_commands

        ethexplorer_web = self._containers[ETHEXPLORER_WEB]
        ethexplorer_web.updateServiceConfig(
            {
                "image": SEEDEMU_ETH_EXPLORER_WEB_IMAGE,
                "privileged": True,
                "pid": "host",
                "cap_add": ["ALL"],
                "depends_on": {
                    clickhouse.getHostname(): {"condition": "service_healthy"},
                    postgres.getHostname(): {"condition": "service_healthy"},
                    redis.getHostname(): {"condition": "service_healthy"},
                    littlebigtable.getHostname(): {"condition": "service_started"},
                    rawbigtable.getHostname(): {"condition": "service_started"},
                    ethexplorer_api_server.getHostname(): {
                        "condition": "service_healthy"
                    },
                },
                "environment": {
                    "CL_HOST": self.__beacon_host,
                    "EL_HOST": self.__geth_host,
                    "POSTGRES_HOST": postgres_ip,
                },
                "ports": [
                    f"{self._ports.pop()}:{SEEDEMU_ETH_EXPLORER_WEB_INTERNAL_PORT}"
                ],
                "build": f"./{ethexplorer_web.getHostname()}",
                "logging": DOCKER_LOGGOING_CONFIG,
            }
        )
        ethexplorer_web.joinInternalNetwork(
            asn=internal_network["asn"],
            network_name=internal_network["network_name"],
            hostname=ethexplorer_web.getHostname(),
            ip_address=internal_network["ip_addresses"][1],
            default_route=internal_network["default_route"],
        )
        # Set "hostname" as an alias, which is concise and convenient for accessing the ethexplorer_web container in the emulator.
        self.addEtcHostsRecord(ethexplorer_web.getHostname(), ip_addresses[1])
        frontend_start_commands = FRONTEND_START_SH.copy()
        frontend_start_commands = [
            (
                command.format(
                    CLICKHOUSE_HOST=clickhouse_ip,
                    LBT_HOST=littlebigtable_ip,
                    RBT_HOST=rawbigtable_ip,
                    REDIS_HOST=redis_ip,
                )
                if command.startswith("sed -i ")
                else command
            )
            for command in frontend_start_commands
        ]
        ethexplorer_web._start_commands = frontend_start_commands

    def getBeaconHost(self) -> str:
        """!
        @brief Return the selected consensus-layer Beacon host.

        @returns Beacon node hostname or IP address.
        """
        return self.__beacon_host

    def getGethHost(self) -> str:
        """!
        @brief Return the selected execution-layer Geth host.

        @returns Geth node hostname or IP address.
        """
        return self.__geth_host

    def setBeaconHost(self, beacon_host) -> None:
        """!
        @brief Override the Beacon host used by backend and frontend.

        @param beacon_host Beacon node hostname or IP address.
        """
        self.__beacon_host = beacon_host

    def setGethHost(self, geth_host) -> None:
        """!
        @brief Override the Geth host used by backend and frontend.

        @param geth_host Geth node hostname or IP address.
        """
        self.__geth_host = geth_host
