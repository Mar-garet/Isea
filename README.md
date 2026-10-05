# SGAgent

SGAgent 是面向 SWE-bench 的仓库级软件修复研究原型。系统把问题定位、修改规划和补丁生成分为三个阶段，让调用者可以检查每个阶段的结果。

[技术报告](https://ise-agent.github.io/fix-agent-home/) · [MIT License](LICENSE)

## 修复流程

主修复流程有 **3 个脚本入口**，这里统计的是可以直接执行的阶段脚本。Context 等数据对象、Agent 类和工具函数不另算入口。

1. 调用者执行 `localizer.py`。Localizer 读取问题和目标项目，输出可疑文件、行号及原因。
2. 调用者执行 `suggester.py`。Suggester 读取定位结果，输出修改动作、理由、代码预览、测试方案、风险和证据。
3. 调用者执行 `fixer.py`。Fixer 读取完整建议，使用文件工具修改项目；运行器随后执行调用者配置的回归测试，测试通过才导出补丁。

阶段之间通过 `results/locations/<INSTANCE_ID>.json` 和 `results/suggestions/<INSTANCE_ID>.json` 传递结果。保存时，运行器把定位和修改动作中的文件路径转换为项目相对路径，使它们可以在下一阶段的新工作目录中使用。旧版产物如果包含已清理目录的绝对路径，应重新运行定位和建议阶段。同一进程内，Agent 也会把结构化输出更新到传入的 Context。三个脚本应在仓库根目录依次执行。

每个阶段由运行器从 Docker 镜像复制独立的临时工作目录，再让工具访问该目录。执行结束后，运行器清理临时目录和容器。无需手动设置 TEST_BED 或 PROJECT_NAME；程序化调用工具时才需要指定它们。

## 安装与配置

需要 Python 3.12+、uv，以及可以正常运行的 Docker。目标项目的测试依赖应已安装在对应的 SWE-bench 评测镜像中；本仓库不构建这些镜像。

```sh
uv sync --frozen
cp .env.example .env
docker image ls
```

填写 `.env`：

- `API_KEY`、`MODEL`：模型服务的凭据和模型名称。
- `BASE_URL`：兼容 OpenAI 的服务地址；留空使用客户端默认地址。
- `DATASET`：本地数据集名称，可选 `lite` 或 `verified`。
- `INSTANCE_ID`：数据集中真实存在的实例 ID。
- `DOCKER_IMAGE`：已准备好的本地评测镜像完整名称。留空时，运行器按实例 ID 查找唯一的本地镜像；有多个候选时应显式指定。
- `TEST_COMMAND`：在目标容器的 `/testbed` 目录执行的回归命令，例如 `python -m pytest -q tests/test_example.py`。请替换为该实例实际相关的测试，包含复现问题的用例和必要的回归用例。
- `TEST_TIMEOUT`：每次测试执行的秒数上限，默认 300。

可以用下面的命令查看数据集中的实例 ID：

```sh
uv run python -c 'import pandas as pd; print(pd.read_parquet("dataset/lite.parquet")["instance_id"].head().to_string(index=False))'
```

设置镜像名称后，用 `docker image inspect <镜像名称>` 确认它已存在。镜像必须包含 `/testbed` 及其 Git 元数据，并能在 Bash 登录环境中执行所选测试命令。镜像架构需要由本地 Docker 支持。

## 执行与结果

这一章沿用上面的 **3 个阶段入口**；以下命令按定位、规划、修复的顺序调用它们。

```sh
uv run python localizer.py
uv run python suggester.py
uv run python fixer.py
```

Fixer 可以通过 `run_tests` 工具检查测试结果。即使模型报告完成，运行器仍会独立再执行一次 TEST_COMMAND。

通过验证的补丁保存到 `results/patch_diff/<DATASET>_<INSTANCE_ID>.patch`。退出码、标准输出、标准错误和通过状态保存到 `results/validation/<DATASET>_<INSTANCE_ID>.json`。测试失败或超时会让修复阶段失败，并阻止补丁导出；重新执行时，运行器会移除同名的旧补丁和验证报告，避免误用旧结果。补丁导出的 Git 命令也在 Docker 中执行，不创建 Git 提交。

取消运行时，运行器先等待正在执行的验证或导出操作退出，再清理容器和工作目录。验证受 TEST_TIMEOUT 限制，导出上限为 30 秒；取消后的清理可能需要等待这些操作结束。

TEST_COMMAND 由调用者配置，不直接执行模型建议中的任意命令。测试通过只代表这个命令退出成功，并不等价于 SWE-bench 官方判定通过。

## 工具执行与代码索引

模型可以读取和修改临时项目中的文件。工具先解析完整路径，再拒绝指向项目外部的绝对路径、父目录路径和符号链接，也拒绝直接访问 Git 元数据。创建文件后的 Python 执行、回归测试和 Git 补丁导出均在 Docker 内完成，容器关闭网络、移除额外能力，并在超时后被清理。

模型生成 Python 并在宿主机直接执行的 create_tool 能力已移除。开发者仍可通过 BaseAgent.add_tool 注册自己维护的可信函数。

代码索引只解析 Python 源码，不导入目标项目。索引支持普通函数和异步函数；工具修改文件后使索引失效，外部文件变化和项目根目录变化也会触发重建。目录扫描排除 Git 元数据、虚拟环境及项目外部的符号链接。调用关系仍是静态近似：同名目标存在歧义时不推断调用边，不能替代完整的 Python 语义分析。

## 开发验证

```sh
uv run pytest
uv run ruff check .
```

测试使用离线模型和临时 Git 仓库，覆盖工具路径边界、完整建议传递、上下文更新、索引刷新、容器清理及补丁验证门槛，无需模型 API 或 Docker。Docker 执行边界通过替身验证；真实镜像兼容性和修复率仍需单独执行端到端实验。

当前开源范围限于 SWE-bench。仓库中的测试不构成修复率、成本或规划阶段收益的实验结论。
