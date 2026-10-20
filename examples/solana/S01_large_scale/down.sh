#!/usr/bin/env bash
# Stop this Compose deployment in batches, then remove its containers/networks.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="$SCRIPT_DIR/output"
BATCH_SIZE="${BATCH_SIZE:-32}"
JOBS="${COMPOSE_PARALLEL_LIMIT:-8}"
usage() {
    cat <<'EOF'
Usage: ./down.sh [--output DIR] [--batch-size N] [--jobs N]
Stop project containers in batches, then Compose down. Keeps output and records.
Use the same COMPOSE_PROJECT_NAME as up.sh (default chainseed-solana-s01).
EOF
}
while (( $# )); do
    case "$1" in
        --output|--batch-size|--jobs)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            case "$1" in --output) OUTPUT="$2" ;; --batch-size) BATCH_SIZE="$2" ;; --jobs) JOBS="$2" ;; esac
            shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
for value in "$BATCH_SIZE" "$JOBS"; do
    [[ "$value" =~ ^[1-9][0-9]*$ ]] || { printf 'Batch size and jobs must be positive integers.\n' >&2; exit 2; }
done
[[ -f "$OUTPUT/docker-compose.yml" ]] || { printf 'No Compose file in %s\n' "$OUTPUT" >&2; exit 2; }
OUTPUT="$(cd -- "$OUTPUT" && pwd)"
export COMPOSE_PARALLEL_LIMIT="$JOBS"
compose=(docker compose --project-name "${COMPOSE_PROJECT_NAME:-chainseed-solana-s01}" -f "$OUTPUT/docker-compose.yml")
containers_file="$(mktemp)"
trap 'rm -f -- "$containers_file"' EXIT
"${compose[@]}" ps -a -q > "$containers_file"
mapfile -t containers < "$containers_file"
for (( i=0; i<${#containers[@]}; i+=BATCH_SIZE )); do
    end=$((i+BATCH_SIZE < ${#containers[@]} ? i+BATCH_SIZE : ${#containers[@]}))
    printf 'Stopping containers %s..%s / %s\n' "$((i+1))" "$end" "${#containers[@]}"
    # Continue to Compose cleanup if a container disappeared during shutdown.
    docker stop --time 10 "${containers[@]:i:BATCH_SIZE}" || printf 'Some batch stops failed; continuing project cleanup.\n' >&2
done
"${compose[@]}" down --timeout 10 --remove-orphans

# Remove only generated runtime state; retain compiled keys and experiment records.
for file in "$OUTPUT"/solana_start_barrier/*.ready; do
    if [[ -f "$file" ]]; then rm -f -- "$file"; fi
done
for file in genesis-ledger.tar genesis-ledger.tar.tmp genesis.bin; do
    rm -f -- "$OUTPUT/solana_genesis_shared/$file"
done
