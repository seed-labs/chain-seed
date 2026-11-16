"""Blockchain extensions for SeedEmu."""

from .extension import ChainSeedExtension, check_seedemu_compatibility, descriptor

check_seedemu_compatibility()

__version__ = descriptor.version

__all__ = ["ChainSeedExtension", "descriptor", "__version__"]

