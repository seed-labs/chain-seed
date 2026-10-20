"""Static outbound Geth peers declared using logical server names."""

import json
import shlex

from eth_account import Account
from eth_keys import keys

from .RuntimeConfig import integer


P2P_KEY_PATH = "/tmp/geth-p2p-nodekey"
P2P_CONFIG_PATH = "/tmp/geth-peers.toml"
P2P_PORT = 30303


class GethPeerConfig:
    """Mixin for servers that actually run a Geth execution client."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Created once per Server, persisted with an unrendered emulator dump.
        # Only activated/written when this server participates in static peering.
        self._p2p_private_key = bytes(Account.create().key)
        self._p2p_identity_enabled = False
        self._p2p_enode = None
        self._static_peers = None
        self._static_peer_enodes = []
        self._max_peers = None

    @staticmethod
    def _validatePeerName(vnode):
        if not isinstance(vnode, str) or not vnode.strip():
            raise ValueError("static peer must be a non-empty virtual node name")
        return vnode

    def setStaticPeers(self, vnodes):
        """Replace this client's persistent outbound peers (not an inbound ACL).

        Names resolve at render time, so referenced servers may be created later.
        An empty sequence explicitly configures an empty static list.
        Discovery is controlled independently by setNoDiscover().
        """
        self._assertConfigurable()
        if isinstance(vnodes, (str, bytes)):
            raise ValueError("static peers must be a sequence of virtual node names")
        try:
            peers = list(vnodes)
        except TypeError:
            raise ValueError("static peers must be a sequence of virtual node names") from None
        for vnode in peers:
            self._validatePeerName(vnode)
        self._static_peers = list(dict.fromkeys(peers))
        return self

    def addStaticPeer(self, vnode: str):
        """Add one persistent outbound peer; duplicate declarations are ignored."""
        self._assertConfigurable()
        self._validatePeerName(vnode)
        if self._static_peers is None:
            self._static_peers = []
        if vnode not in self._static_peers:
            self._static_peers.append(vnode)
        return self

    def getStaticPeers(self):
        """Return a copy of this instance's declared static peer names."""
        return list(self._static_peers or [])

    def setMaxPeers(self, count: int):
        """Set Geth's maxpeers option; zero disables its P2P network."""
        self._assertConfigurable()
        self._max_peers = integer(count, "max peers", minimum=0)
        return self

    def getP2PEnode(self):
        """Return the planned client enode after render, or None if unmanaged.

        This is a deployment declaration, not an observation of a live client.
        """
        return self._p2p_enode

    def _resolveP2PIdentity(self, address):
        public_key = keys.PrivateKey(self._p2p_private_key).public_key.to_bytes().hex()
        self._p2p_identity_enabled = True
        self._p2p_enode = f"enode://{public_key}@{address}:{P2P_PORT}"

    def _gethPeerCommand(self, command):
        arguments = []
        reserved = set()
        if self._p2p_identity_enabled:
            arguments += ["--nodekey", P2P_KEY_PATH]
            reserved.update(("--nodekey", "--nodekeyhex", "--port"))
        if self._static_peers is not None:
            arguments += ["--config", P2P_CONFIG_PATH]
            reserved.add("--config")
        if self._max_peers is not None:
            arguments += ["--maxpeers", str(self._max_peers)]
            reserved.add("--maxpeers")
        if self._max_peers == 0 and self._static_peers:
            raise ValueError("setMaxPeers(0) disables networking and cannot be used with non-empty static peers")
        for token in shlex.split(self._custom_geth_command_option or ""):
            flag = token.split("=", 1)[0]
            if flag in reserved:
                raise ValueError(f"Geth option {flag} conflicts with the Server's P2P configuration")
        return command + ((" " + shlex.join(arguments)) if arguments else "")

    def _installGethPeers(self, node):
        if self._p2p_identity_enabled:
            node.setFile(P2P_KEY_PATH, self._p2p_private_key.hex() + "\n")
            node.appendStartCommand(f"chmod 600 {P2P_KEY_PATH}")
        if self._static_peers is not None:
            node.setFile(P2P_CONFIG_PATH,
                         "[Node.P2P]\nStaticNodes = " + json.dumps(self._static_peer_enodes) + "\n")
