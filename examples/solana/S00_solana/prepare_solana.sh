#!/usr/bin/env bash
#
# Prepare the S00_solana emulation and leave all containers running.
#
# This script is intentionally separate from test_solana.sh:
#   - prepare_solana.sh builds/generates/starts the environment
#   - test_solana.sh only verifies an already-running environment
#
# Usage:
#   ./prepare_solana.sh
#   PLATFORM=linux/amd64 ./prepare_solana.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
OUTPUT_DIR="$HERE/output"
COMPOSE="docker compose"
DEFAULT_PYTHON_BIN="/home/bruce/miniconda3/envs/seedpy310/bin/python"
if [[ ! -x "$DEFAULT_PYTHON_BIN" ]]; then
  DEFAULT_PYTHON_BIN="$(cd "$REPO_ROOT" && command -v python3)"
fi
PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_PYTHON_BIN}"

case "$(uname -m)" in
  arm64|aarch64) DEFAULT_PLATFORM="linux/arm64" ;;
  *)             DEFAULT_PLATFORM="linux/amd64" ;;
esac
PLATFORM="${PLATFORM:-$DEFAULT_PLATFORM}"
case "$PLATFORM" in
  linux/arm64) EMU_ARCH="arm" ;;
  linux/amd64) EMU_ARCH="amd" ;;
  *) echo "Unsupported PLATFORM=$PLATFORM (expected linux/amd64 or linux/arm64)" >&2; exit 1 ;;
esac
export DOCKER_DEFAULT_PLATFORM="$PLATFORM"

log()  { echo -e "\033[1;34m[prepare]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
fail() { echo -e "\033[1;31m[fail]\033[0m $*"; }

if [[ -z "${HTTP_PROXY:-}" && -n "${http_proxy:-}" ]]; then export HTTP_PROXY="$http_proxy"; fi
if [[ -z "${HTTPS_PROXY:-}" && -n "${https_proxy:-}" ]]; then export HTTPS_PROXY="$https_proxy"; fi
if [[ -z "${http_proxy:-}" && -n "${HTTP_PROXY:-}" ]]; then export http_proxy="$HTTP_PROXY"; fi
if [[ -z "${https_proxy:-}" && -n "${HTTPS_PROXY:-}" ]]; then export https_proxy="$HTTPS_PROXY"; fi
if [[ -z "${NO_PROXY:-}" && -n "${no_proxy:-}" ]]; then export NO_PROXY="$no_proxy"; fi
if [[ -z "${no_proxy:-}" && -n "${NO_PROXY:-}" ]]; then export no_proxy="$NO_PROXY"; fi

BUILD_ARGS=()
for proxy_var in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy; do
  if [[ -n "${!proxy_var:-}" ]]; then
    BUILD_ARGS+=(--build-arg "$proxy_var")
  fi
done
BUILD_NETWORK="${DOCKER_BUILD_NETWORK:-host}"
BUILD_NETWORK_ARGS=()
if [[ -n "$BUILD_NETWORK" ]]; then
  BUILD_NETWORK_ARGS+=(--network "$BUILD_NETWORK")
fi

inject_solana_ulimits() {
  local compose_file="$1"
  "$PYTHON_BIN" - "$compose_file" <<'PY'
from pathlib import Path
import re
import sys

compose_path = Path(sys.argv[1])
lines = compose_path.read_text().splitlines(keepends=True)
service_re = re.compile(r"^    [A-Za-z0-9][A-Za-z0-9_.-]*:\s*$")
top_level_re = re.compile(r"^\S.*:\s*$")
container_re = re.compile(r"container_name:\s+.*Solana-")
ulimits_re = re.compile(r"^\s+ulimits:\s*$")
network_re = re.compile(r"^        networks:\s*$")
privileged_re = re.compile(r"^        privileged:\s+true\s*$")

ulimits_block = [
    "        ulimits:\n",
    "            nofile:\n",
    "                soft: 1000000\n",
    "                hard: 1000000\n",
]

out = []
updated = 0
i = 0
while i < len(lines):
    if not service_re.match(lines[i]):
        out.append(lines[i])
        i += 1
        continue

    j = i + 1
    while j < len(lines) and not service_re.match(lines[j]) and not top_level_re.match(lines[j]):
        j += 1

    block = lines[i:j]
    is_solana_service = any(container_re.search(line) for line in block)
    has_ulimits = any(ulimits_re.match(line) for line in block)

    if is_solana_service and not has_ulimits:
        insert_at = next((idx for idx, line in enumerate(block) if network_re.match(line)), None)
        if insert_at is None:
            insert_at = next(
                (idx + 1 for idx, line in enumerate(block) if privileged_re.match(line)),
                len(block),
            )
        block = block[:insert_at] + ulimits_block + block[insert_at:]
        updated += 1

    out.extend(block)
    i = j

compose_path.write_text("".join(out))
print(updated)
PY
}

patch_solana_runtime_scripts() {
  local output_dir="$1"
  "$PYTHON_BIN" - "$output_dir" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
bootstrap_updates = 0
validator_updates = 0

validator_stake_keypair_line = (
    '[ -f "$LEDGER_DIR/stake-account.json" ]  || '
    'solana-keygen new --no-passphrase -so "$LEDGER_DIR/stake-account.json"\n'
)

validator_stake_block = [
    "\n",
    "# Create and delegate stake so this validator becomes active in the validator set.\n",
    'VALIDATOR_STAKE_SOL="${VALIDATOR_STAKE_SOL:-2}"\n',
    'STAKE_PUBKEY=$(solana-keygen pubkey "$LEDGER_DIR/stake-account.json")\n',
    'VOTE_PUBKEY=$(solana-keygen pubkey "$LEDGER_DIR/vote-account.json")\n',
    'STAKE_STATUS=$(solana --url "$RPC_URL" stake-account "$STAKE_PUBKEY" 2>/dev/null || true)\n',
    'if echo "$STAKE_STATUS" | grep -q "Delegated Stake"; then\n',
    '  echo "[seedemu-solana] stake account already delegated."\n',
    "else\n",
    '  echo "[seedemu-solana] creating/delegating ${VALIDATOR_STAKE_SOL} SOL stake to validator."\n',
    '  until solana --url "$RPC_URL" airdrop "$NODE_SOL" "$IDENTITY_PUBKEY" >/dev/null 2>&1; do\n',
    '    echo "[seedemu-solana] airdrop not ready for stake account, retrying ..."; sleep 2\n',
    "  done\n",
    '  if ! solana --url "$RPC_URL" stake-account "$STAKE_PUBKEY" >/dev/null 2>&1; then\n',
    '    until solana --url "$RPC_URL" create-stake-account "$LEDGER_DIR/stake-account.json" "$VALIDATOR_STAKE_SOL" \\\n',
    '    --from "$LEDGER_DIR/identity.json" \\\n',
    '    --fee-payer "$LEDGER_DIR/identity.json" \\\n',
    '    --stake-authority "$LEDGER_DIR/identity.json" \\\n',
    '    --withdraw-authority "$LEDGER_DIR/withdrawer.json" \\\n',
    '    >/dev/null 2>&1; do\n',
    '      echo "[seedemu-solana] create-stake-account not ready, retrying ..."; sleep 2\n',
    "    done\n",
    "  fi\n",
    '  until solana --url "$RPC_URL" delegate-stake "$LEDGER_DIR/stake-account.json" "$VOTE_PUBKEY" \\\n',
    '    --stake-authority "$LEDGER_DIR/identity.json" \\\n',
    '    --fee-payer "$LEDGER_DIR/identity.json" \\\n',
    '    >/dev/null 2>&1; do\n',
    '      echo "[seedemu-solana] delegate-stake not ready, retrying ..."; sleep 2\n',
    "  done\n",
    "fi\n",
]

for path in root.glob("hnode_*/*"):
    if not path.is_file():
        continue
    text = path.read_text(errors="ignore")

    if "# seedemu-solana: genesis / bootstrap validator" in text and "--slots-per-epoch" not in text:
        lines = text.splitlines(keepends=True)
        for idx, line in enumerate(lines):
            if line.strip() == "--enable-warmup-epochs \\":
                lines.insert(idx + 1, "    --slots-per-epoch 64 \\\n")
                path.write_text("".join(lines))
                bootstrap_updates += 1
                break
        continue

    if "# seedemu-solana: validator joining the private cluster" not in text:
        continue
    if "delegate-stake" in text:
        continue

    lines = text.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if 'withdrawer.json" ]' in line:
            lines.insert(idx + 1, validator_stake_keypair_line)
            break

    create_vote_idx = next(
        (idx for idx, line in enumerate(lines) if "create-vote-account" in line),
        None,
    )
    if create_vote_idx is None:
        continue

    insert_at = next(
        (idx + 1 for idx in range(create_vote_idx, len(lines)) if lines[idx].strip() == "fi"),
        None,
    )
    if insert_at is None:
        continue

    lines[insert_at:insert_at] = validator_stake_block
    path.write_text("".join(lines))
    validator_updates += 1

print(f"bootstrap={bootstrap_updates} validators={validator_updates}")
PY
}

log "building seedemu-solana base image ($PLATFORM) ..."
docker build --platform "$PLATFORM" "${BUILD_NETWORK_ARGS[@]}" "${BUILD_ARGS[@]}" \
  -t seedemu-solana "$REPO_ROOT/docker_images/solana" \
  || { fail "base image build failed"; exit 1; }
ok "base image ready."

log "generating emulation from solana_basic.py (arch: $EMU_ARCH) ..."
( cd "$HERE" && "$PYTHON_BIN" solana_basic.py "$EMU_ARCH" ) \
  || { fail "emulation generation failed"; exit 1; }
[[ -f "$OUTPUT_DIR/docker-compose.yml" ]] || { fail "no docker-compose.yml produced"; exit 1; }
ok "emulation generated."

log "applying Solana validator nofile ulimits ..."
ulimit_services="$(inject_solana_ulimits "$OUTPUT_DIR/docker-compose.yml")" \
  || { fail "failed to patch generated docker-compose.yml"; exit 1; }
ok "nofile ulimits applied to ${ulimit_services:-0} Solana services."

log "patching Solana runtime scripts for short epochs and validator stake delegation ..."
runtime_patch_result="$(patch_solana_runtime_scripts "$OUTPUT_DIR")" \
  || { fail "failed to patch generated Solana runtime scripts"; exit 1; }
ok "runtime scripts patched: $runtime_patch_result."

# seedemu node images do `FROM <digest>`, where each <digest> base image is
# built by a "dummy" compose service (one file per digest under output/dummies/).
# docker compose v2 builds services in parallel, so build these first.
dummy_services="$(ls "$OUTPUT_DIR/dummies" 2>/dev/null | tr '\n' ' ')"
if [[ -n "$dummy_services" ]]; then
  log "pre-building base images: $dummy_services"
  ( cd "$OUTPUT_DIR" && $COMPOSE build $dummy_services ) \
    || { fail "base (dummy) image build failed"; exit 1; }
fi

log "building containers and starting the cluster ..."
( cd "$OUTPUT_DIR" && $COMPOSE up -d --build ) \
  || { fail "docker compose up failed"; exit 1; }

ok "cluster containers are running."
echo "Verify with: ./test_solana.sh"
echo "Inspect bootstrap RPC with:"
echo "  BOOT=\$(docker ps --format '{{.Names}}' | grep '^as150h-Solana-Bootstrap-150-' | head -n 1)"
echo "  docker exec \"\$BOOT\" solana --url http://127.0.0.1:8899 cluster-version"
echo "Tear down manually with:"
echo "  (cd output && docker compose down -v --remove-orphans)"
