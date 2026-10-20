from __future__ import annotations

from typing import Optional

from seedemu.core.Node import Node
from seedemu.core.Service import Server

from .SolanaEnum import SolanaNodeRole
from ...common.systems import SOLANA


# Default ports for a Solana node. RPC/pubsub/gossip/faucet match the upstream
# defaults; the dynamic range carries TPU / turbine / repair traffic.
DEFAULT_RPC_PORT = 8899
DEFAULT_GOSSIP_PORT = 8001
DEFAULT_FAUCET_PORT = 9900
DEFAULT_DYNAMIC_PORT_LOW = 8002
DEFAULT_DYNAMIC_PORT_HIGH = 8030


class SolanaServer(Server):
    """!
    @brief Base class shared by all Solana node servers.

    A ``SolanaServer`` renders, at install time, a self-contained start script
    that drives the real Agave (``agave-validator``) toolchain. Connectivity
    information (this node's own IP, and the bootstrap node's gossip/RPC
    endpoint) is injected by :class:`SolanaNetwork` during the *configure*
    phase, where it is resolved from the virtual-node bindings. Nothing about
    addresses is hard-coded here (PRINCIPLES.md P4).
    """

    def __init__(self, network: "SolanaNetwork", role: SolanaNodeRole):
        super().__init__()
        self.setBaseSystem(SOLANA)
        self._network = network
        self._role = role

        # Ports (sensible defaults; overridable via the fluent API).
        self._rpc_port = DEFAULT_RPC_PORT
        self._gossip_port = DEFAULT_GOSSIP_PORT
        self._faucet_port = DEFAULT_FAUCET_PORT
        self._dyn_low = DEFAULT_DYNAMIC_PORT_LOW
        self._dyn_high = DEFAULT_DYNAMIC_PORT_HIGH

        # Runtime binding information (populated during configure()).
        self._self_ip: Optional[str] = None
        self._bootstrap_ip: Optional[str] = None
        self._bootstrap_gossip_port: Optional[int] = None
        self._bootstrap_rpc_port: Optional[int] = None

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    @property
    def role(self) -> SolanaNodeRole:
        return self._role

    def is_bootstrap(self) -> bool:
        return self._role == SolanaNodeRole.BOOTSTRAP

    def get_gossip_port(self) -> int:
        return self._gossip_port

    def get_rpc_port(self) -> int:
        return self._rpc_port

    # ------------------------------------------------------------------ #
    # Fluent configuration API (PRINCIPLES.md P3)
    # ------------------------------------------------------------------ #
    def setRpcPort(self, port: int) -> "SolanaServer":
        """!@brief Set the JSON-RPC port (default 8899)."""
        self._rpc_port = port
        return self

    def setGossipPort(self, port: int) -> "SolanaServer":
        """!@brief Set the gossip port (default 8001)."""
        self._gossip_port = port
        return self

    def setDynamicPortRange(self, low: int, high: int) -> "SolanaServer":
        """!@brief Set the dynamic (TPU/turbine/repair) port range."""
        self._dyn_low = low
        self._dyn_high = high
        return self

    # ------------------------------------------------------------------ #
    # Runtime-information setters (called by SolanaNetwork.configure)
    # ------------------------------------------------------------------ #
    def set_self_ip(self, ip: str):
        self._self_ip = ip

    def set_bootstrap_endpoint(self, ip: str, gossip_port: int, rpc_port: int):
        self._bootstrap_ip = ip
        self._bootstrap_gossip_port = gossip_port
        self._bootstrap_rpc_port = rpc_port

    # ------------------------------------------------------------------ #
    # Installation
    # ------------------------------------------------------------------ #
    def install(self, node: Node):  # pragma: no cover - executed by runtime
        raise NotImplementedError("install must be implemented by a subclass")


class SolanaBootstrapServer(SolanaServer):
    """!
    @brief The genesis / bootstrap validator of a private Solana cluster.

    Creates all genesis keypairs, builds the genesis ledger with
    ``solana-genesis``, runs ``solana-faucet`` so other validators can fund
    themselves, and starts ``agave-validator`` as the cluster's first staked
    validator and gossip entrypoint.
    """

    def __init__(self, network: "SolanaNetwork"):
        super().__init__(network, SolanaNodeRole.BOOTSTRAP)
        self._faucet_lamports = 500000000000000000
        self._hashes_per_tick = "sleep"  # low-CPU PoH, suited to emulation (P9)

    def setFaucetLamports(self, lamports: int) -> "SolanaBootstrapServer":
        """!@brief Set the amount of lamports held by the genesis faucet."""
        self._faucet_lamports = lamports
        return self

    def setHashesPerTick(self, value: str) -> "SolanaBootstrapServer":
        """!@brief Set solana-genesis --hashes-per-tick ("sleep", "auto", or a number)."""
        self._hashes_per_tick = value
        return self

    def install(self, node: Node):  # pragma: no cover - executed by runtime
        assert self._self_ip is not None, \
            "SolanaBootstrapServer not configured; did SolanaNetwork.configure() run?"

        script = _BOOTSTRAP_SCRIPT.format(
            self_ip=self._self_ip,
            rpc_port=self._rpc_port,
            gossip_port=self._gossip_port,
            faucet_port=self._faucet_port,
            dyn_low=self._dyn_low,
            dyn_high=self._dyn_high,
            faucet_lamports=self._faucet_lamports,
            hashes_per_tick=self._hashes_per_tick,
        )
        node.setFile("/opt/solana/run-bootstrap.sh", script)
        node.addBuildCommandAtEnd("chmod +x /opt/solana/run-bootstrap.sh")
        node.appendStartCommand("/opt/solana/run-bootstrap.sh", fork=True)


class SolanaValidatorServer(SolanaServer):
    """!
    @brief A validator that joins an existing private cluster.

    Waits for the bootstrap RPC, generates its own identity / vote keypairs,
    funds its identity from the faucet (an airdrop relayed through the
    bootstrap RPC), creates its vote account, and then starts
    ``agave-validator`` with the bootstrap node as its gossip entrypoint.
    """

    def __init__(self, network: "SolanaNetwork"):
        super().__init__(network, SolanaNodeRole.VALIDATOR)
        self._node_sol = 500  # SOL airdropped for fees + vote-account rent

    def setNodeSol(self, sol: int) -> "SolanaValidatorServer":
        """!@brief Set the amount of SOL this validator airdrops to itself."""
        self._node_sol = sol
        return self

    def install(self, node: Node):  # pragma: no cover - executed by runtime
        assert self._self_ip is not None, \
            "SolanaValidatorServer not configured; did SolanaNetwork.configure() run?"
        assert self._bootstrap_ip is not None, \
            "SolanaValidatorServer has no bootstrap endpoint; the network needs a bootstrap validator."

        script = _VALIDATOR_SCRIPT.format(
            self_ip=self._self_ip,
            rpc_port=self._rpc_port,
            gossip_port=self._gossip_port,
            dyn_low=self._dyn_low,
            dyn_high=self._dyn_high,
            entrypoint_ip=self._bootstrap_ip,
            boot_gossip_port=self._bootstrap_gossip_port,
            boot_rpc_port=self._bootstrap_rpc_port,
            node_sol=self._node_sol,
        )
        node.setFile("/opt/solana/run-validator.sh", script)
        node.addBuildCommandAtEnd("chmod +x /opt/solana/run-validator.sh")
        node.appendStartCommand("/opt/solana/run-validator.sh", fork=True)


# --------------------------------------------------------------------------- #
# Start-script templates.
#
# These reproduce the exact command sequence used by Agave's own
# multinode-demo scripts (setup.sh / bootstrap-validator.sh / validator.sh),
# adapted for a containerised, fully-private cluster:
#   * --allow-private-addr        : permit RFC1918 (10.x) gossip in the emulator
#   * --no-poh-speed-test / --no-os-network-limits-test : skip host benchmarks
#   * --hashes-per-tick sleep     : low-CPU PoH for emulation
# --------------------------------------------------------------------------- #

_BOOTSTRAP_SCRIPT = r"""#!/bin/bash
# seedemu-solana: genesis / bootstrap validator
set -euo pipefail

CONFIG_DIR=/opt/solana/config
LEDGER_DIR="$CONFIG_DIR/bootstrap-validator"
SELF_IP={self_ip}
RPC_PORT={rpc_port}
GOSSIP_PORT={gossip_port}
FAUCET_PORT={faucet_port}
DYNAMIC_PORT_RANGE={dyn_low}-{dyn_high}

mkdir -p "$LEDGER_DIR"

# 1) Generate genesis keypairs (idempotent across container restarts).
[ -f "$CONFIG_DIR/faucet.json" ]        || solana-keygen new --no-passphrase -fso "$CONFIG_DIR/faucet.json"
[ -f "$LEDGER_DIR/identity.json" ]      || solana-keygen new --no-passphrase -so  "$LEDGER_DIR/identity.json"
[ -f "$LEDGER_DIR/vote-account.json" ]  || solana-keygen new --no-passphrase -so  "$LEDGER_DIR/vote-account.json"
[ -f "$LEDGER_DIR/stake-account.json" ] || solana-keygen new --no-passphrase -so  "$LEDGER_DIR/stake-account.json"

# 2) Build the genesis ledger (only once).
if [ ! -f "$LEDGER_DIR/genesis.bin" ]; then
  solana-genesis \
    --max-genesis-archive-unpacked-size 1073741824 \
    --enable-warmup-epochs \
    --bootstrap-validator "$LEDGER_DIR/identity.json" "$LEDGER_DIR/vote-account.json" "$LEDGER_DIR/stake-account.json" \
    --ledger "$LEDGER_DIR" \
    --faucet-pubkey "$CONFIG_DIR/faucet.json" \
    --faucet-lamports {faucet_lamports} \
    --hashes-per-tick {hashes_per_tick} \
    --cluster-type development
fi

# 3) Point the local CLI at this node's RPC.
solana config set --url "http://127.0.0.1:$RPC_PORT" >/dev/null 2>&1 || true

# 4) Start the faucet so other validators can fund themselves.
solana-faucet --keypair "$CONFIG_DIR/faucet.json" >/var/log/solana-faucet.log 2>&1 &

echo "[seedemu-solana] starting bootstrap validator on $SELF_IP (rpc:$RPC_PORT gossip:$GOSSIP_PORT)"

# 5) Start the bootstrap validator (foreground; keeps the container alive).
exec agave-validator \
  --identity "$LEDGER_DIR/identity.json" \
  --vote-account "$LEDGER_DIR/vote-account.json" \
  --ledger "$LEDGER_DIR" \
  --rpc-port "$RPC_PORT" \
  --rpc-bind-address 0.0.0.0 \
  --rpc-faucet-address "127.0.0.1:$FAUCET_PORT" \
  --gossip-host "$SELF_IP" \
  --gossip-port "$GOSSIP_PORT" \
  --dynamic-port-range "$DYNAMIC_PORT_RANGE" \
  --snapshot-interval-slots 200 \
  --no-incremental-snapshots \
  --full-rpc-api \
  --enable-rpc-transaction-history \
  --allow-private-addr \
  --no-poh-speed-test \
  --no-os-network-limits-test \
  --no-wait-for-vote-to-start-leader \
  --log -
"""

_VALIDATOR_SCRIPT = r"""#!/bin/bash
# seedemu-solana: validator joining the private cluster
set -uo pipefail

CONFIG_DIR=/opt/solana/config
LEDGER_DIR="$CONFIG_DIR/validator"
SELF_IP={self_ip}
RPC_PORT={rpc_port}
GOSSIP_PORT={gossip_port}
DYNAMIC_PORT_RANGE={dyn_low}-{dyn_high}
ENTRYPOINT={entrypoint_ip}:{boot_gossip_port}
RPC_URL=http://{entrypoint_ip}:{boot_rpc_port}
NODE_SOL={node_sol}

mkdir -p "$LEDGER_DIR"

# Keypairs for this validator (idempotent).
[ -f "$LEDGER_DIR/identity.json" ]     || solana-keygen new --no-passphrase -so "$LEDGER_DIR/identity.json"
[ -f "$LEDGER_DIR/vote-account.json" ] || solana-keygen new --no-passphrase -so "$LEDGER_DIR/vote-account.json"
[ -f "$LEDGER_DIR/withdrawer.json" ]   || solana-keygen new --no-passphrase -so "$LEDGER_DIR/withdrawer.json"

# Wait for the bootstrap RPC to come up.
echo "[seedemu-solana] waiting for bootstrap RPC at $RPC_URL ..."
until solana --url "$RPC_URL" cluster-version >/dev/null 2>&1; do sleep 2; done
echo "[seedemu-solana] bootstrap reachable; setting up validator accounts."

# Fund identity from the faucet (relayed via bootstrap RPC) and create the
# vote account, but only the first time.
IDENTITY_PUBKEY=$(solana-keygen pubkey "$LEDGER_DIR/identity.json")
if ! solana --url "$RPC_URL" vote-account "$LEDGER_DIR/vote-account.json" >/dev/null 2>&1; then
  until solana --url "$RPC_URL" airdrop "$NODE_SOL" "$IDENTITY_PUBKEY" >/dev/null 2>&1; do
    echo "[seedemu-solana] airdrop not ready, retrying ..."; sleep 2
  done
  solana --url "$RPC_URL" create-vote-account \
    --fee-payer "$LEDGER_DIR/identity.json" \
    "$LEDGER_DIR/vote-account.json" "$LEDGER_DIR/identity.json" "$LEDGER_DIR/withdrawer.json" \
    || true
fi

echo "[seedemu-solana] starting validator on $SELF_IP (entrypoint $ENTRYPOINT)"

exec agave-validator \
  --identity "$LEDGER_DIR/identity.json" \
  --vote-account "$LEDGER_DIR/vote-account.json" \
  --ledger "$LEDGER_DIR" \
  --entrypoint "$ENTRYPOINT" \
  --rpc-port "$RPC_PORT" \
  --rpc-bind-address 0.0.0.0 \
  --gossip-host "$SELF_IP" \
  --gossip-port "$GOSSIP_PORT" \
  --dynamic-port-range "$DYNAMIC_PORT_RANGE" \
  --no-incremental-snapshots \
  --full-rpc-api \
  --enable-rpc-transaction-history \
  --allow-private-addr \
  --no-poh-speed-test \
  --no-os-network-limits-test \
  --log -
"""
