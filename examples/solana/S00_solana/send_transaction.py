#!/usr/bin/env python3
# encoding: utf-8

"""Send a transfer transaction on the private Solana cluster."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation

from solana_docker import RPC_URL, exec_shell, find_bootstrap_container


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
        description="Create Alice/Bob accounts and transfer SOL inside the S00_solana cluster.",
    )
    parser.add_argument(
        "--airdrop",
        type=sol_amount,
        default="10",
        help="SOL to airdrop when Alice is first created, or with --top-up (default: 10)",
    )
    parser.add_argument(
        "--amount",
        type=sol_amount,
        default="1",
        help="SOL to transfer from Alice to Bob (default: 1)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="discard the previous demo Alice/Bob keypairs and start over",
    )
    parser.add_argument(
        "--top-up",
        action="store_true",
        help="airdrop --airdrop SOL to Alice even when reusing an existing keypair",
    )
    return parser.parse_args()


def main() -> None:
    """Run the transaction demo."""
    args = parse_args()
    container = find_bootstrap_container()

    script = f"""
set -e
U={RPC_URL}
ALICE_KEY=/tmp/seedemu_alice.json
BOB_KEY=/tmp/seedemu_bob.json
OUT=/tmp/seedemu_transfer.out
RESET={1 if args.reset else 0}
TOP_UP={1 if args.top_up else 0}

if [ "$RESET" = 1 ]; then
  rm -f "$ALICE_KEY" "$BOB_KEY"
fi

CREATED_ALICE=0
CREATED_BOB=0
if [ ! -f "$ALICE_KEY" ]; then
  solana-keygen new --no-passphrase -fso "$ALICE_KEY" >/dev/null
  CREATED_ALICE=1
fi
if [ ! -f "$BOB_KEY" ]; then
  solana-keygen new --no-passphrase -fso "$BOB_KEY" >/dev/null
  CREATED_BOB=1
fi

ALICE=$(solana-keygen pubkey "$ALICE_KEY")
BOB=$(solana-keygen pubkey "$BOB_KEY")

echo "bootstrap_container={container}"
echo "alice=$ALICE"
echo "alice_key_created=$CREATED_ALICE"
echo "bob=$BOB"
echo "bob_key_created=$CREATED_BOB"

if [ "$CREATED_ALICE" = 1 ] || [ "$TOP_UP" = 1 ]; then
  solana --url "$U" airdrop {args.airdrop} "$ALICE" >/dev/null
  echo "airdrop_to_alice={args.airdrop} SOL"
else
  echo "airdrop_to_alice=skipped"
fi
echo "alice_balance_before=$(solana --url "$U" balance "$ALICE")"

solana --url "$U" transfer --from "$ALICE_KEY" --fee-payer "$ALICE_KEY" \\
  "$BOB" {args.amount} --allow-unfunded-recipient > "$OUT"
cat "$OUT"

SIG=$(sed -n 's/^Signature: //p' "$OUT")
test -n "$SIG"
echo "signature=$SIG"
solana --url "$U" confirm -v "$SIG"

echo "alice_balance_after=$(solana --url "$U" balance "$ALICE")"
echo "bob_balance_after=$(solana --url "$U" balance "$BOB")"
echo "transaction_count=$(solana --url "$U" transaction-count)"
"""
    print(exec_shell(container, script), end="")


if __name__ == "__main__":
    main()
