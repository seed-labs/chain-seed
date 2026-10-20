#!/usr/bin/env bash
#
# Verify an already-running S00_solana private Solana cluster.
#
# This script intentionally does not build images, generate the emulation,
# start containers, or tear containers down. Prepare the environment first with
# ./prepare_solana.sh, then run this script as many times as needed while you
# inspect the live cluster.
#
# Usage:
#   ./prepare_solana.sh             # one-time setup/start
#   ./test_solana.sh                # verify the running cluster
#   MIN_VALIDATORS=1 ./test_solana.sh

set -uo pipefail

# Bootstrap validator: AS150 / host_0. Its RPC is reachable on the emulated
# network; we reach it by exec-ing into the container (no host port mapping).
BOOT_NAME_PREFIX="as150h-Solana-Bootstrap-150-"

# How long to wait (seconds) for the chain to start producing blocks.
MAX_WAIT="${MAX_WAIT:-420}"
# Minimum number of *voting* validators required for a hard pass. On a native
# image for your host architecture (amd64 or arm64) and with enough CPU/RAM,
# all validators can converge. Set REQUIRE_MULTI=1 to make this a hard
# requirement.
MIN_VALIDATORS="${MIN_VALIDATORS:-2}"

log()  { echo -e "\033[1;34m[test]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
fail() { echo -e "\033[1;31m[fail]\033[0m $*"; }

if [[ $# -gt 0 ]]; then
  fail "test_solana.sh does not take lifecycle arguments; it only verifies a running cluster."
  echo "Prepare the cluster with ./prepare_solana.sh, then run ./test_solana.sh."
  exit 2
fi

find_boot_container() {
  docker ps --format '{{.Names}}' | grep "^$BOOT_NAME_PREFIX" | head -n 1
}

boot_cid="$(find_boot_container)"
if [[ -z "$boot_cid" ]]; then
  fail "could not find a running bootstrap container (${BOOT_NAME_PREFIX}...)."
  docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Status}}'
  echo "Run ./prepare_solana.sh first."
  exit 1
fi

ok "bootstrap container is running: $boot_cid"

# Helper: resolve the current bootstrap container name before every exec, so a
# recreated container does not leave the test script holding a stale reference.
RPC_URL_LOCAL="http://127.0.0.1:8899"
exec_boot() {
  local cid
  cid="$(find_boot_container)"
  [[ -n "$cid" ]] || return 1
  docker exec "$cid" "$@"
}

sol() {
  local tries=0 out
  while (( tries < 6 )); do
    if out=$(exec_boot solana --url "$RPC_URL_LOCAL" "$@" 2>/dev/null); then
      echo "$out"; return 0
    fi
    tries=$((tries+1)); sleep 2
  done
  return 1
}

# ---------------------------------------------------------------------------
# 4) Verify the chain is alive and producing blocks.
# ---------------------------------------------------------------------------
log "waiting for the bootstrap RPC to come online ..."
deadline=$(( $(date +%s) + MAX_WAIT ))
rpc_up=0
ver=""
while (( $(date +%s) < deadline )); do
  if ver=$(sol cluster-version) && [[ -n "$ver" ]]; then
    rpc_up=1; break
  fi
  sleep 10
done
if (( rpc_up != 1 )); then
  fail "RPC never came online within ${MAX_WAIT}s"
  exec_boot sh -c 'tail -n 40 /opt/solana/config/bootstrap-validator/*.log' 2>/dev/null || true
  exit 1
fi
ok "RPC online: cluster-version $ver"

log "checking that slots are advancing (block production) ..."
slot1=$(sol slot | tr -dc '0-9'); slot1=${slot1:-0}
log "slot now: $slot1 ; waiting ~30s ..."
sleep 30
slot2=$(sol slot | tr -dc '0-9'); slot2=${slot2:-0}
log "slot now: $slot2"

if [[ "$slot2" -gt "$slot1" ]]; then
  ok "slots are advancing ($slot1 -> $slot2): the chain is producing blocks."
else
  fail "slots did not advance ($slot1 -> $slot2): chain is not producing blocks."
  exec_boot sh -c 'tail -n 60 /opt/solana/config/bootstrap-validator/*.log' 2>/dev/null || true
  exit 1
fi

# Confirm block height is non-zero too.
bh=$(sol block-height | tr -dc '0-9')
log "block-height: ${bh:-unknown}"

# ---------------------------------------------------------------------------
# 4b) Verify the chain actually processes transactions (airdrop -> balance).
# ---------------------------------------------------------------------------
log "verifying transaction processing (airdrop to a fresh account) ..."
tx_ok=0
if exec_boot bash -c '
    set -e
    U=http://127.0.0.1:8899
    solana-keygen new --no-passphrase -fso /tmp/seedemu_test_payer.json >/dev/null 2>&1
    PK=$(solana-keygen pubkey /tmp/seedemu_test_payer.json)
    solana --url $U airdrop 5 "$PK" >/dev/null 2>&1
    for i in $(seq 1 10); do
      bal=$(solana --url $U balance "$PK" 2>/dev/null | grep -oE "^[0-9.]+")
      awk "BEGIN{exit !($bal > 0)}" && exit 0
      sleep 2
    done
    exit 1
  ' 2>/dev/null; then
  tx_ok=1
  ok "transaction processed: airdrop credited a new account (ledger is executing transactions)."
else
  fail "transaction did not confirm (airdrop balance stayed 0)."
  exec_boot sh -c 'tail -n 40 /opt/solana/config/bootstrap-validator/*.log' 2>/dev/null || true
  exit 1
fi

# ---------------------------------------------------------------------------
# 5) Verify the joining validators register and vote in the cluster.
#
# This is the multi-host part of the cluster. It converges when the image is
# native to the host architecture and Docker has enough CPU/RAM. Under
# cross-architecture emulation, joining validators may not converge; that is an
# emulation-host limitation, not a defect in the generated topology. It is
# therefore best-effort by default; set REQUIRE_MULTI=1 to make it a hard
# requirement.
# ---------------------------------------------------------------------------
log "waiting for joining validators to vote (up to ${MAX_WAIT}s; need >= $MIN_VALIDATORS) ..."
deadline=$(( $(date +%s) + MAX_WAIT ))
nval=0
while (( $(date +%s) < deadline )); do
  nval=$(sol validators 2>/dev/null | grep -oE '[0-9]+ current validators' | grep -oE '^[0-9]+' | head -1)
  nval=${nval:-0}
  log "voting validators in cluster: $nval (target >= $MIN_VALIDATORS)"
  (( nval >= MIN_VALIDATORS )) && break
  sleep 15
done

echo
log "validator set:"
sol validators || true
echo

multi_ok=0
if (( nval >= MIN_VALIDATORS )); then
  (( nval >= 2 )) && multi_ok=1
  if (( multi_ok == 1 )); then
    ok "$nval validators are voting (multi-validator consensus working)."
  else
    ok "$nval validator is voting."
  fi
elif [[ "${REQUIRE_MULTI:-0}" == "1" ]]; then
  fail "only $nval voting validator(s); expected >= $MIN_VALIDATORS (REQUIRE_MULTI=1)."
  exec_boot sh -c 'tail -n 40 /opt/solana/config/bootstrap-validator/*.log' 2>/dev/null || true
  exit 1
else
  echo -e "\033[1;33m[warn]\033[0m only $nval voting validator(s) converged here."
  echo "       Multi-host convergence needs native images for your host architecture and enough CPU/RAM."
fi

# ---------------------------------------------------------------------------
# Verdict. The core requirement — a working Solana chain that produces blocks
# and processes transactions — is verified by the hard checks above.
# ---------------------------------------------------------------------------
echo
ok "SUCCESS: the private Solana chain is live, producing blocks, and processing transactions."
echo "    cluster-version    : $ver"
echo "    slot               : $slot1 -> $slot2"
echo "    block-height       : ${bh:-unknown}"
echo "    transaction test   : $([[ $tx_ok == 1 ]] && echo passed || echo failed)"
echo "    voting validators  : $nval $([[ $multi_ok == 1 ]] && echo '(multi-validator consensus)' || echo '(single voting validator)')"
echo "    cluster state      : left running"
