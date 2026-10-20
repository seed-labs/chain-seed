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
    version="0.1.0a0",
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

    if (
        not hasattr(core, "SystemProfile")
        or not callable(getattr(Docker, "_getSystemImageCatalog", None))
        or not callable(getattr(Docker, "addContainerBundle", None))
    ):
        raise RuntimeError(
            "chainseed requires SeedEmu SystemProfile, image catalog hooks and ContainerBundle support; "
            "install SeedEmu from the Docker branch. The distribution "
            "version alone does not identify these capabilities."
        )

