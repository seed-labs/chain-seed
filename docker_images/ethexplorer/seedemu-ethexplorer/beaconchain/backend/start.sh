#! /bin/bash

stopit() {
  echo "trapped SIGINT"
  exit 0
}

trap stopit SIGINT

echo "run provision-explorer-config-custom.sh ..."
cd /app/local_deployment
chmod +x provision-explorer-config-custom.sh
./provision-explorer-config-custom.sh

if [ $? -eq 0 ]; then
  echo "SUCCESS: script executed normally"
else
  echo "ERROR: script failed"
  exit 1
fi

cd /app
echo "start ..."
echo "run eth1indexer"
bc eth1indexer -config /app/local_deployment/config.yml -concurrency 1 -blocks.tracemode 'geth' &
echo "run rewards-exporter"
bc rewards-exporter -config /app/local_deployment/config.yml &
echo "run statistics"
bc statistics -config /app/local_deployment/config.yml --charts.enabled --graffiti.enabled -validators.enabled -deposits.enabled &
echo "end."

while true; do
  date
  sleep 1
done
