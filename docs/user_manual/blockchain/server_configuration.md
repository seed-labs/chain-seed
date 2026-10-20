# Ethereum Server configuration

Create a Server and configure that instance before calling `emu.render()`.
There are no chain-wide client defaults or inherited tuning values.

```python
geth0 = (chain.createGethNode("geth-0")
         .setCacheMiB(128)
         .setGoMemoryLimitMiB(384)
         .setRpcTxFeeCap(0))
geth1 = chain.createGethNode("geth-1").setGoMemoryLimitMiB(512)

beacon = (chain.createBeaconNode("beacon-0")
          .setProcessorMaxWorkers(2)
          .setReconstructHistoricStates(False)
          .enableMetrics(port=5054)
          .connectToGethNode("geth-0"))

vc = (chain.createVcNode("vc-0")
      .setValidatorKeyCount(100)
      .enablePOSValidatorAtGenesis()
      .connectToBeaconNode("beacon-0"))

setup = chain.createBeaconSetupNode("beaconsetup").setGenesisDelay(1800)
```

Bind the virtual nodes to network hosts and add the Ethereum service as usual.
The [E10 example](../../../examples/ethereum/E10_large_scale/README.md) shows the
complete network, client, binding and compilation steps.

| Server | API | Default when not configured |
| --- | --- | --- |
| Geth | `setCacheMiB(value)` | Geth's default cache; no extra flag |
| Geth | `setGoMemoryLimitMiB(value)` | No GOMEMLIMIT override |
| Geth | `setRpcTxFeeCap(value)` | Geth's default RPC fee cap |
| Beacon | `setProcessorMaxWorkers(value)` | Lighthouse's default worker count |
| Beacon | `setReconstructHistoricStates(enabled)` | Enabled, preserving existing examples |
| Beacon | `enableMetrics(enabled=True, port=5054, address="0.0.0.0")` | Disabled |
| Beacon | `setSubscribeAllSubnets(enabled=True)` | Disabled |
| VC | `setValidatorKeyCount(count)` | One genesis validator key |
| BeaconSetup | `setGenesisDelay(seconds)` | Zero seconds after setup startup |
| BeaconSetup | `setValidatorMnemonic(mnemonic)` | Existing example mnemonic |
| Beacon / VC | `setBootstrapRetryPolicy(...)` | 60 attempts, 10-second interval; curl's default timeouts |

Cache accepts non-negative integer MiB; Go memory and worker budgets must be
positive integers. RPC fee caps are non-negative ETH; zero disables the cap.
`GOMEMLIMIT` is a Go runtime soft budget, not a container memory limit. It is
attached only to the Geth launch command, not the whole container.
`setReconstructHistoricStates(False)` omits the reconstruction flag; it does not
remove existing database contents. `enableMetrics(False)` disables metrics again.
Metrics ports must not conflict with another Ethereum endpoint on the same host.
Options must be supported by the client binaries in the selected image.

Download settings belong to each Beacon or VC:

```python
beacon.setBootstrapRetryPolicy(
    attempts=720,
    interval_seconds=10,
    connect_timeout_seconds=5,
    request_timeout_seconds=120,
)
```

Each call replaces the complete download policy. The optional timeouts are in
seconds; `None` uses curl's default. Testnet readiness failures stop that node's
bootstrap script after the configured attempts. Curl timeouts also apply to the
VC's subsequent Beacon readiness requests; that readiness loop continues until
the Beacon responds.

Each genesis VC may have a different key count. For counts 2, 3 and 1, the service
allocates `[0, 2)`, `[2, 5)` and `[5, 6)` in logical registration order. The same
ranges drive BeaconSetup's mnemonic configuration and VC key import. Withdrawal
addresses remain specific to each VC. Set a shared derivation mnemonic on the
BeaconSetup instance; all genesis VCs use it. Multi-key configuration currently
requires `enablePOSValidatorAtGenesis()`; runtime deposits remain a separate step.

Setters update Python instance fields. During `render()`, bindings resolve into
addresses and Servers generate commands/configuration through Node APIs. The
Docker compiler copies or mounts these artifacts. At container startup Geth
receives `env GOMEMLIMIT=384MiB geth ... --cache 128`, while Lighthouse receives
`--beacon-processor-max-workers 2`. Docker does not interpret these client options.
Client tuning and connection setters reject changes after rendering; changing a
running deployment requires regenerating output and recreating affected containers.

Existing `setCustomGethCommandOption(...)` arguments are included in the Geth
command. A custom `--cache` or `--rpc.txfeecap` conflicts with the corresponding
explicit Server API and is rejected during rendering.


To attach EthExplorer to a particular observation node, use its virtual node name:

```python
docker.enableEthExplorer("pos", geth_vnode="geth-0", beacon_vnode="beacon-0")
```

The selected Geth must call `enableGethHttp()` and the selected Beacon must retain
`setReconstructHistoricStates(True)`. Both must belong to the requested chain.
Without selectors the component chooses eligible nodes automatically. The
configured Geth HTTP RPC port is forwarded to both Explorer services.
See the [E02 manual](../../../examples/ethereum/E02_eth_explorer/README.md).


## Geth static peers

Geth execution Servers (PoA, PoW or PoS) can name other Geth Servers as persistent
outbound peers. Configure each instance before rendering; targets may be created
after the declarations.

```python
geth0 = chain.createGethNode("geth-0")
geth0.setStaticPeers(["geth-1"])
geth1 = chain.createGethNode("geth-1")
geth1.addStaticPeer("geth-2")
geth2 = chain.createGethNode("geth-2")
geth2.setStaticPeers([])

for server in (geth0, geth1, geth2):
    server.setNoDiscover(True)
    server.setMaxPeers(8)
```

This declares a path: geth-0 dials geth-1, and geth-1 dials geth-2. An established
connection carries traffic in both directions. Declarations do not modify the
target Server's static list. `setStaticPeers()` replaces the list;
`addStaticPeer()` appends one name; duplicates are ignored. `getStaticPeers()`
returns a copy. An empty list configures no outbound static peers.

`setNoDiscover(True)` separately disables Geth discovery. Apply it to all Geth
participants when studying a fixed set of links. It also skips Geth bootnode
HTTP downloads during startup. Static lists do not impose inbound restrictions:
other reachable nodes may still initiate connections. Inspect actual connections
with Geth's `admin.peers` or Lookingglass before treating a graph as observed
experimental ground truth.

At render time, peer names must exist, identify Geth execution Servers in the
same blockchain, and differ from the source name. Each participating Server gets
a pinned client identity. The service combines public keys with bound local IPs
and port 30303 to generate `Node.P2P.StaticNodes` in `/tmp/geth-peers.toml`.
The Geth command receives `--config /tmp/geth-peers.toml` and
`--nodekey /tmp/geth-p2p-nodekey`. These are real execution-client identities,
separate from the auxiliary discovery bootnode on port 30301. A referenced target
also receives its pinned identity even if it has no static-list declaration.

P2P keys are generated once per Server instance. Save an unrendered emulator with
`emu.dump(...)` and reload it to reuse identities with different network bindings.
Building a new model from scratch generates new identities. Node keys contain
private key material, like the other generated emulator keys. `getP2PEnode()`
returns the planned public enode after render for participating nodes, otherwise
`None`; it does not query a running client.

`setMaxPeers(count)` emits Geth's `--maxpeers` option; leave it unset to use the
client default. Zero disables P2P and is rejected with non-empty static lists.
This is a client peer budget, not a declaration of the expected graph's degree.
Custom Geth flags that override managed node keys, config files, port 30303 or an
explicit maxpeers value are rejected rather than silently changing planned peers.
Servers without static declarations or references keep the existing identity and
bootstrap behavior. This API currently applies to Geth execution clients.
