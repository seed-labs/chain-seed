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
   
        curl {curl_options}--http0.9 -fsS http://$node/testnet > /tmp/testnet.tar.gz || exit 1
        mkdir /tmp/bn
        tar -xzvf /tmp/testnet.tar.gz -C /tmp/bn || exit 1

        echo "[beacon_client] starting lighthouse beacon client"
        {bc_start_command}

      
}}; done < /tmp/beacon-setup-node


