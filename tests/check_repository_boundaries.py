"""Static ownership checks for the independently packaged repositories."""

import argparse
import ast
from pathlib import Path
import re


PROTOCOLS = ("EthereumService", "MoneroService", "SolanaService", "ChainlinkService")
OLD_IMPORT = re.compile(r"seedemu\.(?:services\.(?:EthereumService|MoneroService|SolanaService|ChainlinkService)|testing\.blockchain)")
OLD_PROFILE = re.compile(r"BaseSystem\.SEEDEMU_(?:ETHEREUM\w*|MONERO|SOLANA|CHAINLINK|OP_STACK|SC_DEPLOYER)")


def check(seedemu: Path, chainseed: Path):
    errors = []
    count = 0
    for repository, roots in ((seedemu, ("seedemu",)), (chainseed, ("chainseed", "examples", "case_study", "experiments", "tests", "tools", "library"))):
        for root in roots:
            for path in (repository / root).rglob("*.py"):
                if path.resolve() == Path(__file__).resolve():
                    continue
                if any(part in {"__pycache__", "node_modules", "output", "build"} for part in path.parts):
                    continue
                count += 1
                text = path.read_text(encoding="utf-8-sig")
                try:
                    tree = ast.parse(text, filename=str(path))
                except SyntaxError as exc:
                    errors.append(str(exc))
                    continue
                if repository == seedemu:
                    for node in ast.walk(tree):
                        imports = []
                        if isinstance(node, ast.Import):
                            imports = [alias.name for alias in node.names]
                        elif isinstance(node, ast.ImportFrom):
                            imports = [node.module or ""]
                        if any(name == "chainseed" or name.startswith("chainseed.") for name in imports):
                            errors.append(str(path) + " imports ChainSEED")
                elif OLD_IMPORT.search(text) or OLD_PROFILE.search(text) or "etherViewEnabled" in text:
                    errors.append(str(path) + " depends on removed SeedEmu protocol APIs")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"ChainSEED dependency boundary and syntax checks passed for {count} Python files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seedemu", type=Path, required=True)
    parser.add_argument("--chainseed", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    check(args.seedemu.resolve(), args.chainseed.resolve())


if __name__ == "__main__":
    main()
