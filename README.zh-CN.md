# ChainSeed

中文 | [English](README.md)

ChainSeed 是 [SeedEmu](https://github.com/seed-labs/seed-emulator) 的区块链
协议扩展仓库，负责 Ethereum、Monero、Solana 和 Chainlink 服务层，以及
对应的镜像配方、工具、示例、运行时探针和大规模实验定义。

依赖方向固定为：

```text
chain-seed -> seed-emulator
seed-emulator -X-> chain-seed
```

## 依赖关系与前置条件

ChainSeed 是 SeedEmu 的附加扩展，并不是能够单独使用的替代品。用户必须先
准备好可用的 SeedEmu 源码工作区和 Python 环境。在加入 ChainSeed 前，用户
应能在同一环境中成功渲染、编译、构建并运行一个不包含区块链的 SeedEmu
示例。

ChainSeed 可以导入 `seedemu` 已公开且有文档约束的 API。反方向上，SeedEmu
不得导入或打包 ChainSeed。同时，ChainSeed 服务代码应避免依赖 SeedEmu
编译器的私有实现，以免 SeedEmu 的正常内部重构不必要地破坏扩展。

## 软件包集成

区块链服务使用 `chainseed.*` 导入。
ChainSeed 服务通过 SeedEmu 现有的 `Node.setBaseSystem` API 声明与编译器无关的
`SystemProfile`；`ChainSeedDocker` 再把 ChainSeed 自有 profile 映射为对应平台的
镜像和部署组件。ChainSeed 不再依赖 SeedEmu 的区块链镜像表；区块链实现、
镜像、示例和协议测试由本仓库负责。SeedEmu Docker 仍保留旧实现；ChainSEED 独立使用本仓库的区块链实现。
EthExplorer 部署也由 ChainSeed 负责：Python 集成位于
`chainseed.ethereum.EthExplorer`，镜像配方保留在 `images/ethexplorer`。
SeedEmu 只为编译器子类提供受保护的 Compose 附加服务钩子；`ChainSeedDocker`
覆写该钩子，并完整拥有 EthExplorer 服务定义与网络接入。上游旧 Explorer 路径仍保留，ChainSEED 使用自己的组件。

可调用 `ethereum.createLookingglassServer()` 创建全局
[Lookingglass](docs/user_manual/blockchain/lookingglass.md)，像 Faucet 一样绑定到仿真主机。
它展示全部 Ethereum 链，默认自动映射宿主机 8765 端口；不创建则不启动。
运行代码和网页资源均包含在 ChainSeed 安装包内。

生成的 Compose 输出、客户端数据库、大规模原始采样、数据集、Python 缓存
和 Node 依赖缓存不提交到 Git。

## 普通安装

Python 发行名是 `chainseed`，导入名同样是 `chainseed`；仓库名仍为 `chain-seed`。
当前支持 Python 3.10，旧版 Web3 5 依赖升级前不支持 Python 3.11 及以上。
使用 SeedEmu `Docker` 分支（当前发行版本为 `0.0.7`）。ChainSEED 在导入时
检查 `SystemProfile` 和 Docker 扩展钩子，版本号本身不足以证明兼容性。
ChainSEED 尚未发布到 PyPI。

SeedEmu Docker 使用 editable 安装，ChainSEED 使用普通安装：

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -e ../seed-emulator
python -m pip install .
```

先从 SeedEmu `Docker` 源码安装，再安装 ChainSEED。虽然 ChainSEED 声明
了 SeedEmu 依赖，但 PyPI 上同版本的旧构建可能没有所需钩子。
SeedEmu 独立维护，目前仍保留其旧区块链实现。
SeedEmu Docker 的普通 wheel 缺少旧区块链模板资源，导入时会失败，
因此当前使用上述 editable 安装，保留源码目录。此问题需要由上游另行修复。
Docker、客户端镜像和 Node 工具链不由 Python 包安装提供。
通用 Docker 网络适配已移至 SeedEmu 的 Docker 分支，ChainSEED 不再覆写网络编译。E01 的 PoS 出块和签名 ETH 转账
已在 Docker 29.9.0 上验证通过；其他示例仍需动态验证。

## 联合开发安装

推荐将两个仓库放在同一个工作目录下并保持为兄弟目录：

```text
seed-workspace/
├── seed-emulator/
└── chain-seed/
```

两个仓库在技术上不依赖固定位置，但兄弟目录更便于跨仓库开发和示例复用。
不要把 ChainSeed clone 到 SeedEmu 仓库内部，以免形成嵌套 Git 仓库。

```bash
mkdir seed-workspace
cd seed-workspace

git clone --branch Docker https://github.com/seed-labs/seed-emulator.git
git clone https://github.com/seed-labs/chain-seed.git

python3 -m venv .venv
source .venv/bin/activate

python -m pip install -e ./seed-emulator
python -m pip install -e "./chain-seed[dev]"
```

本地编译检查和完整 Docker 生命周期使用与 CI 相同的入口：

```bash
chainseed-test compile chain-seed/examples/ethereum/E01_ethereum_pos/example.yaml
chainseed-test all chain-seed/examples/ethereum/E01_ethereum_pos/example.yaml
```

共享网络定义位于 `examples/ethereum/E00_ethereum_poa/mini_internet.py`，调用 SeedEmu 公开网络 API，支持 mini/full/hybrid 拓扑和网络 `.bin` 导出。
ChainSeed 示例不再依赖 SeedEmu 源码中的顶层 `examples` 目录。
示例脚本仍位于本仓库 `examples/`，使用时保留整个目录。

使用显式导入：

```python
from seedemu import Binding, Emulator, Filter
from chainseed import ChainSeedDocker
from chainseed.ethereum import ConsensusMechanism, EthereumService
from chainseed.monero import MoneroService
from chainseed.solana import SolanaService
```

## 版本兼容与首次 1.0.0 发布

ChainSeed 与 SeedEmu 独立发布。ChainSeed 可以发布新版本以适配新版
SeedEmu，而不要求 SeedEmu 同步发版；每个 ChainSeed 版本都必须明确声明
其支持的 SeedEmu 版本范围。

联合开发期间，两个仓库通过普通安装或 editable checkout 安装并一起测试。当前仍
保留 alpha 版本元数据，不提前声称兼容尚未发布的 SeedEmu API。

首次 `1.0.0` 的发布门禁是：

1. 完成两个仓库中的配套修改；
2. 本地测试和两个仓库的远端 CI/CD 全部通过；
3. 将两个项目的发布版本统一修改为 `1.0.0`；
4. 分别从两个仓库的当前远端发布 `v1.0.0`；
5. 从这两个 tag 重新安装并运行完整兼容性测试；
6. 再确认无误后，才向 SeedEmu 的 upstream 提交 PR。

ChainSeed 当前没有单独的 upstream，可以直接从当前远端发布。此过程中不得
向 SeedEmu upstream 推送 commit 或 tag。

联合发布后，ChainSeed 应使用有上下界的依赖，例如
`seedemu>=1.0.0,<2.0.0`；前提是 SeedEmu 对公共扩展 API 遵守语义化版本。
每次发布都应提供经过测试的兼容矩阵。

目录职责：

```text
chainseed/       Python 服务层和协议感知测试
images/          区块链客户端与 Explorer 镜像配方
tools/           Explorer、钱包和区块链工具
examples/        按链种分类的示例：chainlink、ethereum、monero、solana
experiments/     历史原型和示例
tests/           软件包、编译器与运行器检查
docs/            架构、集成与使用手册
```

目标架构和仍需补充的 SeedEmu 公共 API 见
[docs/design](docs/design/README.zh-CN.md)。

网络模式由 SeedEmu 的 Docker 分支配置，ChainSeedDocker 直接继承，
需要 Docker Engine 28 或更新版本。仿真的 Local/InternetExchange 网络使用 `gateway_mode_ipv4=nat-unprotected`，允许仿真路由器转发流量。
该模式允许直接路由访问网络中未发布的端口，适用于独立实验环境；外部 Bridge
网络保持上游默认配置。不修改 Docker daemon 的全局防火墙设置。
