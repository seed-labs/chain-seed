#!/usr/bin/env bash
# Start the core first; admit remaining voting-configured nodes after checking it.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="$SCRIPT_DIR/output"
PHASE=""
BATCH_SIZE=10
JOBS=2
BATCH_DELAY=20
usage() {
    echo 'Usage: ./up.sh --phase core|validators [--output DIR] [--batch-size N] [--jobs N] [--batch-delay SEC]'
}
while (( $# )); do
    case "$1" in
        --phase|--output|--batch-size|--jobs|--batch-delay)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            case "$1" in
                --phase) PHASE="$2" ;; --output) OUTPUT="$2" ;;
                --batch-size) BATCH_SIZE="$2" ;; --jobs) JOBS="$2" ;; --batch-delay) BATCH_DELAY="$2" ;;
            esac
            shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
[[ "$PHASE" == core || "$PHASE" == validators ]] || { usage >&2; exit 2; }
[[ "$BATCH_SIZE" =~ ^[1-9][0-9]*$ && "$JOBS" =~ ^[1-9][0-9]*$ && "$BATCH_DELAY" =~ ^[0-9]+$ ]] || exit 2
OUTPUT="$(cd -- "$OUTPUT" && pwd)"
export COMPOSE_PARALLEL_LIMIT="$JOBS"
compose=(docker compose --project-name "${COMPOSE_PROJECT_NAME:-chainseed-solana-s01}" -f "$OUTPUT/docker-compose.yml")
start_group() {
    local group="$1" i
    local -a services
    mapfile -t services < "$OUTPUT/$group-services.txt"
    for (( i=0; i<${#services[@]}; i+=BATCH_SIZE )); do
        printf 'Starting %s services %s..%s / %s\n' "$group" "$((i+1))" "$((i+BATCH_SIZE<${#services[@]}?i+BATCH_SIZE:${#services[@]}))" "${#services[@]}"
        "${compose[@]}" up -d --no-build --no-deps "${services[@]:i:BATCH_SIZE}"
        if (( i+BATCH_SIZE < ${#services[@]} && BATCH_DELAY > 0 )); then sleep "$BATCH_DELAY"; fi
    done
}
if [[ "$PHASE" == core ]]; then
    start_group infrastructure
    sleep 5
    start_group core
else
    start_group validators
fi
