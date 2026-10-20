#! /bin/bash

stopit() {
  echo "trapped SIGINT"
  exit 0
}

trap stopit SIGINT

echo "run provision-explorer-config-custom.sh ..."
cd /app/local-deployment
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
echo "run explorer"
/app/explorer -config /app/local-deployment/config.yml &
echo "run validator-tagger"
/app/validator-tagger -config /app/local-deployment/config.yml -schedule true &
echo "run frontend-data-updater"
/app/frontend-data-updater -config /app/local-deployment/config.yml &
echo "end."

while true; do
  date
  sleep 1
done
