"""A global Ethereum viewer installed on an ordinary emulated host."""

from __future__ import annotations

import json
import math
from importlib.resources import files
from pathlib import Path, PurePosixPath
import shlex

from seedemu.core import Server
from seedemu.core.enums import NetworkType

from ..EthereumServer import PoSBeaconServer, PoSVcServer
from ..GethPeers import GethPeerConfig
from ..RuntimeConfig import integer


class LookingglassServer(Server):
    """Observe every Ethereum chain without changing any client's settings."""

    DIR_PREFIX = "/opt/chainseed/lookingglass"

    def __init__(self):
        super().__init__()
        self._port = 8765
        self._probes = True
        self._peer_interval = 10
        self._metrics_interval = 10
        self._workers = 8
        self._observation_directory = None
        self._inventory = None

    def _assertConfigurable(self):
        if self._inventory is not None:
            raise RuntimeError("Configure Lookingglass before emu.render()")

    def setPort(self, port: int):
        """Set both the HTTP listener and its published host port."""
        self._assertConfigurable()
        self._port = integer(port, "Lookingglass port", maximum=65535)
        return self

    def getPort(self):
        return self._port

    def setProbePolicy(self, *, enabled=True, peer_interval=10,
                       metrics_interval=10, workers=8):
        """Adjust optional read-only client queries; defaults need no setup."""
        self._assertConfigurable()
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        for name, value, minimum in (("peer_interval", peer_interval, 1),
                                     ("metrics_interval", metrics_interval, 2)):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not minimum <= value <= 3600):
                raise ValueError(f"{name} must be {minimum}..3600 seconds")
        integer(workers, "Lookingglass workers", maximum=32)
        self._probes, self._peer_interval = enabled, peer_interval
        self._metrics_interval, self._workers = metrics_interval, workers
        return self

    def setObservationDirectory(self, directory):
        """Optionally read independent collectors' files via a read-only mount."""
        self._assertConfigurable()
        self._observation_directory = Path(directory).expanduser().resolve()
        return self

    def configure(self, emulator, ethereum):
        bound_host = next(node for server, node in ethereum.getTargets() if server is self)
        for obj in emulator.getRegistry().getAll().values():
            if not hasattr(obj, "getPorts"):
                continue
            for host_port, target_port, protocol in obj.getPorts():
                if protocol == "tcp" and host_port == self._port:
                    if obj is not bound_host or target_port != self._port:
                        raise ValueError(f"Lookingglass host port {self._port} is already forwarded")
        nodes, edges = [], []
        for vnode, server in ethereum.getPendingTargets().items():
            if isinstance(server, GethPeerConfig):
                role = "geth"
            elif isinstance(server, PoSBeaconServer):
                role = "beacon"
            elif isinstance(server, PoSVcServer):
                role = "validator"
            else:
                continue
            host = emulator.getBindingFor(vnode)
            interface = next((i for i in host.getInterfaces()
                              if i.getNet().getType() == NetworkType.Local
                              and i.getAddress() is not None), None)
            if interface is None:
                raise ValueError(f"{vnode}: Lookingglass needs an addressed local interface")
            chain = server.getBlockchain()
            item = dict(id=vnode, vnode=vnode, role=role,
                        label=host.getDisplayName() or vnode,
                        chain=chain.getChainName(), chain_id=chain.getChainId(),
                        consensus=chain.getConsensusMechanism().value,
                        asn=str(host.getAsn()), host=host.getName(),
                        ip=str(interface.getAddress()), rpc_port=None)
            if role == "geth":
                item.update(rpc_port=server.getGethHttpPort() if server.isGethHttpEnabled() else None,
                            static_peers=server.getStaticPeers(), enode=server.getP2PEnode(),
                            cache_mib=server._cache_mib,
                            gomemlimit_mib=server._go_memory_limit_mib)
            elif role == "beacon":
                item.update(rpc_port=8000, metrics_port=server.getMetricsPort(),
                            cap=server._processor_max_workers)
                target = server.getConnectGethVNode()
                if target:
                    edges.append(dict(source=vnode, target=target, kind="service", at=None))
            else:
                item["keys"] = server.getValidatorKeyCount()
                target = server.getConnectBeaconVNode()
                if target:
                    edges.append(dict(source=vnode, target=target, kind="service", at=None))
            nodes.append(item)
        ids = {node["id"] for node in nodes}
        self._inventory = dict(title="Ethereum global view", nodes=nodes,
                               chains=ethereum.getBlockchainNames(),
                               edges=[edge for edge in edges if edge["target"] in ids])

    def install(self, node):
        if self._inventory is None:
            raise RuntimeError("Configure Lookingglass before installation")
        node.appendClassName("Ethereum-Lookingglass")
        node.setLabel("chainseed.component", "lookingglass")
        node.addSoftware("python3 python3-yaml")
        resources = files(__package__)
        # Install a small runtime package; its initializer must not import the
        # deployment class, whose SeedEmu dependencies are host-side only.
        node.setFile(f"{self.DIR_PREFIX}/__init__.py", '"""Lookingglass HTTP runtime."""\n')
        for name in ("app.py", "sources.py"):
            node.setFile(f"{self.DIR_PREFIX}/{name}", resources.joinpath(name).read_text(encoding="utf-8"))
        for resource in sorted(resources.joinpath("static").iterdir(), key=lambda item: item.name):
            if resource.is_file():
                node.setFile(f"{self.DIR_PREFIX}/static/{resource.name}", resource.read_text(encoding="utf-8"))
        node.setFile(f"{self.DIR_PREFIX}/inventory.json", json.dumps(self._inventory, indent=2) + "\n")
        runtime_path = PurePosixPath(self.DIR_PREFIX)
        command = ["env", f"PYTHONPATH={runtime_path.parent}", "python3", "-u", "-m",
                   runtime_path.name + ".app", "--inventory",
                   f"{self.DIR_PREFIX}/inventory.json", "--host", "0.0.0.0",
                   "--port", str(self._port), "--peer-interval", str(self._peer_interval),
                   "--peer-jobs", str(self._workers),
                   "--metrics-interval", str(self._metrics_interval)]
        if self._probes:
            command.append("--probe-peers")
        if self._observation_directory is not None:
            self._observation_directory.mkdir(parents=True, exist_ok=True)
            node.addSharedFolder("/observations", str(self._observation_directory), read_only=True)
            command += ["--run-dir", "/observations"]
        forwarding = (self._port, self._port, "tcp")
        for host_port, target_port, protocol in node.getPorts():
            if protocol == "tcp" and (host_port == self._port or target_port == self._port):
                if (host_port, target_port, protocol) != forwarding:
                    raise ValueError("Lookingglass port conflicts with an existing port forwarding")
        if forwarding not in node.getPorts():
            node.addPort(*forwarding)
        node.appendStartCommand(shlex.join(command), True)

    def print(self, indent=0):
        return " " * indent + "Global Ethereum Lookingglass server.\n"
