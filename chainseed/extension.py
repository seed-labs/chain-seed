"""Versioned metadata describing the ChainSeed extension boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChainSeedExtension:
    distribution: str
    version: str
    extension_api_version: int
    seedemu_min_version: str
    owned_layer_names: tuple[str, ...]
    artifact_schema_versions: tuple[str, ...]


descriptor = ChainSeedExtension(
    distribution="chainseed",
    version="1.0.0",
    extension_api_version=1,
    seedemu_min_version="0.0.7",
    owned_layer_names=(
        "EthereumService",
        "MoneroService",
        "SolanaService",
        "ChainlinkService",
    ),
    artifact_schema_versions=("chainseed.labels/v1",),
)


def check_seedemu_compatibility() -> None:
    """Check the SeedEmu capabilities used by the blockchain plugin."""
    from seedemu import core
    from seedemu.compiler import Docker

    required = {
        "seedemu.core.SystemProfile": hasattr(core, "SystemProfile"),
        "Service.getDockerImages": callable(getattr(core.Service, "getDockerImages", None)),
        "Service.setDockerImage": callable(getattr(core.Service, "setDockerImage", None)),
        "Docker._collectServiceImages": callable(getattr(Docker, "_collectServiceImages", None)),
        "Docker.addContainerBundle": callable(getattr(Docker, "addContainerBundle", None)),
    }
    missing = [name for name, available in required.items() if not available]
    if missing:
        raise RuntimeError(
            "chainseed is missing required SeedEmu capabilities: " + ", ".join(missing) + "; "
            "install seedemu==0.0.7 with these extension interfaces. The distribution "
            "version alone does not identify these capabilities."
        )

