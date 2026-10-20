# this is meant to be built with the root of this repo as build-context
FROM golang:1.23-bookworm AS build-env

WORKDIR /
RUN git clone https://github.com/gobitfly/beaconchain.git
WORKDIR /beaconchain/backend
COPY . .
RUN go mod download
ARG target=all
RUN git config --global --add safe.directory '*' && make -B $target
    

# final stage
FROM debian:bookworm-slim
ENV POSTGRES_PORT=$POSTGRES_PORT\
    ALLOY_PORT=$ALLOY_PORT\
    LBT_PORT=$LBT_PORT\
    RBT_PORT=$RBT_PORT\
    EL_PORT=$EL_PORT\
    CL_PORT=$CL_PORT\
    REDIS_PORT=$REDIS_PORT\
    REDIS_SESSIONS_PORT=$REDIS_SESSIONS_PORT\
    SERVER_HOST=$SERVER_HOST
RUN apt-get update && \
    apt-get install -y \
        curl \
        jq \
        ca-certificates \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build-env /beaconchain/backend/bin /usr/local/bin/
COPY --from=build-env /beaconchain/backend/local_deployment/provision-explorer-config-custom.sh /app/local_deployment/provision-explorer-config-custom.sh
COPY --from=build-env /beaconchain/backend/local_deployment/mainnet.chain.yml /app/local_deployment/mainnet.chain.yml
COPY start.sh /
RUN chmod +x /start.sh \
    && chmod +x /app/local_deployment/provision-explorer-config-custom.sh
ENTRYPOINT ["/start.sh"]
