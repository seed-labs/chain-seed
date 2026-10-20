"""Docker compiler with ChainSeed runtime mappings and components."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping
from pathlib import Path
from seedemu.compiler import Docker, DockerImage, Platform
from seedemu.core import Emulator, SystemProfile

from .images import IMAGE_CATALOG


class ChainSeedDocker(Docker):
    """Compile ChainSeed systems and optional deployment components."""

    def __init__(self, *args, platform: Platform | None = None, **kwargs):
        self.__components: List[object] = []
        if args:
            if platform is not None:
                raise TypeError("platform cannot be passed both positionally and by keyword")
            super().__init__(*args, **kwargs)
        else:
            super().__init__(platform=platform or Platform.AMD64, **kwargs)

    def getName(self) -> str:
        return "ChainSeedDocker"

    def addComponent(self, component) -> "ChainSeedDocker":
        """Register a component that contributes deployment services."""
        if not hasattr(component, "getComposeServices"):
            raise TypeError(
                "component must provide getComposeServices(emulator, network_name)"
            )
        self.__components.append(component)
        return self

    def enableEthExplorer(
        self,
        chain_name: str,
        port: int = 5000,
        backend_image: str | None = None,
        web_image: str | None = None,
        *,
        geth_vnode: str | None = None,
        beacon_vnode: str | None = None,
    ) -> "ChainSeedDocker":
        """Enable the ChainSeed EthExplorer deployment component."""
        from ..ethereum.EthExplorer import (
            ETH_EXPLORER_BACKEND_IMAGE,
            ETH_EXPLORER_WEB_IMAGE,
            EthExplorer,
        )

        return self.addComponent(
            EthExplorer(
                chain_name=chain_name,
                port=port,
                backend_image=backend_image or ETH_EXPLORER_BACKEND_IMAGE,
                web_image=web_image or ETH_EXPLORER_WEB_IMAGE,
                geth_vnode=geth_vnode,
                beacon_vnode=beacon_vnode,
            )
        )

    def _getSystemImageCatalog(
        self, platform: Platform
    ) -> Dict[SystemProfile, DockerImage]:
        catalog = dict(super()._getSystemImageCatalog(platform))
        catalog.update(IMAGE_CATALOG[platform])
        return catalog

    def _getAdditionalComposeServices(
        self, emulator: Emulator
    ) -> Mapping[str, Mapping[str, Any]]:
        services = dict(super()._getAdditionalComposeServices(emulator))
        for component in self.__components:
            additions = component.getComposeServices(emulator, self._getRealNetName)
            if not isinstance(additions, Mapping):
                raise TypeError("component Compose services must be a mapping")
            duplicates = set(services) & set(additions)
            if duplicates:
                raise ValueError(
                    "duplicate Compose service(s): {}".format(
                        ", ".join(sorted(duplicates))
                    )
                )
            services.update(additions)
        return services

    def _registerMoneroOverrides(self, emulator: Emulator) -> None:
        try:
            monero = emulator.getLayer("MoneroService")
        except AssertionError:
            return

        known_images = {image.getName() for image, _ in self.getImages()}
        for server, node in monero.getTargets():
            custom_image = server.network.getCustomBaseImage()
            if not custom_image:
                continue
            if custom_image not in known_images:
                self.addImage(
                    DockerImage(
                        name=custom_image,
                        software=[],
                        local=False,
                        subset=None,
                    ),
                    priority=0,
                )
                known_images.add(custom_image)
            self.setImageOverride(node, custom_image)

    def _doCompile(self, emulator: Emulator):
        self._registerMoneroOverrides(emulator)
        result = super()._doCompile(emulator)
        for component in self.__components:
            writer = getattr(component, "writeOutputFiles", None)
            if writer is not None:
                writer(emulator, Path.cwd())
        return result


__all__ = ["ChainSeedDocker"]
