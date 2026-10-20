"""Isolation for mutable state in the upstream Docker compiler."""

import pytest
from seedemu.compiler import Docker


@pytest.fixture(autouse=True)
def isolate_upstream_container_bundles(monkeypatch):
    # Remove when upstream Docker initializes its bundle list per instance.
    monkeypatch.setattr(Docker, "_Docker__containerBundles", [], raising=False)
