#!/bin/bash
while read -r node; do {{
    let count=0
    ok=true
    validator=false
    until curl {curl_options}--http0.9 -fsS http://$node/testnet > /dev/null; do {{
        echo "eth: beacon-setup node $node not ready, waiting..."
        sleep {retry_interval}
        let count++
        [ $count -ge {retry_attempts} ] && {{
            echo "eth: connection to beacon-setup node $node failed too many times."
            exit 1
        }}
    }}; done
    ($ok) && {{
        validatorAtGenesis={is_validator_at_genesis}
        validatorAtRunning={is_validator_at_running}

        curl {curl_options}--http0.9 -fsS http://$node/testnet > /tmp/testnet.tar.gz || exit 1
        mkdir /tmp/bn
        tar -xzvf /tmp/testnet.tar.gz -C /tmp/bn || exit 1

        ($validatorAtGenesis || $validatorAtRunning) && {{
            mkdir /tmp/vc
            tar -xzvf /tmp/testnet.tar.gz -C /tmp/vc || exit 1
        }}


        ($validatorAtGenesis) && {{
            eth2-val-tools keystores --source-mnemonic {validator_mnemonic} --source-max {validator_key_end} --source-min {validator_key_start} --out-loc "/tmp/vc/assigned_data"
            mkdir /tmp/vc/local-testnet/testnet/validators
            cp -r /tmp/vc/assigned_data/keys/* /tmp/vc/local-testnet/testnet/validators/
            cp -r /tmp/vc/assigned_data/secrets /tmp/vc/local-testnet/testnet/
        }}





        ($validatorAtRunning) && {{
        echo "creating validator wallet and deposit"
        {wallet_create_command}
        {validator_create_command}
        {validator_deposit_sh}
        }}

        # while loop till bc client is ready
        while ! curl {curl_options}--http0.9 -sS http://{ip_address}:8000 > /dev/null; do
            echo "eth: local beacon node not ready, waiting..."
            sleep 3
        done


        ($validatorAtGenesis || $validatorAtRunning) && {{
        echo "[validator client] starting lighthouse validator client"
        {vc_start_command}
        }}

    }}
}}; done < /tmp/beacon-setup-node


