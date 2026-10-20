"""Per-server client options, rendered before Docker compilation.

These mixins store no chain-wide defaults. Unset Geth/worker options leave the
client's own defaults in effect; Beacon historical reconstruction retains the
existing ChainSeed default.
"""

from decimal import Decimal, InvalidOperation
from ipaddress import ip_address
import shlex


def integer(value, name, minimum=1, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        limit = f"between {minimum} and {maximum}" if maximum is not None else f">= {minimum}"
        raise ValueError(f"{name} must be an integer {limit}")
    return value


class EthereumRuntimeConfig:
    def _initRuntimeConfig(self):
        self._configuration_frozen = False
        self._cache_mib = None
        self._go_memory_limit_mib = None
        self._rpc_tx_fee_cap = None
        self._bootstrap_attempts = 60
        self._bootstrap_interval = 10
        self._bootstrap_connect_timeout = None
        self._bootstrap_request_timeout = None

    def _assertConfigurable(self):
        if self._configuration_frozen:
            raise RuntimeError("Server configuration is frozen; configure it before emu.render()")

    def _freezeConfiguration(self):
        self._configuration_frozen = True

    def setCacheMiB(self, value: int):
        """Set Geth's cache budget in MiB. This is not a container limit."""
        self._assertConfigurable()
        self._cache_mib = integer(value, "cache MiB", minimum=0)
        return self

    def setGoMemoryLimitMiB(self, value: int):
        """Set GOMEMLIMIT for the Geth process only (Go's soft memory budget)."""
        self._assertConfigurable()
        self._go_memory_limit_mib = integer(value, "Go memory limit MiB")
        return self

    def setRpcTxFeeCap(self, value):
        """Set Geth's RPC transaction fee cap in ETH; zero disables the cap."""
        self._assertConfigurable()
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError("RPC transaction fee cap must be a finite non-negative number") from None
        if not amount.is_finite() or amount < 0:
            raise ValueError("RPC transaction fee cap must be a finite non-negative number")
        self._rpc_tx_fee_cap = format(amount, "f")
        return self

    def setBootstrapRetryPolicy(self, *, attempts=60, interval_seconds=10,
                                connect_timeout_seconds=None, request_timeout_seconds=None):
        """Configure testnet-download retries and curl timeouts for this server.

        Optional timeouts are seconds; None retains curl's default. Each call
        replaces this server's complete download policy.
        """
        self._assertConfigurable()
        attempts = integer(attempts, "bootstrap attempts")
        interval = integer(interval_seconds, "bootstrap interval seconds", minimum=0)
        for value, name in ((connect_timeout_seconds, "connect timeout seconds"),
                            (request_timeout_seconds, "request timeout seconds")):
            if value is not None:
                integer(value, name)
        self._bootstrap_attempts = attempts
        self._bootstrap_interval = interval
        self._bootstrap_connect_timeout = connect_timeout_seconds
        self._bootstrap_request_timeout = request_timeout_seconds
        return self

    def _bootstrapTemplateOptions(self):
        arguments = []
        if self._bootstrap_connect_timeout is not None:
            arguments += ["--connect-timeout", str(self._bootstrap_connect_timeout)]
        if self._bootstrap_request_timeout is not None:
            arguments += ["--max-time", str(self._bootstrap_request_timeout)]
        return dict(retry_attempts=self._bootstrap_attempts,
                    retry_interval=self._bootstrap_interval,
                    curl_options=(shlex.join(arguments) + " ") if arguments else "")

    def _gethRuntimeCommand(self, command):
        arguments = []
        if self._cache_mib is not None:
            arguments += ["--cache", str(self._cache_mib)]
        if self._rpc_tx_fee_cap is not None:
            arguments += ["--rpc.txfeecap", self._rpc_tx_fee_cap]
        # Existing custom options share the same command. Reject ambiguous
        # ownership instead of relying on the client's duplicate-flag behavior.
        custom = self._custom_geth_command_option or ""
        configured = set(arguments[::2])
        for token in shlex.split(custom):
            if token.split("=", 1)[0] in configured:
                raise ValueError(f"Geth option {token.split('=', 1)[0]} is also configured by a Server API")
        if arguments:
            command += " " + shlex.join(arguments)
        if self._go_memory_limit_mib is not None:
            command = f"env GOMEMLIMIT={self._go_memory_limit_mib}MiB " + command
        return command


class BeaconRuntimeConfig:
    def _initBeaconRuntimeConfig(self):
        self._processor_max_workers = None
        self._reconstruct_historic_states = True
        self._metrics_enabled = False
        self._metrics_port = 5054
        self._metrics_address = "0.0.0.0"

    def setProcessorMaxWorkers(self, value: int):
        """Limit Lighthouse Beacon Processor workers for this instance."""
        self._assertConfigurable()
        self._processor_max_workers = integer(value, "processor max workers")
        return self

    def setReconstructHistoricStates(self, enabled: bool = True):
        """Control Lighthouse's historical-state reconstruction flag."""
        self._assertConfigurable()
        if type(enabled) is not bool:
            raise ValueError("historical-state reconstruction must be a bool")
        self._reconstruct_historic_states = enabled
        return self

    def isReconstructHistoricStatesEnabled(self) -> bool:
        """Whether this Beacon is configured to reconstruct historical states."""
        return self._reconstruct_historic_states

    def enableMetrics(self, enabled: bool = True, *, port: int = 5054, address: str = "0.0.0.0"):
        """Enable/disable the Beacon metrics endpoint on its emulated interface."""
        self._assertConfigurable()
        if type(enabled) is not bool:
            raise ValueError("metrics enabled must be a bool")
        port = integer(port, "metrics port", maximum=65535)
        if not isinstance(address, str):
            raise ValueError("metrics address must be an IPv4 or IPv6 address")
        try:
            ip_address(address)
        except ValueError:
            raise ValueError("metrics address must be an IPv4 or IPv6 address") from None
        self._metrics_enabled = enabled
        self._metrics_port = port
        self._metrics_address = str(address)
        return self

    def getMetricsPort(self):
        """Return this Beacon's metrics port, or None when metrics are disabled."""
        return self._metrics_port if self._metrics_enabled else None

    def _beaconRuntimeArguments(self):
        arguments = []
        if self._reconstruct_historic_states:
            arguments.append("--reconstruct-historic-states")
        if self._processor_max_workers is not None:
            arguments += ["--beacon-processor-max-workers", str(self._processor_max_workers)]
        if self._metrics_enabled:
            arguments += ["--metrics", "--metrics-address", self._metrics_address,
                          "--metrics-port", str(self._metrics_port)]
        return shlex.join(arguments)
