# SeedEmu 去区块链内容：人工修改清单

本文路径均相对 seed-emulator 仓库根目录。本轮只清理已有区块链实现、依赖、入口和文字，
不引入 profiles/images 新设计，不做发行改造，不替你修改 SeedEmu。

你已分批移除部分镜像、示例、实验、辅助库、工具及旧 tests。已经不存在的文件直接跳过，
不要为了匹配旧方案重新创建。原方案的 550 删、55 改、3 新仅用于历史范围核对，不代表当前待办数量。

## 本轮边界

| 本轮做 | 本轮不做 |
|---|---|
| 删除旧服务、Explorer、区块链 runner 及其导入／导出 | 不改 SystemProfile.py、Service.py、Docker.py 的接口和行为 |
| 删除 BaseSystem 与 DockerImageConstant 中已有的区块链常量／映射键 | 不新增 getDockerImages、setDockerImage、validateProfiles 或编译器收集逻辑 |
| 删除区块链镜像构建资源、示例、文档引用 | 不设计新的 profile 别名或外部镜像映射机制 |
| A08 改为无区块链依赖的 BuildtimeDocker 示例 | 不新增通用镜像接口测试或安装包 smoke 脚本 |
| 移除 requirements 中区块链依赖 | 不改 1.0.0 版本、不改 build-system、extras、console_scripts，不升级其他依赖 |
| 清理 CI 中被删除的区块链路径 | 不增加 CI 项目或修改 Docker 网络／路由实现 |

删除旧常量属于清除原有区块链内容，不是实施新 profiles/images 设计。
只删 BaseSystem 而留下 DockerImageConstant 的引用会导致 import 报错，两者应同批处理。
这轮完成不等于 ChainSeed 已能使用新扩展机制；对接与发行由后续 PR 处理。

## 建议操作顺序

| 顺序 | 工作块 | 同批要求 |
|---|---|---|
| 1 | 已完成的镜像／示例／实验／工具删除 | 不重复操作；检查 CI 和文档是否还指向它们。 |
| 2 | 服务与 Explorer 删除 | 每删除一个服务，立即删除 __init__.py 中对应导入；Chainlink 等消费者也不能保留对已删除 Ethereum 的引用。 |
| 3 | 区块链 runner 删除 | 同批改 seedemu/testing 的 __init__、registry、CLI。 |
| 4 | BaseSystem 与 DockerImageConstant 清理 | 旧消费者移除后，两文件一起删专用常量及映射。 |
| 5 | 混合文档、Demo、seed-agent、A08、WannaCry | 各块独立审阅；保留通用网络部分。 |
| 6 | requirements 清理 | 确认剩余代码不再导入区块链库后操作。 |

## 当前仍存在的修改目标

以下每行给出具体操作；只修改相关行，不做整文件格式重排。

| 勾选 | 文件 | 具体怎么改 | 注意事项 |
|---|---|---|---|
| ☐ | `seedemu/core/BaseSystem.py` | 仅删除八个 SEEDEMU_* 区块链成员；完整删除名单及最终文件内容见下方。 | 保留现有 SystemProfile 类型和继承关系，不新增验证或映射接口。 |
| ☐ | `seedemu/compiler/DockerImageConstant.py` | 删除区块链 DockerImage 常量及两个平台映射表中的区块链键；最终保留项见下方。 | 必须与 BaseSystem 删除同步；Platform 和通用网络镜像定义不动。 |
| ☐ | `seedemu/services/__init__.py` | 删除 EthereumService、MoneroService、SolanaService、ChainlinkService 的导入／导出。 | 每删除一个 Service，就同步删除其导出 |
| ☐ | `seedemu/containerBundle/__init__.py` | 删除 EthExplorer 导入及导出；将原来的 `all` 修正为 `__all__`，只保留 ContainerBundle、InternetMap。 | 与对应删除项同步 |
| ☐ | `seedemu/testing/__init__.py` | 删除 BlockchainTestRunner、EthereumRuntimeTest 的导入及 __all__ 条目；保留通用、Internet 和 Satellite 接口。 | 与对应删除项同步 |
| ☐ | `seedemu/testing/registry.py` | 删除两种导入路径中的 BlockchainTestRunner 及 RUNNER_REGISTRY 的 blockchain 项。 | 与对应删除项同步 |
| ☐ | `seedemu/testing/cli.py` | 从 --runner 选项中删除 blockchain；保留 generic、internet、satellite。 | 与对应删除项同步 |
| ☐ | `requirements.txt` | 删除 web3、eth-abi、eth-account、eth-hash、eth-keyfile、eth-keys、eth-rlp、eth-typing、eth-utils、hexbytes、rlp 等区块链直接依赖；按实际剩余 import 确认。 | 在旧区块链模块和消费者删除后做；保留 geopy、networkx、PyYAML、requests 等网络依赖，不顺便升级其他包。IPFS／通用加密库不能仅凭名称删除。 |
| ☐ | `.github/workflows/on-pull-request.yaml` | 只移除区块链入口与失效引用；具体删除项见后面的 CI 操作表。 | 不增加 wheel 检查、新测试、release 版本配置或 host sysctl 改动。 |
| ☐ | `tests/requirements.txt` | 删除旧区块链测试使用的 web3、eth-*、hexbytes、rlp 等依赖；你当前已删除旧 tests，需核对剩余 CI 是否仍安装此文件。 | 此阶段不建立 extras、不升级 Docker SDK 或 Faker；其余无用传递依赖可另开依赖清理 PR。 |
| ☐ | `examples/basic/A08_buildtime_docker/Dockerfile` | 去掉账户生成相关构建依赖，改用 Python 3.10 slim、/app 工作目录和 Python 入口。 | 与 A08 脚本替换同批 |
| ☐ | `examples/basic/A08_buildtime_docker/README.md` | 将演示目标改为生成 output/network.txt，继续说明 BuildtimeDocker 的构建与挂载。 | 与 A08 脚本替换同批 |
| ☐ | `examples/yesterday_once_more/Y04_wannacry/wannacry_emulator.py` | 只删除 install_blockchain_placeholder() 空实现及其调用；保留网络与蠕虫实验逻辑。 | 与对应删除项同步 |
| ☐ | `examples/yesterday_once_more/Y04_wannacry/safe_ransomware_sim.py` | 删除／替换说明文字中的后续区块链支付步骤。 | 与对应删除项同步 |
| ☐ | `examples/yesterday_once_more/Y04_wannacry/README.md` | 删除区块链支付／密钥释放占位说明，保留已有实验手册。 | 与对应删除项同步 |
| ☐ | `README.md` | 删除内置 Blockchain 能力描述；删除指向已移除区块链示例／文档的链接。保留原有安装和运行说明。 | 本轮不改版本、pip 安装流程、PYTHONPATH 用法或宿主机参数说明。 |
| ☐ | `CONTRIBUTING.md` | 删除正在研发区块链组件的描述，保留通用网络组件贡献说明。 | 与对应删除项同步 |
| ☐ | `docs/designs/readme.md` | 删除 Bitcoin 空章节及目录项。 | 与对应删除项同步 |
| ☐ | `docs/developer_manual/04-creating-a-new-experiment.md` | 删除 Ethereum Layer 2、CustomGenesis、CustomBlockchain 的示例和旧模块导入；保留通用实验目录、README、本地 lib 与继承说明。 | 本轮不补写 getDockerImages / setDockerImage 等未来接口，也不需要整篇重写。 |
| ☐ | `docs/developer_manual/10-kubo-service.md` | 只删除 Ethereum/IPFS dApp 教学规划小节；保留 Kubo 配置与实现说明。 | 与对应删除项同步 |
| ☐ | `docs/thoughts/layered_design.md` | 删除区块链层专用段落及区块链举例；保留通用分层设计。 | 与对应删除项同步 |
| ☐ | `docs/thoughts/todo.md` | 删除区块链开发任务小节；保留网络任务。 | 与对应删除项同步 |
| ☐ | `docs/user_manual/00_notes.md` | 删除旧区块链示例重排计划及相关合并笔记。 | 与对应删除项同步 |
| ☐ | `docs/user_manual/README.md` | 删除指向 blockchain 子目录的入口。 | 与对应删除项同步 |
| ☐ | `docs/user_manual/component.md` | 将内置组件列举中的 Blockchain 改为通用网络服务示例。 | 与对应删除项同步 |
| ☐ | `docs/user_manual/docker.md` | 删除区块链专用镜像介绍；将自定义镜像例子里的 handsonsecurity/seedemu-ethereum 改成 my-network-service:latest。 | 保留现有 DockerImage、addImage、setImageOverride 用法；不改镜像解析设计。 |
| ☐ | `labs/README.md` | 删除区块链实验小节／入口。 | 与对应删除项同步 |
| ☐ | `tools/DemoSystem/extensions/menus.yml` | 删除 blockchain 菜单对象及配图引用，保留其他菜单。 | 与两张 large_blockchain.png 同批 |
| ☐ | `tools/DemoSystem/frontend/src/extensions/index.ts` | 删除前端 blockchain 菜单配置，保留数组和类型结构。 | 与菜单 YAML／图片同批 |
| ☐ | `tools/seed-agent/PRINCIPLES.md` | 删除内置区块链服务、geth、MetaMask、Explorer 的能力举例，修整上下文句子。 | 只清理本仓库能力描述；人工检查断句、列表和路径，避免机械替换产生残句 |
| ☐ | `tools/seed-agent/agents/paper-researcher/AGENTS.md` | 删除区块链实验能力及论文候选类别，不改其他研究流程。 | 只清理本仓库能力描述；人工检查断句、列表和路径，避免机械替换产生残句 |
| ☐ | `tools/seed-agent/agents/paper-researcher/paper-fit-guide.md` | 删除 blockchain/oracle/distributed-ledger 专用类别及相关场景、采集指标。 | 只清理本仓库能力描述；人工检查断句、列表和路径，避免机械替换产生残句 |
| ☐ | `tools/seed-agent/knowledge/architecture.md` | 从架构与目录图中移除区块链服务和 examples/blockchain。 | 只清理本仓库能力描述；人工检查断句、列表和路径，避免机械替换产生残句 |
| ☐ | `tools/seed-agent/knowledge/capability-map.md` | 删除区块链／预言机能力块及示例、文档证据链接。 | 只清理本仓库能力描述；人工检查断句、列表和路径，避免机械替换产生残句 |
| ☐ | `tools/seed-agent/skills/seedemu-capability-refresh/SKILL.md` | 删除区块链专用检索关键词类别。 | 只清理本仓库能力描述；人工检查断句、列表和路径，避免机械替换产生残句 |
| ☐ | `tools/seed-agent/skills/seedemu-compose-scenario/SKILL.md` | 删除 examples/blockchain 模板路径。 | 只清理本仓库能力描述；人工检查断句、列表和路径，避免机械替换产生残句 |
| ☐ | `tools/seed-agent/skills/seedemu-paper-search/SKILL.md` | 删除描述与检索词中的 Ethereum、Chainlink、Monero、blockchain 能力。 | 只清理本仓库能力描述；人工检查断句、列表和路径，避免机械替换产生残句 |

## 关键文件的具体修改

### 1. 服务导出：seedemu/services/__init__.py

删除以下四行，其余网络服务导入保留：

```python
from .EthereumService import *
from .MoneroService import *
from .SolanaService import *
from .ChainlinkService import *
```

### 2. Explorer 导出：seedemu/containerBundle/__init__.py

删除 EthExplorer 的导入与导出；最终内容为：

```python
from .ContainerBundle import ContainerBundle
from .InternetMap import InternetMap

__all__ = ["ContainerBundle", "InternetMap"]
```

### 3. 区块链 runner：seedemu/testing 下三个文件

| 文件 | 删除内容 | 保留内容 |
|---|---|---|
| `__init__.py` | `from .blockchain import BlockchainTestRunner, EthereumRuntimeTest`；__all__ 中这两个名称 | 通用 runner、Internet、Satellite、ComposeRuntimeTest 等原有导出 |
| `registry.py` | try 中的 `.blockchain` 导入、except 中的 `blockchain` 导入，以及 `"blockchain": BlockchainTestRunner` | generic、test、internet、satellite 的注册及 create_runner 逻辑 |
| `cli.py` | --runner 的 choices 中的 `"blockchain"` | choices 改为 `["generic", "internet", "satellite"]`；不改其他命令 |

三处引用移除后，删除 `seedemu/testing/blockchain.py`。

### 4. 删除 BaseSystem 的旧区块链成员

`seedemu/core/BaseSystem.py` 最终只保留：

```python
from .SystemProfile import SystemProfile


class BaseSystem:
    """Built-in network system profiles."""

    UBUNTU_20_04 = SystemProfile("ubuntu20.04")
    SEEDEMU_BASE = SystemProfile("seedemu-base", subset=UBUNTU_20_04)
    SEEDEMU_ROUTER = SystemProfile("seedemu-router", subset=SEEDEMU_BASE)
    DEFAULT = SEEDEMU_BASE
```

删除的八个成员及配套镜像常量如下，不能只删成员而保留后面的映射：

| BaseSystem 成员 | AMD64 常量 | ARM64 常量 |
|---|---|---|
| `SEEDEMU_ETHEREUM` | `ETHEREUM_IMAGE` | `ETHEREUM_IMAGE_ARM64` |
| `SEEDEMU_ETHEREUM_LEGACY` | `ETHEREUM_IMAGE_LEGACY` | `ETHEREUM_IMAGE_ARM64_LEGACY` |
| `SEEDEMU_ETHEREUM_POS` | `ETHEREUM_IMAGE_POS` | `ETHEREUM_IMAGE_ARM64_POS` |
| `SEEDEMU_MONERO` | `MONERO_IMAGE` | `MONERO_IMAGE_ARM64` |
| `SEEDEMU_SOLANA` | `SOLANA_IMAGE` | `SOLANA_IMAGE_ARM64` |
| `SEEDEMU_OP_STACK` | `OP_STACK_IMAGE` | `OP_STACK_IMAGE_ARM64` |
| `SEEDEMU_SC_DEPLOYER` | `SC_DEPLOYER_IMAGE` | `SC_DEPLOYER_IMAGE_ARM64` |
| `SEEDEMU_CHAINLINK` | `CHAINLINK_IMAGE` | `CHAINLINK_IMAGE_ARM64` |

### 5. 清理 DockerImageConstant，不引入新映射机制

在 `seedemu/compiler/DockerImageConstant.py` 删除上表两列的 DockerImage 对象声明，
并将两个内置映射表收缩为：

```python
BASESYSTEM_DOCKERIMAGE_MAPPING = {
    BaseSystem.UBUNTU_20_04: UBUNTU_IMAGE,
    BaseSystem.SEEDEMU_BASE: BASE_IMAGE,
    BaseSystem.SEEDEMU_ROUTER: ROUTER_IMAGE,
}

BASESYSTEM_ARM64_DOCKERIMAGE_MAPPING = {
    BaseSystem.UBUNTU_20_04: UBUNTU_IMAGE_ARM64,
    BaseSystem.SEEDEMU_BASE: BASE_IMAGE_ARM64,
    BaseSystem.SEEDEMU_ROUTER: ROUTER_IMAGE_ARM64,
}
```

原有 UBUNTU_IMAGE、BASE_IMAGE、ROUTER_IMAGE 及 ARM64 版本的镜像名、软件列表和 subset 不变。
`Platform` 枚举及 `BASESYSTEM_DOCKERIMAGE_MAPPING_PER_PLATFORM` 不变；不改 Docker.py。

### 6. CI 文件具体删除项

`.github/workflows/on-pull-request.yaml` 不要直接替换成之前的新 CI 版本，只做以下删除：

| 位置 | 操作 |
|---|---|
| selected-example options | 删除 D01、D10、D20、D21、D22、D23。 |
| workflow_dispatch inputs | 删除 run-blockchain-examples 输入项。 |
| env | 删除 RUN_BLOCKCHAIN_EXAMPLES。 |
| 静态 py_compile 命令 | 删除 seedemu/testing/blockchain.py 及 examples/blockchain 下的文件路径；注意剩余命令最后一行不要留下悬空反斜杠。 |
| manifest 检查命令 | 删除 examples/blockchain 下的 clean 命令。 |
| 各 job 的 matrix.example | 删除 category 为 blockchain 的对象；编译矩阵和运行矩阵都检查。 |
| 各 step 的 if | 删除 blockchain category / RUN_BLOCKCHAIN_EXAMPLES 对应分支，修好括号和逻辑运算符；保留 basic、internet 条件。 |
| 其他路径引用 | 删除对你已移除的旧 tests 文件的调用；保留仍存在的网络示例检查，不重新创建已删除的旧 tests。 |

### 7. A08 只替换业务内容

| 文件 | 操作 |
|---|---|
| create_eth_account.py | 删除，由 create_network_config.py 替代。 |
| create_network_config.py（本轮唯一计划新增文件） | 保留 BuildtimeDockerFile / BuildtimeDockerImage 的构建、挂载、执行、复制输出流程；镜像名由 ethaccount 改为 network-config；容器内使用标准库 `ipaddress.ip_network` 生成 `network.txt`；不再 import eth_account。 |
| Dockerfile | 使用 `FROM python:3.10-slim`、`WORKDIR /app`、`ENTRYPOINT ["python"]`；移除只为账户生成准备的构建依赖。 |
| README.md | 运行命令改为 python create_network_config.py，输出文件改为 output/network.txt；保留 BuildtimeDocker 的说明。 |

### 8. WannaCry 只去掉支付占位

删除 `wannacry_emulator.py` 中的 `install_blockchain_placeholder()` 空函数及调用；
清理其 README 和 safe_ransomware_sim.py 中“后续区块链支付／密钥释放”的文字。
不更改现有网络、服务、传播或本地恢复流程。

## 已删除的旧文件：无需再修改或恢复

以下是原方案中曾计划修改、但当前 release 已不存在的旧测试文件：

| 原路径 | 本轮处理 |
|---|---|
| `tests/__init__.py` | 已删除，跳过，不为本轮清理重新创建。 |
| `tests/run-tests.py` | 已删除，跳过，不为本轮清理重新创建。 |
| `tests/compile-and-build-test/compile-test.py` | 已删除，跳过，不为本轮清理重新创建。 |
| `tests/compile-and-build-test/compile-and-build-test.py` | 已删除，跳过，不为本轮清理重新创建。 |
| `tests/ci/run_ci.py` | 已删除，跳过，不为本轮清理重新创建。 |
| `tests/README.md` | 已删除，跳过，不为本轮清理重新创建。 |
| `tests/ci/README.md` | 已删除，跳过，不为本轮清理重新创建。 |
| `tests/internet/ip_anycast/README.md` | 已删除，跳过，不为本轮清理重新创建。 |
| `tests/internet/mini_internet/README.md` | 已删除，跳过，不为本轮清理重新创建。 |

## 明确留到后续 PR

| 文件／设计 | 本轮处理 |
|---|---|
| `seedemu/core/SystemProfile.py` 的 validateProfiles | 不修改。 |
| `seedemu/core/Service.py` 的 getDockerImages / setDockerImage 与新映射表 | 不修改。 |
| `seedemu/compiler/Docker.py` 的 _collectServiceImages / _imageDefinition | 不修改。 |
| profile 别名及 Service 到编译器的新镜像收集流程 | 不实施；由后续对接 PR 处理。 |
| `setup.py`、`pyproject.toml`、`.gitignore` 的发行改造 | 不纳入当前去区块链清理。 |
| `seedemu/__init__.py` 的 1.0.0 版本声明 | 不新增。 |
| `tests/test_service_images.py`、`tests/ci/installed_package_smoke.py` | 不新增。 |
| A09 同级示例路径修复 | 独立修复，不混入当前删除 PR。 |
| 旧 OSPF 断言修复 | 对应旧文件已删除，不恢复；不修改路由实现。 |

## 原方案删除目录对照

下表沿用历史删除范围便于人工核对；其中部分已提交，不是当前待删文件数。
镜像构建资源的删除与 profiles/images 新接口重构是两件事；以下不要求引入新接口。

### 历史删除范围（550 个）

删除目录指原方案中该目录的已跟踪文件；不要顺带删除个人未跟踪数据。
“有对应文件”不表示所有历史内容原样保留：旧测试、重复方案和占位内容按之前决定清理。

### 1. 镜像构建资源：39 个

| 勾选 | 删除路径 | 文件数 | 说明／联动 |
|---|---|---:|---|
| ☐ | `docker_images/seedemu-ethereum/` | 4 | 4 个文件；已在首批提交中删除。ChainSeed 对应 `docker_images/ethereum/`。 |
| ☐ | `docker_images/amd64/seedemu-ethereum/` | 3 | 已在首批提交中删除；对应 ChainSeed `docker_images/legacy/amd64/ethereum/`。 |
| ☐ | `docker_images/arm64/seedemu-ethereum/` | 3 | 已在首批提交中删除；对应 ChainSeed `docker_images/legacy/arm64/ethereum/`。 |
| ☐ | `docker_images/multiarch/seedemu-ethereum/` | 4 | 已在首批提交中删除；对应 ChainSeed `docker_images/legacy/multiarch/ethereum/`。 |
| ☐ | `docker_images/seedemu-chainlink/` | 2 | 对应 ChainSeed `docker_images/chainlink/`；保留阶段仍使用的远端镜像 tag。 |
| ☐ | `docker_images/seedemu-monero/` | 2 | 对应 ChainSeed `docker_images/monero/`。 |
| ☐ | `docker_images/seedemu-ethexplorer/` | 20 | 对应 ChainSeed `docker_images/ethexplorer/`；同步清理 D10 README 中的本地源码目录链接，或与 D10 一起删除。 |
| ☐ | `docker_images/seedemu-solana/` | 1 | 对应 ChainSeed `docker_images/solana/`；D70 的 `prepare_solana.sh` 直接读取该目录，应先删除／改好调用方，不能单独提前删。 |

### 2. 区块链实现及入口：79 个

| 勾选 | 删除路径 | 文件数 | 说明／联动 |
|---|---|---:|---|
| ☐ | `seedemu/services/EthereumService/` | 26 | 26 个文件对应 ChainSeed `chainseed/services/ethereum/`；同步移除 services 导出及其调用方。 |
| ☐ | `seedemu/services/ChainlinkService/` | 41 | 41 个文件对应 ChainSeed `chainseed/services/chainlink/`；同批处理导出。 |
| ☐ | `seedemu/services/MoneroService/` | 6 | 对应 ChainSeed `chainseed/services/monero/`；同批处理导出。 |
| ☐ | `seedemu/services/SolanaService/` | 4 | 对应 ChainSeed `chainseed/services/solana/`；同批处理导出。 |
| ☐ | `seedemu/containerBundle/EthExplorer.py` | 1 | 对应 ChainSeed `chainseed/visualization/EthExplorer.py`；保留通用 ContainerBundle 与 InternetMap。 |
| ☐ | `seedemu/testing/blockchain.py` | 1 | 对应 ChainSeed `chainseed/testing/blockchain.py`；同批处理 testing 的导出、registry 和 CLI。 |

### 3. 示例：188 个

| 勾选 | 删除路径 | 文件数 | 说明／联动 |
|---|---|---:|---|
| ☐ | `examples/blockchain/` | 104 | 104 个文件；现役示例由 ChainSeed 的 ethereum/、chainlink/、monero/、solana/ 目录承担；同步删除 CI 的 D 系列引用。 |
| ☐ | `examples/.not_ready_examples/18-eth-private-network/` | 12 | 旧 Ethereum 示例；不在 SeedEmu 保留。 |
| ☐ | `examples/.not_ready_examples/26-proof-of-authority/` | 14 | 旧 PoA 示例；不在 SeedEmu 保留。 |
| ☐ | `examples/.not_ready_examples/B08-Remix-Connection/` | 7 | 旧 Remix 示例；结合 ChainSeed 现有文档核对，不重新恢复已清理的历史方案。 |
| ☐ | `examples/.not_ready_examples/B09-Smart-Contract-Attacks/` | 8 | 旧智能合约攻击示例；不在 SeedEmu 保留。 |
| ☐ | `examples/.not_ready_examples/C04_ethereum_pos/` | 1 | 旧 PoS 示例；由 ChainSeed 的现役 PoS 示例承担。 |
| ☐ | `examples/internet/B27_ipfs_kubo_dapp/` | 41 | 41 个文件，对应 ChainSeed `examples/ethereum/E08_ipfs_kubo_dapp/`；只删这个 dApp，不删 Kubo 服务。 |
| ☐ | `examples/basic/A08_buildtime_docker/create_eth_account.py` | 1 | 替换为后面的 create_network_config.py；同批修改 A08 Dockerfile 和 README。 |

### 4. 实验及辅助库：48 个

| 勾选 | 删除路径 | 文件数 | 说明／联动 |
|---|---|---:|---|
| ☐ | `experiments/blockchain/` | 31 | 31 个文件；对应 ChainSeed `experiments/legacy/blockchain/`，不恢复此前已清理的 `test_deployment.py`。 |
| ☐ | `experiments/ethereum-layer2/` | 13 | 13 个文件对应 ChainSeed `experiments/legacy/ethereum-layer2/`；必须核对其中 `docker_images/seedemu-sc-deployer/l2.tar.gz`，该 77 MB 资源已补迁。 |
| ☐ | `library/blockchain/` | 4 | 4 个文件对应 ChainSeed 同名目录；先移除仍使用它们的旧示例／实验。 |

### 5. 旧区块链测试：58 个

| 勾选 | 删除路径 | 文件数 | 说明／联动 |
|---|---|---:|---|
| ☐ | `tests/ethereum/` | 20 | PoA、PoW、PoS 旧测试；先同步清理 tests/__init__.py 与 run-tests.py 的导入和分组。 |
| ☐ | `tests/chainlink/` | 13 | 旧 Chainlink 测试；同步清理测试导入。 |
| ☐ | `tests/ethUtility/` | 10 | 旧 Utility 测试；同步清理测试导入。 |
| ☐ | `tests/ethereumLayer2/` | 4 | 旧 Layer 2 测试。 |
| ☐ | `tests/experiment_test/genesis/` | 10 | 仅删除 genesis 子目录，不删除整个 experiment_test。 |
| ☐ | `tests/multi-platform-test/` | 1 | 原脚本只检查旧区块链示例；不把它误认为通用网络平台检查。 |

### 6. 工具与 Demo 图片：123 个

| 勾选 | 删除路径 | 文件数 | 说明／联动 |
|---|---|---:|---|
| ☐ | `tools/Blockchain/` | 121 | 121 个文件；119 个有 ChainSeed tools/blockchain 对应文件；旧 EtherView2/test/test.py 及其 README 不恢复。 |
| ☐ | `tools/DemoSystem/extensions/assets/img/large_blockchain.png` | 1 | 与 Demo 菜单项清理一起处理。 |
| ☐ | `tools/DemoSystem/frontend/src/assets/img/large_blockchain.png` | 1 | 与前端区块链菜单项清理一起处理。 |

### 7. 专用文档与配图：15 个

| 勾选 | 删除路径 | 文件数 | 说明／联动 |
|---|---|---:|---|
| ☐ | `docs/user_manual/blockchain/` | 10 | 10 个文件；区块链用户说明归 ChainSeed。 |
| ☐ | `docs/developer_manual/blockchain/` | 1 | 区块链开发说明归 ChainSeed。 |
| ☐ | `docs/developer_manual/06-chainlink-service.md` | 1 | 移除 SeedEmu 的 Chainlink 服务文档。 |
| ☐ | `docs/developer_manual/fig/06-chainlink-service/` | 3 | 删除对应 3 张配图；与上一项一起处理。 |


## 保留边界与收尾核对

| 项目 | 要求 |
|---|---|
| SystemProfile、Service/Server、通用 DockerImage 与 ContainerBundle | 保留现有实现；这不是删除所有运行环境抽象。 |
| BgpLookingGlassService、InternetMap、Kubo/IPFS、Tor | 保留网络服务；Tor 的 consensus 不是区块链共识。 |
| SDN 的 FAUCET 控制器 | 不按 faucet 名称误删。 |
| routing、BGP、AS、Docker 默认网络行为 | 不修改；不加入 nat-unprotected 或新的 host sysctl 配置。 |
| 已迁往 ChainSeed 的资源 | 删除前核对，包括 Layer 2 的 l2.tar.gz。 |
| 清理原则 | 每删一个目录，检查 imports、CLI、CI、脚本和文档链接；不要机械替换整个文件，也不要批量删除所有“加密库”。 |

可在 SeedEmu 根目录用下面命令排查残留，再逐项判断命中内容，不直接批量删除：

```bash
rg -n -i 'blockchain|ethereum|chainlink|monero|solana|ethexplorer|eth_account|web3' seedemu docs examples experiments library tools tests .github README.md CONTRIBUTING.md requirements.txt
```

已经不存在的目录从命令中去掉。引用清完后，检查 `import seedemu` 不再因已删除模块失败。
这一步只确认清理后的 SeedEmu 自身边界；不宣称已完成下一轮 ChainSeed profiles/images 对接。
