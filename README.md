# Isea

Isea 是一个面向 Python 项目的多 Agent 软件工程实验框架。它根据 GitHub Issue 理解问题，通过代码定位、修改规划和补丁生成三个阶段，探索如何让语言模型完成仓库级的软件修复任务。

当前项目以 SWE-bench Lite 和 Verified 为任务来源，支持兼容 OpenAI API 的模型服务。每个阶段都保存结构化结果，方便查看 Agent 的判断过程、调整修改方案和开展实验。

## 项目能力

- **代码定位**：结合问题描述和 Python 代码索引，找出相关文件、函数与行号，并给出定位理由。
- **修改规划**：根据定位结果提出修改动作、代码预览、测试方案和潜在风险。
- **补丁生成与验证**：Agent 使用文件工具实施修改，运行器执行配置的回归测试，通过后导出 Git 补丁。
- **Docker 工作环境**：每个阶段使用独立的临时项目目录，复现脚本和回归测试在目标容器中执行。

## 工作流程

主流程提供 **3 个可直接运行的脚本入口**，分别负责定位、规划和修改验证。调用者在仓库根目录按顺序执行它们：

1. `localizer.py`：Localizer 读取 Issue 和目标项目，输出相关代码位置与理由。
2. `suggester.py`：Suggester 读取定位结果，形成可检查的修改建议。
3. `fixer.py`：Fixer 读取定位与建议，修改目标项目；运行器随后执行回归测试并导出补丁。

阶段之间通过 JSON 文件传递结果。代码位置使用项目相对路径，供后续阶段在各自的临时工作目录中读取。运行器负责从本地 Docker 镜像准备目标项目，并在阶段结束后清理工作目录和容器。

## 快速开始

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 Docker。运行前需要准备对应任务的本地 SWE-bench 镜像，镜像中应包含目标项目及其测试依赖。

```sh
git clone https://github.com/Mar-garet/Isea.git
cd Isea
uv sync --frozen
cp .env.example .env
```

在 `.env` 中填写模型服务、任务实例和测试配置：

| 配置项 | 用途 |
| --- | --- |
| `API_KEY` | 模型服务的 API 密钥 |
| `MODEL` | 模型名称 |
| `BASE_URL` | 兼容 OpenAI API 的服务地址；留空使用客户端默认地址 |
| `DATASET` | 任务数据集，可选 `lite` 或 `verified`，默认 `lite` |
| `INSTANCE_ID` | 所选数据集中的任务实例 ID |
| `DOCKER_IMAGE` | 对应任务的本地镜像完整名称；留空时按实例 ID 查找唯一匹配镜像 |
| `TEST_COMMAND` | 在容器 `/testbed` 中执行的回归测试命令，运行 `fixer.py` 时必填 |
| `TEST_TIMEOUT` | 每次测试执行的秒数上限，默认 `300` |
| `LOG_DIR` | 日志目录，默认 `results/logs` |

可以先查看数据集中的实例 ID 和本地镜像：

```sh
uv run python -c 'import pandas as pd; print(pd.read_parquet("dataset/lite.parquet")["instance_id"].head().to_string(index=False))'
docker image ls
```

镜像需要包含 `/testbed` 及其 Git 元数据，支持 Bash 登录环境，并能运行配置的测试命令。`TEST_COMMAND` 应覆盖所选问题的复现用例和相关回归用例，例如 `python -m pytest -q tests/test_example.py`，其中测试路径需替换为目标项目的实际路径。

配置完成后，依次运行：

```sh
uv run python localizer.py
uv run python suggester.py
uv run python fixer.py
```

Fixer 可以在修改过程中调用测试工具查看结果。生成结束后，运行器会再次执行 `TEST_COMMAND`；测试失败或超时会终止补丁导出。

## 输出结果

运行结果保存在 `results/` 下：

```text
results/
├── locations/<INSTANCE_ID>.json                 # 代码位置与定位理由
├── suggestions/<INSTANCE_ID>.json               # 修改建议、测试方案与风险
├── patch_diff/<DATASET>_<INSTANCE_ID>.patch      # 通过回归验证的补丁
├── validation/<DATASET>_<INSTANCE_ID>.json       # 测试退出码与输出
└── logs/                                       # 模型与工具调用日志（默认位置）
```

验证报告记录配置的回归命令是否通过。SWE-bench 的任务评分需要使用其官方评测流程单独运行。

## 项目结构

三个阶段脚本负责组织执行流程，`agents/` 实现各阶段的模型交互，`prompts/` 定义其任务要求。Agent 调用 `tools/` 读取和修改项目；`kg/` 解析 Python 源码建立代码索引，`retriever/` 提供检索能力。`utils/` 管理 Docker 工作目录、文件路径、日志和验证结果，`dataset/` 保存任务数据，`tests/` 验证框架行为。

代码索引支持普通函数、异步函数、类、调用关系和继承关系。文件变化后，检索工具会更新索引。调用关系来自静态源码分析，对动态调用和同名符号的判断有一定限制。

## 开发

```sh
uv run pytest
uv run ruff check .
```

测试使用离线模型和临时项目，覆盖阶段结果传递、文件工具、代码索引、回归验证和资源清理，无需模型 API 或 Docker。真实模型与任务镜像的端到端实验需要另外配置运行环境。

## 许可证

项目采用 [MIT License](LICENSE)。版权声明见许可证文件。
