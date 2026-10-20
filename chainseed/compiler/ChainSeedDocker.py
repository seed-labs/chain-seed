"""Docker compiler with ChainSeed runtime image mappings."""

from __future__ import annotations

from typing import Dict
from seedemu.compiler import Docker, DockerImage, Platform
from seedemu.core import Emulator, SystemProfile

from .images import IMAGE_CATALOG


class ChainSeedDocker(Docker):
    """Compile ChainSeed systems using the runtime image catalog."""

    def __init__(self, *args, platform: Platform | None = None, **kwargs):
        if args:
            if platform is not None:
                raise TypeError("platform cannot be passed both positionally and by keyword")
            super().__init__(*args, **kwargs)
        else:
            super().__init__(platform=platform or Platform.AMD64, **kwargs)

    def getName(self) -> str:
        return "ChainSeedDocker"

    def _getSystemImageCatalog(
        self, platform: Platform
    ) -> Dict[SystemProfile, DockerImage]:
        catalog = dict(super()._getSystemImageCatalog(platform))
        catalog.update(IMAGE_CATALOG[platform])
        return catalog

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
        return super()._doCompile(emulator)


__all__ = ["ChainSeedDocker"]
