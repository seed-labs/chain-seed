#! /bin/bash

POSTGRES_HOST=${POSTGRES_HOST:-postgres}
POSTGRES_PORT=${POSTGRES_PORT:-5432}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-pass}
POSTGRES_USER=${POSTGRES_USER:-postgres}
POSTGRES_DB=${POSTGRES_DB:-db}
ALLOY_PORT=${ALLOY_PORT:-5432}
CLICKHOUSE_PORT=${CLICKHOUSE_PORT:-9000}
LBT_PORT=${LBT_PORT:-9000}
RBT_PORT=${RBT_PORT:-9000}
EL_HOST=${EL_HOST:-192.168.254.128}
EL_PORT=${EL_PORT:-8545}
CL_HOST=${CL_HOST:-192.168.254.128}
CL_PORT=${CL_PORT:-8000}
REDIS_PORT=${REDIS_PORT:-6379}
REDIS_SESSIONS_PORT=${REDIS_SESSIONS_PORT:-6379}
SERVER_PORT=${SERVER_PORT:-5000}
CLICKHOUSE_DB=${CLICKHOUSE_DB:-beaconchain}

export POSTGRES_HOST=$POSTGRES_HOST POSTGRES_PORT=$POSTGRES_PORT POSTGRES_PASSWORD=$POSTGRES_PASSWORD POSTGRES_USER=$POSTGRES_USER POSTGRES_DB=$POSTGRES_DB CLICKHOUSE_DB=$CLICKHOUSE_DB

########################################
# Common Retry Function - JSON RPC
########################################

retry_rpc_method() {
  local rpc_url="$1"
  local method="$2"

  local resp
  local value

  local i=0
  while true; do
    i=$((i + 1))
    echo "[$method] Attempt $i..." >&2

    resp=$(curl -sS --fail -X POST "$rpc_url" \
      -H "Content-Type: application/json" \
      -d "{
        \"jsonrpc\":\"2.0\",
        \"method\":\"$method\",
        \"params\":[],
        \"id\":1
      }" 2>/dev/null)

    value=$(echo "$resp" | jq -er '.result // empty' 2>/dev/null || true)

    if [ -n "$value" ]; then
      echo "[$method] Success: $value" >&2
      echo "$value"

      return 0
    fi

    echo "[$method] Failed response:" >&2
    echo "$resp" >&2

    echo "[$method] Retrying in 30s..." >&2
    sleep 30
  done

  echo "[$method] Failed after retries" >&2
  return 1
}

########################################
# Beacon Genesis
########################################

URL="http://${CL_HOST}:${CL_PORT}/eth/v1/beacon/genesis"

count=0
while true; do
  count=$((count + 1))
  echo "[Genesis] Attempt $count..."

  RESP=$(curl -sS --fail "$URL" 2>/dev/null)

  GENESIS_TIMESTAMP=$(echo "$RESP" | jq -er '.data.genesis_time // empty' 2>/dev/null || true)
  GENESIS_VALIDATORSROOT=$(echo "$RESP" | jq -er '.data.genesis_validators_root // empty' 2>/dev/null || true)

  if [ -n "$GENESIS_TIMESTAMP" ] && [ -n "$GENESIS_VALIDATORSROOT" ]; then
    echo "[Genesis] Success!"
    echo "[Genesis] GENESIS_TIMESTAMP=$GENESIS_TIMESTAMP"
    echo "[Genesis] GENESIS_VALIDATORS_ROOT=$GENESIS_VALIDATORSROOT"
    break
  fi

  echo "[Genesis] Failed response:"
  echo "$RESP"

  echo "[Genesis] Retrying in 30s..."
  sleep 30
done

if [ -z "$GENESIS_TIMESTAMP" ] || [ -z "$GENESIS_VALIDATORSROOT" ]; then
  echo "Failed to get GENESIS_TIMESTAMP or GENESIS_VALIDATORSROOT"
  exit 1
fi

########################################
# Execution Layer RPC
########################################

RPC_URL="http://${EL_HOST}:${EL_PORT}"

CHAIN_HEX=$(
  retry_rpc_method \
    "$RPC_URL" \
    "eth_chainId"
)

NETWORK_ID=$(
  retry_rpc_method \
    "$RPC_URL" \
    "net_version"
)

if [ -z "$CHAIN_HEX" ]; then
  echo "Failed to get CHAIN_HEX"
  exit 1
fi

if [ -z "$NETWORK_ID" ]; then
  echo "Failed to get NETWORK_ID"
  exit 1
fi

CHAIN_ID=$((CHAIN_HEX))

echo "chainId (dec): $CHAIN_ID"
echo "networkId (dec): $NETWORK_ID"

FILE="/app/local_deployment/mainnet.chain.yml"
sed -i "s/^DEPOSIT_CHAIN_ID:.*/DEPOSIT_CHAIN_ID: ${CHAIN_ID}/" "$FILE"
sed -i "s/^DEPOSIT_NETWORK_ID:.*/DEPOSIT_NETWORK_ID: ${NETWORK_ID}/" "$FILE"

touch config.yml

cat >config.yml <<EOL
justV2: false
# Database credentials
readerDatabase:
  name: $POSTGRES_DB
  host: $POSTGRES_HOST
  port: $POSTGRES_PORT
  user: $POSTGRES_USER
  password: $POSTGRES_PASSWORD
writerDatabase:
  name: $POSTGRES_DB
  host: $POSTGRES_HOST
  port: $POSTGRES_PORT
  user: $POSTGRES_USER
  password: $POSTGRES_PASSWORD
alloyReader:
  name: $POSTGRES_DB
  host: $POSTGRES_HOST
  port: $POSTGRES_PORT
  user: $POSTGRES_USER
  password: $POSTGRES_PASSWORD
alloyWriter:
  name: $POSTGRES_DB
  host: $POSTGRES_HOST
  port: $POSTGRES_PORT
  user: $POSTGRES_USER
  password: $POSTGRES_PASSWORD
bigtable:
  project: explorer
  instance: explorer
  emulator: true
  emulatorPort: $LBT_PORT
  emulatorHost: littlebigtable
rawBigtable:
  project: rawExplorer
  instance: rawExplorer
  emulator: true
  emulatorPort: $RBT_PORT
  emulatorHost: rawbigtable
eth1ErigonEndpoint: 'http://$EL_HOST:$EL_PORT'
eth1GethEndpoint: 'http://$EL_HOST:$EL_PORT'
redisCacheEndpoint: 'redis:$REDIS_PORT'
redisSessionStoreEndpoint: 'redis:$REDIS_SESSIONS_PORT'
tieredCacheProvider: 'redis'

clickHouseEnabled: true
validatorTagger:
  enabled: true
  schedulerEnabled: true

# Chain network configuration (example will work for the prysm testnet)
chain:
  name: "mainnet"

  genesisTimestamp: $GENESIS_TIMESTAMP
  genesisValidatorsRoot: $GENESIS_VALIDATORSROOT
  clConfigPath: ./local_deployment/mainnet.chain.yml
  pectraWithdrawalRequestContractAddress: "0x0000000000000000000000000000000000000000"
  pectraConsolidationRequestContractAddress: "0x0000000000000000000000000000000000000000"

clickhouse:
  readerDatabase:
    user: beacon
    password: "pass"
    name: beaconchain
    host: clickhouse
    port: $CLICKHOUSE_PORT
    ssl: false

  writerDatabase:
    user: beacon
    password: "pass"
    name: beaconchain
    host: clickhouse
    port: $CLICKHOUSE_PORT
    ssl: false

# Note: It is possible to run either the frontend or the indexer or both at the same time
# Frontend config
frontend:
  sessionSameSiteNone: false
  siteDomain: "localhost:$SERVER_PORT"
  siteName: 'Open Source Ethereum (ETH) Testnet Explorer' # Name of the site, displayed in the title tag
  siteSubtitle: "Showing a local testnet."
  csrfAuthKey: '0123456789abcdef000000000000000000000000000000000000000000000000'
  jwtSigningSecret: "0123456789abcdef000000000000000000000000000000000000000000000000"
  jwtIssuer: "beaconcha.in"
  jwtValidityInMinutes: 30
  server:
    host: "0.0.0.0" # Address to listen on
    port: $SERVER_PORT # Port to listen on
  readerDatabase:
    name: $POSTGRES_DB
    host: $POSTGRES_HOST
    port: $POSTGRES_PORT
    user: $POSTGRES_USER
    password: $POSTGRES_PASSWORD
  writerDatabase:
    name: $POSTGRES_DB
    host: $POSTGRES_HOST
    port: $POSTGRES_PORT
    user: $POSTGRES_USER
    password: $POSTGRES_PASSWORD
  sessionSecret: "11111111111111111111111111111111"

# Indexer config
indexer:
  enabled: true # Enable or disable the indexing service
  fullIndexOnStartup: false # Perform a one time full db index on startup
  indexMissingEpochsOnStartup: false # Check for missing epochs and export them after startup
  node:
    host: $CL_HOST
    port: $CL_PORT
    type: lighthouse
EOL

echo "generated config written to config.yml"

echo "initializing bigtable schema"
cd ..
bc misc -config local_deployment/config.yml -command initBigtableSchema
echo "bigtable schema initialization completed"

echo "provisioning postgres db schema"
bc misc -config local_deployment/config.yml -command applyDbSchema -target-version -2 -target-database postgres
echo "postgres db schema initialization completed"

echo "provisioning clickhose db schema"
bc misc -config local_deployment/config.yml -command applyDbSchema -target-version -2 -target-database clickhouse
echo "clickhose db schema initialization completed"
