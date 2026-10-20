from __future__ import annotations

from enum import Enum


class SolanaNodeRole(Enum):
    """!
    @brief Role of a Solana node within a private cluster.

    A private Agave/Solana cluster is bootstrapped by exactly one *bootstrap*
    (genesis) validator. That node creates the genesis ledger and runs the
    faucet. Every other validator joins the cluster over gossip using the
    bootstrap node as its entrypoint.
    """

    ## The genesis / bootstrap validator. Creates the genesis ledger, stakes
    #  itself, runs the faucet, and is the gossip entrypoint for the cluster.
    BOOTSTRAP = "bootstrap"

    ## A regular validator that joins an existing cluster via the bootstrap's
    #  gossip entrypoint, funds itself from the faucet, and votes.
    VALIDATOR = "validator"


class SolanaNetworkType(Enum):
    """!
    @brief Cluster type passed to ``solana-genesis --cluster-type``.

    For emulation we use ``development``, which is the self-contained local
    cluster type (no connection to Solana's public devnet/testnet/mainnet).
    """

    DEVELOPMENT = "development"
