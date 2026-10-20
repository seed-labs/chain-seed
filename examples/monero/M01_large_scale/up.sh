#!/usr/bin/env bash
# Start an already compiled deployment in batches. Never regenerates output.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="$SCRIPT_DIR/output"
BATCH_SIZE="${BATCH_SIZE:-32}"
JOBS="${COMPOSE_PARALLEL_LIMIT:-8}"
usage() {
    cat <<'EOF'
Usage: ./up.sh [--output DIR] [--batch-size N] [--jobs N]
Start an existing output in batches, without building images or testing readiness.
COMPOSE_PROJECT_NAME defaults to chainseed-monero-m01. Requires Bash and Compose v2.
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
compose=(docker compose --project-name "${COMPOSE_PROJECT_NAME:-chainseed-monero-m01}" -f "$OUTPUT/docker-compose.yml")
services_file="$(mktemp)"
trap 'rm -f -- "$services_file"' EXIT
"${compose[@]}" config --services > "$services_file"
mapfile -t services < "$services_file"
(( ${#services[@]} > 0 )) || { printf 'Compose contains no services.\n' >&2; exit 2; }
for (( i=0; i<${#services[@]}; i+=BATCH_SIZE )); do
    end=$((i+BATCH_SIZE < ${#services[@]} ? i+BATCH_SIZE : ${#services[@]}))
    printf 'Starting services %s..%s / %s\n' "$((i+1))" "$end" "${#services[@]}"
    "${compose[@]}" up -d --no-build --no-deps "${services[@]:i:BATCH_SIZE}"
done
