# Case studies

Install SeedEmu and ChainSeed in the same Python environment. Run the commands
in each example's manual from the repository root. Docker examples require a
Linux Docker host and Compose; run one deployment at a time.

| Example | Experiment |
| --- | --- |
| [CS1 KnockBlock](CS1_knockblock/) | BGP hijacking, missed proposer slots and recovery |
| [CS2 Blockchain Amplification](CS2_blockchain_amplification/) | Invalid-transaction amplification tests and custom Geth deployment |
| [CS3 TopoShot](CS3_toposhot/) | Replacement-transaction probing and topology-discovery precision/recall |
| [CS4 Eth2.0-NA](CS4_eth20_na/) | Beacon target peers, traffic and sampled head spread |

Each case contains its own network construction and helper functions.

SeedEmu's Docker compiler must support forwarding through emulated routers
(for example, its `nat-unprotected` bridge configuration). Network configuration
comes from SeedEmu; these examples do not patch Compose bridge modes.

Generated deployments and results are excluded from version control. Each
example provides deployment and measurement steps. Measured values depend on
the client versions, machine and run.
