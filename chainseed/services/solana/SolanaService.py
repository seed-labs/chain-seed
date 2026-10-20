from __future__ import annotations

from typing import Dict, List, Optional

from seedemu.core.Emulator import Emulator
from seedemu.core.Node import Node
from seedemu.core.Service import Server, Service
from seedemu.core.enums import NetworkType

from .SolanaEnum import SolanaNodeRole, SolanaNetworkType
from .SolanaServer import SolanaServer, SolanaBootstrapServer, SolanaValidatorServer


class SolanaService(Service):
    """!
    @brief Entry point for the Solana blockchain service.

    Mirrors the structure of ``EthereumService`` / ``MoneroService``: the
    service tracks the mapping between virtual nodes and one or more private
    Solana clusters (:class:`SolanaNetwork`). During the *configure* phase it
    resolves the virtual-node bindings and wires every validator to the
    cluster's bootstrap node; during *render* each server installs the real
    Agave toolchain onto its physical node.

    Nodes declare the ChainSeed Solana runtime system. `ChainSeedDocker` maps it
    to the platform-specific image containing the pinned Agave binaries (see
    docker_images/solana).
    """

    def __init__(self):
        super().__init__()
        self.__networks: Dict[str, "SolanaNetwork"] = {}
        # The cluster needs the base topology and routing to exist first
        # (PRINCIPLES.md P2: declare render-order dependencies explicitly).
        self.addDependency('Base', False, False)
        self.addDependency('Routing', False, False)

    # ------------------------------------------------------------------ #
    # Service interface
    # ------------------------------------------------------------------ #
    def getName(self) -> str:
        return "SolanaService"

    def _createServer(self) -> Server:
        raise AssertionError(
            "Create Solana nodes via SolanaNetwork.createBootstrapValidator()/createValidator()"
        )

    def configure(self, emulator: Emulator):
        # Resolve cluster connectivity first (needs the bindings), then let the
        # base Service bind/configure each pending target.
        for network in self.__networks.values():
            network.configure(emulator)
        super().configure(emulator)

    def _doInstall(self, node: Node, server: Server):
        self._log("install {} on as{}/{}".format(
            server.__class__.__name__, node.getAsn(), node.getName()))
        super()._doInstall(node, server)

    # ------------------------------------------------------------------ #
    # Blockchain management
    # ------------------------------------------------------------------ #
    def createBlockchain(
        self,
        name: str,
        net_type: SolanaNetworkType = SolanaNetworkType.DEVELOPMENT,
    ) -> "SolanaNetwork":
        """!
        @brief Create and register a logical private Solana cluster.

        @param name unique cluster identifier.
        @param net_type cluster type (only DEVELOPMENT is supported for now).

        @returns the new :class:`SolanaNetwork`.
        """
        assert name not in self.__networks, f"Duplicated Solana blockchain name: {name}"
        network = SolanaNetwork(self, name, net_type)
        self.__networks[name] = network
        return network

    def getBlockchainNames(self) -> List[str]:
        """!@brief Return the names of all registered clusters."""
        return list(self.__networks.keys())

    def getBlockchain(self, name: str) -> "SolanaNetwork":
        """!@brief Return the cluster with the given name."""
        return self.__networks[name]

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _register_node(self, vnode: str, server: SolanaServer) -> SolanaServer:
        assert vnode not in self._pending_targets, \
            f"Duplicated Solana virtual node: {vnode}"
        self._pending_targets[vnode] = server
        return server


class SolanaNetwork:
    """!
    @brief Representation of a single private Solana cluster.

    Holds the cluster's nodes and, during ``configure``, resolves each virtual
    node's bound IP and points every validator at the bootstrap node's gossip
    entrypoint and RPC. Exactly one bootstrap validator is required per cluster.
    """

    def __init__(self, service: SolanaService, name: str, net_type: SolanaNetworkType):
        self._service = service
        self._name = name
        self._net_type = net_type
        self._nodes: Dict[str, SolanaServer] = {}
        self._bootstrap_vnode: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Public API (PRINCIPLES.md P3 / P4)
    # ------------------------------------------------------------------ #
    def getName(self) -> str:
        return self._name

    def createBootstrapValidator(self, vnode: str) -> SolanaBootstrapServer:
        """!
        @brief Create the cluster's genesis / bootstrap validator.

        Only one bootstrap validator may exist per cluster.

        @param vnode virtual node name (resolved to a physical node by a Binding).
        @returns the :class:`SolanaBootstrapServer`.
        """
        assert self._bootstrap_vnode is None, \
            f"Solana cluster '{self._name}' already has a bootstrap validator ({self._bootstrap_vnode})"
        server = SolanaBootstrapServer(self)
        self._bootstrap_vnode = vnode
        self._nodes[vnode] = server
        self._service._register_node(vnode, server)
        return server

    def createValidator(self, vnode: str) -> SolanaValidatorServer:
        """!
        @brief Create a validator that joins this cluster via the bootstrap node.

        @param vnode virtual node name (resolved to a physical node by a Binding).
        @returns the :class:`SolanaValidatorServer`.
        """
        server = SolanaValidatorServer(self)
        self._nodes[vnode] = server
        self._service._register_node(vnode, server)
        return server

    # ------------------------------------------------------------------ #
    # Configure (resolve bindings -> connectivity)
    # ------------------------------------------------------------------ #
    def configure(self, emulator: Emulator):
        if not self._nodes:
            return
        assert self._bootstrap_vnode is not None, \
            f"Solana cluster '{self._name}' needs a bootstrap validator (createBootstrapValidator)."

        # Resolve every node's primary IP from its binding.
        for vnode, server in self._nodes.items():
            node = emulator.getBindingFor(vnode)
            server.set_self_ip(self._get_primary_ip(node))

        # Hand every validator the bootstrap node's gossip + RPC endpoint.
        boot = self._nodes[self._bootstrap_vnode]
        for vnode, server in self._nodes.items():
            if server is boot:
                continue
            server.set_bootstrap_endpoint(
                ip=boot._self_ip,
                gossip_port=boot.get_gossip_port(),
                rpc_port=boot.get_rpc_port(),
            )

    # ------------------------------------------------------------------ #
    # Internal utilities
    # ------------------------------------------------------------------ #
    def _get_primary_ip(self, node: Node) -> str:
        for iface in node.getInterfaces():
            if iface.getNet().getType() == NetworkType.Local:
                return str(iface.getAddress())
        raise AssertionError(f"Node {node.getName()} has no local network interface")

    def getBootstrapNode(self) -> Optional[str]:
        """!@brief Return the virtual-node name of the bootstrap validator."""
        return self._bootstrap_vnode

    def getValidatorNodes(self) -> List[str]:
        """!@brief Return the virtual-node names of the joining validators."""
        return [v for v in self._nodes if v != self._bootstrap_vnode]
