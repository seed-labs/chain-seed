"""Run from outside either checkout after installing ordinary wheels."""

import argparse
from importlib import metadata
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path)
    args = parser.parse_args()

    import seedemu
    assert metadata.version("seedemu")
    # SeedEmu development currently needs its source assets (editable install).
    import chainseed
    from chainseed.chainlink import ChainlinkService
    from chainseed.ethereum import EthereumService
    from chainseed.monero import MoneroService
    from chainseed.solana import SolanaService

    assert "site-packages" in str(Path(chainseed.__file__).resolve())
    assert metadata.metadata("chainseed")["Name"] == "chainseed"
    assert all((ChainlinkService, EthereumService, MoneroService, SolanaService))
    entries = metadata.distribution("chainseed").entry_points
    assert any(entry.name == "chainseed-test" for entry in entries)
    print("Installed ChainSEED wheel and all protocol imports work")

    if args.examples:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(args.examples.resolve(), root / "examples", ignore=shutil.ignore_patterns("output", "__pycache__"))
            programs = [
                [str(root / "examples/D01_ethereum_pos/ethereum_pos.py"), "--no-eth-explorer", "--beacon-nodes", "1", "--validators-per-beacon", "1", "--output", str(root / "pos-output")],
                ["-c", "import runpy; m=runpy.run_path('examples/D00_ethereum_poa/ethereum_poa.py'); m['run'](dumpfile='poa.bin', hosts_per_as=1, total_eth_nodes=7, total_accounts_per_node=1)"],
            ]
            for program in programs:
                result = subprocess.run([sys.executable, *program], cwd=root, capture_output=True, text=True, timeout=180)
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
            assert (root / "pos-output/docker-compose.yml").is_file()
            assert (root / "poa.bin").is_file()
            print("Copied Ethereum examples work with installed ChainSEED and SeedEmu development")
            for example in ("D01_ethereum_pos", "D10_eth_explorer", "D11_lookingglass", "D20_faucet", "D21_deploy_contract", "D22_oracle", "D23_validator"):
                manifest = root / "examples" / example / "example.yaml"
                result = subprocess.run(
                    [sys.executable, "-m", "chainseed.testing.cli", "compile", str(manifest), "--artifact-dir", str(root / "artifacts" / example)],
                    cwd=root, capture_output=True, text=True, timeout=180,
                )
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                print(example + " installed-package compilation passed")


if __name__ == "__main__":
    main()
