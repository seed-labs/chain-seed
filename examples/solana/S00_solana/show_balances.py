#!/usr/bin/env python3
# encoding: utf-8

"""Show Alice and Bob balances from the transaction demo."""

from __future__ import annotations

import argparse

from solana_docker import RPC_URL, exec_shell, find_bootstrap_container


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Show Alice/Bob balances created by send_transaction.py.",
    )
    return parser.parse_args()


def main() -> None:
    """Print the demo account balances."""
    parse_args()
    container = find_bootstrap_container()
    script = f"""
set -e
U={RPC_URL}
ALICE_KEY=/tmp/seedemu_alice.json
BOB_KEY=/tmp/seedemu_bob.json

test -f "$ALICE_KEY" || {{ echo "missing $ALICE_KEY; run python3 send_transaction.py first" >&2; exit 1; }}
test -f "$BOB_KEY" || {{ echo "missing $BOB_KEY; run python3 send_transaction.py first" >&2; exit 1; }}

ALICE=$(solana-keygen pubkey "$ALICE_KEY")
BOB=$(solana-keygen pubkey "$BOB_KEY")

echo "bootstrap_container={container}"
echo "alice=$ALICE"
echo "alice_balance=$(solana --url "$U" balance "$ALICE")"
echo "bob=$BOB"
echo "bob_balance=$(solana --url "$U" balance "$BOB")"
"""
    print(exec_shell(container, script), end="")


if __name__ == "__main__":
    main()
