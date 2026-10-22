# ChainSeed

中文 | [English](README.md)

ChainSeed 是一个基于 [SEED Internet Emulator](https://github.com/seed-labs/seed-emulator)
构建的可扩展、高保真区块链仿真器。它将真实区块链客户端与可配置的路由网络相结合，
使研究人员能够在可控的网络条件下研究区块链的性能、安全性和应用。

ChainSeed 支持 Ethereum、Monero、Solana 以及 Chainlink 服务，并提供相应的 API 和工具，
用于配置节点、定制创世状态和节点连接、部署智能合约，以及生成交易负载。
监控与可视化工具帮助用户查看链上活动和节点运行状态，仓库中的例子涵盖私有测试网络、
大规模部署和安全实验。

## 安装

ChainSeed 依赖 SeedEmu。请参考
[SeedEmu 安装说明](https://github.com/seed-labs/seed-emulator/blob/development/README.md#getting-started)
配置所需环境，包括 Python 3.10、Docker Engine 和 Docker Compose，
然后安装 SeedEmu 的 `development` 分支。
建议在安装 ChainSeed 前运行一个基础 SeedEmu 例子，确认环境正常。

将两个仓库克隆到同一个工作目录中，其中 SeedEmu 使用 `development` 分支：

```bash
mkdir -p workspace
cd workspace

git clone --branch development https://github.com/seed-labs/seed-emulator.git
git clone https://github.com/seed-labs/chain-seed.git
```

```text
workspace/
├── seed-emulator/
└── chain-seed/
```

进入 `chain-seed` 目录，再选择下面的 Conda 或 uv 安装方式。
命令中的 `../seed-emulator` 指向同级的 SeedEmu 源码目录。

```bash
cd chain-seed
```

### Conda

```bash
conda create -n chainseed python=3.10 pip -y
conda activate chainseed
python -m pip install -e ../seed-emulator
python -m pip install .
```

### uv

```bash
uv venv --python 3.10
source .venv/bin/activate
uv pip install -e ../seed-emulator
uv pip install .
```

SeedEmu 使用可编辑模式安装，因此安装后请保留其源码目录。

## 快速开始

在 `chain-seed` 目录下运行 Ethereum PoS 例子，生成 Docker 部署文件，
然后构建并启动容器：

```bash
python examples/ethereum/E01_ethereum_pos/ethereum_pos.py
cd examples/ethereum/E01_ethereum_pos/output
docker compose build
docker compose up -d
```

如需停止仿真并移除其容器和网络，在 `output` 目录下执行：

```bash
docker compose down
```

配置和访问方法见 [Ethereum PoS 例子](examples/ethereum/E01_ethereum_pos/README.md)。

区块链配置和部署例子见 [examples](examples/README.md)。复制例子时请保留完整的
`examples/` 目录，因为部分例子会复用其他例子的代码。

路由攻击、区块链放大攻击、拓扑发现和节点连接实验见
[case studies](case_study/README.md)。

## 监控与可视化

[EthExplorer](examples/ethereum/E02_eth_explorer/README.md) 提供 Web 界面，
用于浏览 Ethereum 区块、交易、epoch 和验证者信息。

[Lookingglass](docs/user_manual/blockchain/lookingglass.md) 提供仿真网络中
Ethereum 节点、对等连接和运行状态的全局视图。

## 文档

- [使用手册](docs/user_manual/blockchain/README.md)
- [Ethereum 客户端配置](docs/user_manual/blockchain/server_configuration.md)
- [交易发生器](tools/ethereum/transaction_generator/README.md)

## 许可证

ChainSeed 采用 [GNU 通用公共许可证第 3 版](LICENSE.txt)。
