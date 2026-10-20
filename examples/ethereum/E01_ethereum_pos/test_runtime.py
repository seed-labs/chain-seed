#!/usr/bin/env python3

from __future__ import annotations

from chainseed.common.systems import ETHEREUM_POS
from chainseed.compiler.images import IMAGE_CATALOG
from seedemu.compiler import Platform
from chainseed.testing import EthereumRuntimeTest


def main() -> int:
    test = EthereumRuntimeTest(__file__)

    expected_from = "FROM " + IMAGE_CATALOG[Platform.AMD64][ETHEREUM_POS].getName()
    dummy_dir = test.example_dir / "output" / "dummies"
    generated_from = {
        path.read_text(encoding="utf-8").strip()
        for path in dummy_dir.iterdir()
        if path.is_file()
    } if dummy_dir.is_dir() else set()
    test.structural_check(
        "E01 uses the ChainSeed Ethereum PoS image",
        expected_from in generated_from,
        "expected {} in generated Docker inputs".format(expected_from),
    )

    geth_nodes = test.require_ethereum_services(
        "E01 has a Geth node for the transaction test",
        minimum_count=1,
        class_contains="Ethereum-POS-Geth",
        consensus="POS",
    )

    if geth_nodes:
        test.send_ether_and_verify(
            "A signed ETH transfer is included and changes balances",
            geth_nodes[0],
            value_wei=10**18,
        )

    test.write_summary("e01-ethereum-pos-runtime-test.json")
    return test.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
