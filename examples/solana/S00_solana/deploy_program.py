#!/usr/bin/env python3
# encoding: utf-8

"""Build and deploy the example Solana program to the private cluster."""

from __future__ import annotations

import argparse
import shutil
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from solana_docker import (
    RPC_URL,
    docker_cp,
    exec_shell,
    exit_with_process_error,
    find_bootstrap_container,
    run_command,
)

EXAMPLE_DIR = Path(__file__).resolve().parent
PROGRAM_DIR = EXAMPLE_DIR / "programs" / "noop_logger"
DEFAULT_SO = PROGRAM_DIR / "dist" / "seedemu_solana_noop.so"
CONTAINER_SO = "/tmp/seedemu_solana_noop.so"


def sol_amount(value: str) -> str:
    """Parse and normalize a positive SOL amount."""
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid SOL amount: {value}") from exc
    if not amount.is_finite() or amount <= 0:
        raise argparse.ArgumentTypeError("amount must be positive")
    return format(amount, "f")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build/copy/deploy the noop_logger SBF program to S00_solana.",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="run cargo build-sbf before deployment",
    )
    parser.add_argument(
        "--so",
        type=Path,
        default=DEFAULT_SO,
        help=f"path to the compiled .so (default: {DEFAULT_SO.relative_to(EXAMPLE_DIR)})",
    )
    parser.add_argument(
        "--airdrop",
        type=sol_amount,
        default="100",
        help="SOL to airdrop to the deployer account (default: 100)",
    )
    return parser.parse_args()


def build_program() -> None:
    """Run cargo build-sbf for the bundled example program."""
    if shutil.which("cargo") is None:
        raise SystemExit(
            "[fail] cargo was not found. Install the Solana/Agave SBF toolchain, "
            "then rerun: python3 deploy_program.py --build"
        )

    proc = run_command(
        ["cargo", "build-sbf", "--sbf-out-dir", "dist"],
        cwd=PROGRAM_DIR,
    )
    if proc.returncode != 0:
        exit_with_process_error("cargo build-sbf failed", proc)
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="" if proc.stderr.endswith("\n") else "\n")


def main() -> None:
    """Deploy the example program."""
    args = parse_args()
    if args.build:
        build_program()

    so_path = args.so.expanduser()
    if not so_path.is_absolute():
        so_path = Path.cwd() / so_path
    if not so_path.is_file():
        raise SystemExit(
            f"[fail] compiled program not found: {so_path}\n"
            "Build it first with: python3 deploy_program.py --build"
        )

    container = find_bootstrap_container()
    docker_cp(so_path, container, CONTAINER_SO)

    script = f"""
set -e
U={RPC_URL}
DEPLOYER_KEY=/tmp/seedemu_deployer.json
OUT=/tmp/seedemu_program_deploy.out

solana-keygen new --no-passphrase -fso "$DEPLOYER_KEY" >/dev/null
DEPLOYER=$(solana-keygen pubkey "$DEPLOYER_KEY")

echo "bootstrap_container={container}"
echo "deployer=$DEPLOYER"
solana --url "$U" airdrop {args.airdrop} "$DEPLOYER" >/dev/null
echo "deployer_balance=$(solana --url "$U" balance "$DEPLOYER")"

solana --url "$U" program deploy \\
  --keypair "$DEPLOYER_KEY" \\
  {CONTAINER_SO} | tee "$OUT"

PROGRAM_ID=$(sed -n 's/^Program Id: //p' "$OUT")
echo "program_id=$PROGRAM_ID"
test -n "$PROGRAM_ID"
solana --url "$U" program show "$PROGRAM_ID"
"""
    print(exec_shell(container, script), end="")


if __name__ == "__main__":
    main()
