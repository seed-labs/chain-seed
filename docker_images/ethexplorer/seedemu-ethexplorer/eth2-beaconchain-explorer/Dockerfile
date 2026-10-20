# syntax=docker/dockerfile:1.7

# --------------------------
# Stage 0: Node runtime
# --------------------------
FROM node:24-bookworm AS node-env
# --------------------------
# Stage 1: Build Go binaries
# --------------------------
FROM golang:1.23-bookworm AS build-env

COPY --from=node-env /usr/local /usr/local
WORKDIR /
RUN git clone https://github.com/gobitfly/eth2-beaconchain-explorer.git
WORKDIR /eth2-beaconchain-explorer
COPY . .

RUN --mount=type=cache,target=/root/.npm \
    npm ci

RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

ARG target=all

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    git config --global --add safe.directory '*' && \
    make -B "${target}"
# --------------------------
# Stage 2: Runtime image
# --------------------------
FROM debian:bookworm-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libssl3 \
    curl \
    jq \
 && rm -rf /var/lib/apt/lists/*

ENV POSTGRES_PORT=$POSTGRES_PORT \
    ALLOY_PORT=$ALLOY_PORT \
    LBT_PORT=$LBT_PORT \
    RBT_PORT=$RBT_PORT \
    EL_PORT=$EL_PORT \
    CL_PORT=$CL_PORT \
    REDIS_PORT=$REDIS_PORT \
    REDIS_SESSIONS_PORT=$REDIS_SESSIONS_PORT \
    SERVER_HOST=$SERVER_HOST

WORKDIR /app

RUN mkdir -p /app/local-deployment

COPY --from=build-env /eth2-beaconchain-explorer/bin/explorer /app/
COPY --from=build-env /eth2-beaconchain-explorer/bin/validator-tagger /app/
COPY --from=build-env /eth2-beaconchain-explorer/bin/frontend-data-updater /app/
COPY --from=build-env /eth2-beaconchain-explorer/config/ /app/config/

COPY local-deployment/provision-explorer-config-custom.sh \
     local-deployment/mainnet.chain.yml \
     /app/local-deployment/

COPY start.sh /start.sh

RUN chmod +x /start.sh \
    && chmod +x /app/local-deployment/provision-explorer-config-custom.sh

ENTRYPOINT ["/start.sh"]