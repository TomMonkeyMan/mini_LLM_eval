# Mini LLM Eval & Experiment Runner

一个面向 LLM 回归测试的最小可用评测运行系统。

它解决的是这样一个工程问题：当团队调整模型、Prompt、RAG、Agent 或工具链路后，如何用一套固定评测集快速做回归，判断新版本是否更好、是否引入异常、是否具备上线条件。

当前版本聚焦 **单机可运行、CLI 可复现、结果可解释**，支持：

- 加载本地评测集
- 调用统一 Provider 接口生成结果
- 按 case 配置多个 Evaluator 打分
- 聚合指标并持久化结果
- 对比两次实验结果
- 导出 Markdown / HTML 报告

## 1. 给评审的最快上手方式

### 1.1 安装

```bash
python -m pip install -e ".[dev]"
```

安装后可用：

```bash
mini-llm-eval --help
```

### 1.2 零 API Key 演示：直接对比两次样例 run

仓库内已经提供了两份固定产物，适合评审直接验证 compare/report 主链路：

```bash
mini-llm-eval compare demo/sample_runs/run-baseline demo/sample_runs/run-candidate
```

再导出对比报告：

```bash
mini-llm-eval report-compare \
  demo/sample_runs/run-baseline \
  demo/sample_runs/run-candidate \
  --format markdown
```

### 1.3 本地跑一次真实评测任务：使用 mock provider

这是最简单的“从数据集到运行结果”的本地闭环，不依赖外部模型服务：

```bash
cd demo/quickstart

mini-llm-eval run \
  --dataset data/sample.jsonl \
  --provider mock-demo \
  --run-id demo-quickstart \
  --config config.yaml \
  --providers providers.yaml
```

这里的 `mock-demo` 使用当前实现已支持的 `fallback` 配置，在 quickstart 示例里会直接返回 case 的 `expected_answer`，用于离线验证执行链路。

查看运行结果：

```bash
mini-llm-eval status demo-quickstart --config config.yaml
mini-llm-eval show demo-quickstart --cases --config config.yaml
```

### 1.4 运行测试

```bash
python -m pytest
```

---

## 2. 题目要求完成情况

### 2.1 本地评测数据集

仓库内提供主评测集：

- `data/eval_cases.jsonl`

当前共 **20 条样例**，覆盖多类场景：

- 领域知识问答
- 结构化抽取
- SQL / 查询解释
- 工具调用决策
- 中英混合输入
- 格式约束 / 数值判断

每条 case 的核心字段包括：

- `case_id`
- `query`
- `expected_answer`
- `tags`
- `difficulty`
- `eval_type` / `eval_types`
- `metadata`

示例：

```json
{
  "case_id": "diag_001",
  "query": "车辆出现高压互锁告警时，优先检查哪些信号？",
  "expected_answer": "HVIL|连接器|DTC",
  "tags": ["diagnostics", "knowledge"],
  "difficulty": "medium",
  "eval_type": "contains",
  "metadata": {"locale": "zh-CN"}
}
```

### 2.2 Provider 抽象

统一 Provider 接口位于：

- `src/mini_llm_eval/providers/base.py`
- `src/mini_llm_eval/providers/factory.py`

已实现 Provider：

- `mock`
- `openai_compatible`
- `plugin`

设计目标：

- 上层 runner 不感知 provider 实现细节
- provider 配置由 YAML 驱动，不写死在业务逻辑中
- 所有 provider 返回统一结构：
  - `output`
  - `latency_ms`
  - `status`
  - `error`
  - 可选 `token_usage`
  - 可选 `cost`

相关实现：

- `src/mini_llm_eval/providers/mock.py`
- `src/mini_llm_eval/providers/openai_compatible.py`
- `src/mini_llm_eval/providers/plugin.py`
- `src/mini_llm_eval/providers/rate_limited.py`

### 2.3 Evaluator 抽象

统一 Evaluator 接口位于：

- `src/mini_llm_eval/evaluators/base.py`
- `src/mini_llm_eval/evaluators/registry.py`

当前实现的 evaluator 包括：

- `exact_match`
- `contains`
- `contains_all`
- `regex`
- `json_field`
- `numeric_tolerance`
- `length_range`
- `not_contains`

满足的要求：

- evaluator 接口统一
- evaluator 返回结构化结果
- evaluator 异常不会导致整个程序 crash
- 每个 case 可按 `eval_type` / `eval_types` 选择 evaluator
- 支持注册表自动发现，新增 evaluator 不需要修改 runner 主流程

### 2.4 实验运行器

核心运行流程位于：

- `src/mini_llm_eval/services/run_service.py`
- `src/mini_llm_eval/services/executor.py`
- `src/mini_llm_eval/db/database.py`
- `src/mini_llm_eval/db/file_storage.py`

一次 run 至少包含：

- `run_id`
- `dataset_path`
- `provider_name`
- `model_config`
- `concurrency`
- `timeout_ms`
- `max_retries`

运行结果包含：

- case 级结果
- 总通过率
- 按 tag 聚合的通过率
- 平均 latency
- p95 latency
- 错误数量与错误分布

CLI 入口位于：

- `src/mini_llm_eval/cli/main.py`

### 2.5 实验对比

对比逻辑位于：

- `src/mini_llm_eval/services/comparator.py`

支持输出：

- 总通过率变化
- 按 tag 的通过率变化
- 新增失败 case
- 修复成功 case
- latency 变化
- base-only / candidate-only case

### 2.6 鲁棒性

当前已显式处理多类异常：

- 非法输入数据
- provider 调用失败
- provider 超时
- evaluator 异常
- 单个 case 失败
- 并发执行中的部分失败
- artifact 结果文件写入失败（带 fallback）

目标是：**单条 case 出错不会让整个 run 失效**。

---

## 3. 选择深入实现的开放方向

除了基本要求外，这个版本实际覆盖了多个“深入方向”：

### A. 任务状态机

实现了 run 状态流转：

- `PENDING`
- `RUNNING`
- `SUCCEEDED`
- `FAILED`
- `CANCELLED`

相关实现：

- `src/mini_llm_eval/services/state_machine.py`
- `src/mini_llm_eval/db/database.py`

并通过 `state_logs` 持久化状态变更记录。

当前这个状态机更偏向 **run 生命周期记录与可恢复执行**，而不是完整的分布式工作流编排。

在当前单机 MVP 中，没有把“运行中 cancel”作为完整能力做完，原因是：

- run 内部仍是本地进程直接驱动 provider / evaluator
- 没有独立任务队列把执行过程彻底解耦
- 主目标是先保证 `ctrl + C -> resume` 这条恢复链路成立

如果后续演进到真正的异步任务系统，更合理的方向会是：

- 用队列把 run / provider / evaluator 解耦
- 再补真正的运行中 cancel
- 或者直接接入 Temporal / Prefect 这类工作流框架，而不是手写完整编排系统

### B. 插件式 Evaluator

Evaluator 采用注册表 + 自动发现机制：

- `src/mini_llm_eval/evaluators/registry.py`

新增 evaluator 时无需修改 runner 主流程代码。

### C. 断点恢复

支持 resume：

- 根据已完成 case 跳过重复执行
- 从未完成部分继续跑

相关实现：

- `src/mini_llm_eval/services/run_service.py`

### E. 并发与限流

支持两层控制：

- run 级 case 并发
- provider 级并发上限 / requests per second

相关实现：

- `src/mini_llm_eval/services/executor.py`
- `src/mini_llm_eval/providers/rate_limited.py`

---

## 4. 项目结构

```text
mini_LLM_eval/
├── README.md
├── pyproject.toml
├── config.yaml
├── providers.yaml
├── data/
│   └── eval_cases.jsonl
├── demo/
│   ├── README.md
│   ├── quickstart/
│   ├── sample_runs/
│   └── reports/
├── docs/
├── outputs/
├── src/mini_llm_eval/
│   ├── cli/
│   ├── core/
│   ├── db/
│   ├── evaluators/
│   ├── models/
│   ├── providers/
│   └── services/
└── tests/
```

分层思路：

- `models/`: 统一 schema
- `core/`: 配置、异常、日志、类型
- `providers/`: 模型调用抽象
- `evaluators/`: 评测规则抽象
- `services/`: 运行、对比、报告等领域逻辑
- `db/`: SQLite 与 artifact 持久化
- `cli/`: 命令行入口

### 4.1 分层架构与 CLI 角色

这个项目的设计并不只是“按目录拆模块”，而是有比较明确的层次划分。对外可以概括为 4 个主要业务层：Provider 层、Evaluator 层、分析层、报表层；CLI 则是这些层在单机 MVP 下的统一组合入口。

#### Provider 层

职责是统一模型调用接口，但不强行限制模型接入方式。

- 对上暴露统一的 `generate()` 契约
- 对下兼容不同模型接入方式
- 支持 `mock`、`openai_compatible`、`plugin` 三类 provider
- 平台侧统一托管并发控制、限流、重试等运行时能力

对应目录：

- `src/mini_llm_eval/providers/`

#### Evaluator 层

职责是把“模型输出”转成“结构化评测结果”。

- 每个 evaluator 只关注单条 case 的判定逻辑
- 统一返回结构化 `EvalResult`
- 通过注册表机制支持插件式扩展

对应目录：

- `src/mini_llm_eval/evaluators/`

#### 分析层

职责是围绕运行结果做聚合、解释和实验对比。

- 运行阶段聚合 pass rate、tag pass rate、latency、error distribution
- 离线阶段基于 artifact 做 run-to-run compare
- 尽量和具体 provider 实现解耦，更关注实验结果本身

对应实现主要包括：

- `src/mini_llm_eval/services/run_service.py`
- `src/mini_llm_eval/services/comparator.py`
- `src/mini_llm_eval/db/file_storage.py`

#### 报表层

职责是把分析结果渲染成适合人阅读和交付的输出。

- 将单次 run 或两次 compare 的结果渲染成 Markdown / HTML
- 不参与执行，只消费已有 artifact 或 compare result
- 目标是让评审、研发或算法同学可以直接阅读结果

对应实现：

- `src/mini_llm_eval/services/reporter.py`

#### CLI 层

CLI 本身不是业务逻辑中心，而是这些层的组合入口。

也正因为底层有明确的 layer 边界，CLI 才自然拆成了几类命令：

- 执行 / 状态类：`run` / `resume` / `status` / `list` / `show` / `cancel`
- 分析类：`compare`
- 报表类：`report-run` / `report-compare`

换句话说，当前 CLI 不是把所有逻辑都塞进命令行脚本里，而是把不同层能力用命令形式暴露出来，方便单机 MVP 直接使用，也为后续替换成 HTTP API、任务队列或工作流系统保留清晰边界。

---

## 5. 核心设计说明

### 5.1 为什么是分层架构

这个项目的核心目标之一，是把“模型调用”“评测判定”“实验分析”“结果呈现”拆成清晰层次，而不是把它们揉在一个 runner 里。

这样设计的好处是：

- Provider 层可以专注处理异构模型接入
- Evaluator 层可以专注处理判定逻辑
- 分析层可以专注做聚合和对比
- 报表层可以专注做人类可读输出
- CLI 只负责组合这些能力，而不是承载全部业务逻辑

这也是为什么当前版本虽然是 CLI 形态，但整体更像一个可继续演进的评测框架，而不只是一个单文件脚本。

### 5.2 为什么要做 plugin provider

这个项目的 Provider 不是只服务固定内部调用方，而是面向更外部、更异构的模型使用场景，尤其可能被做模型训练、微调、评测集构建的人使用。

这些用户的模型接入方式通常很多样：

- 本地部署模型服务
- 走统一网关
- 使用团队自定义 endpoint
- 使用非标准 payload / response schema

如果平台强行把接入方式收敛到单一 OpenAI-compatible 协议，虽然主链路更简单，但会明显限制使用自由度。

因此这里额外提供了 `plugin` provider：

- 用户可以通过一个轻量脚本自定义请求逻辑
- 自己决定 endpoint、payload 和响应解析方式
- 平台侧仍然统一托管运行期能力，例如并发控制、限流、状态管理和结果落盘

这个设计的目标不是做“最标准”的 provider，而是做一个 **对接入方约束更少、对平台侧控制点仍然清晰** 的 provider 扩展层。

### 5.3 为什么用注册表管理 evaluator

原因是 evaluator 是最容易扩展的点。

采用注册表后：

- case 只需要声明 evaluator 名称
- runner 不需要知道 evaluator 的具体实现
- 增加新 evaluator 时不需要侵入主流程

这让 evaluator 层天然适合按插件方式演进，也更符合评测系统里“规则持续增加”的真实场景。

### 5.4 为什么分析和报表基于 artifact

分析层和报表层都尽量不直接绑定运行时数据库，而是优先消费 artifact。

这样做的原因是：

- artifact 是稳定输入，便于归档和分享
- compare/report 不依赖数据库环境
- 更接近真实实验平台中“导出结果后再分析”的工作方式
- 可以让分析层和报表层更独立，不和执行链路强耦合

因此在这个项目里：

- compare 更像分析层能力
- report 更像报表层能力
- 两者都可以脱离执行现场单独使用

### 5.5 为什么同时使用 SQLite 和文件产物

这是当前版本最重要的运行时取舍之一。

- SQLite 用于：
  - run 状态管理
  - case 结果索引
  - resume / list / status / show
- 文件产物用于：
  - 结果归档
  - compare
  - report
  - 脱离数据库后的离线分析

这样做的好处：

- 运行时有结构化状态管理
- 离线分析不依赖数据库环境
- 对评审更友好：直接看 `meta.json` 和 `case_results.jsonl` 即可

### 5.6 并发模型

当前执行模型是：

- case 并发执行 provider 调用
- evaluator 在单个 case 内同步执行
- 结果通过 writer queue 串行写入

这个方案相对简单，但已经能覆盖：

- 基础并发
- provider 限流
- 减少并发写文件/写库冲突

同时，provider 的扩展自由度和平台侧运行控制被有意分开：

- provider 可以自由决定“怎么请求模型”
- 平台统一负责“怎么控制请求节奏”

也就是说，插件可以高度自定义接入逻辑，但并发和限流仍然由平台统一托管。
---

## 6. 数据、Provider、Evaluator 配置

### 6.1 项目配置 `config.yaml`

```yaml
timeout_ms: 30000
max_retries: 3
concurrency: 4
log_level: "INFO"
output_dir: "./outputs"
evaluators_package: "mini_llm_eval.evaluators"
defaults:
  evaluators:
    - contains
```

### 6.2 Provider 配置 `providers.yaml`

根目录 `providers.yaml` 主要展示配置格式；如果你想直接本地跑通，推荐使用：

- `demo/quickstart/providers.yaml`

当前支持的 provider 类型：

- `mock`
- `openai_compatible`
- `plugin`

### 6.3 case 级 evaluator 指定方式

单个 evaluator：

```json
{
  "case_id": "tool_001",
  "query": "Should the system call sql_query or doc_search for a DB question?",
  "expected_answer": "sql_query",
  "eval_type": "exact_match"
}
```

多个 evaluator：

```json
{
  "case_id": "case_multi",
  "query": "Return a JSON tool selection",
  "expected_answer": "sql_query",
  "eval_types": ["json_field", "contains"]
}
```

---

## 7. CLI 使用方式

### 7.1 运行一次评测

```bash
mini-llm-eval run \
  --dataset data/eval_cases.jsonl \
  --provider mock-default \
  --run-id run-001 \
  --config config.yaml \
  --providers providers.yaml
```

### 7.2 恢复一次评测

```bash
mini-llm-eval resume run-001 --config config.yaml --providers providers.yaml
```

### 7.3 查看状态

```bash
mini-llm-eval status run-001 --config config.yaml
```

### 7.4 查看最近 runs

```bash
mini-llm-eval list --limit 10 --config config.yaml
```

### 7.5 查看单次 run 明细

```bash
mini-llm-eval show run-001 --config config.yaml
mini-llm-eval show run-001 --cases --failed-only --config config.yaml
```

### 7.6 取消 run

```bash
mini-llm-eval cancel run-001 --config config.yaml --providers providers.yaml
```

说明：

- 当前版本保留了 `CANCELLED` 状态与 `cancel` 命令接口
- 但作为单机 MVP，**不把运行中 cancel 作为主打能力**
- 更推荐的中断方式是直接 `Ctrl + C`，随后通过 `resume` 继续未完成 case
- 当前版本只可靠支持取消 `PENDING` run

### 7.7 对比两次 run

```bash
mini-llm-eval compare run-base run-candidate
mini-llm-eval compare ./outputs/run-base ./outputs/run-candidate
```

### 7.8 导出报告

单次 run 报告：

```bash
mini-llm-eval report-run run-001 --output-dir ./outputs --format markdown
mini-llm-eval report-run run-001 --output-dir ./outputs --format html --output ./reports/run-001.html
```

两次 run 对比报告：

```bash
mini-llm-eval report-compare run-base run-candidate --output-dir ./outputs --format markdown
mini-llm-eval report-compare run-base run-candidate --output-dir ./outputs --format html --output ./reports/compare.html
```

---

## 8. 输出结果

默认输出目录：

```text
outputs/
└── <run_id>/
    ├── case_results.jsonl
    └── meta.json
```

同时会写入 SQLite：

- `runs`
- `case_results`
- `state_logs`

默认数据库路径：

```text
<output_dir>/eval.db
```

### 8.1 `case_results.jsonl`

每行包含单个 case 结果，核心字段包括：

- `run_id`
- `case_id`
- `query`
- `expected`
- `actual_output`
- `case_status`
- `eval_results`
- `latency_ms`
- `provider_status`
- `error_message`
- `retries`
- `created_at`

### 8.2 `meta.json`

包含 run 元信息与 summary，核心字段包括：

- `run_id`
- `dataset_path`
- `provider_name`
- `model_config`
- `status`
- `summary`
- `created_at`
- `started_at`
- `finished_at`
- `state_logs`
- `case_result_count`

---

## 9. 测试与验证

当前仓库已包含多组自动化测试，覆盖：

- config
- dataset
- schemas
- evaluators
- providers
- storage
- services
- comparator
- reporter
- CLI
- state machine

测试目录：

- `tests/test_cli.py`
- `tests/test_comparator.py`
- `tests/test_config.py`
- `tests/test_dataset.py`
- `tests/test_evaluators.py`
- `tests/test_providers.py`
- `tests/test_reporter.py`
- `tests/test_services.py`
- `tests/test_state_machine.py`
- `tests/test_storage.py`

此外还提供了至少两份样例 run output：

- `demo/sample_runs/run-baseline/`
- `demo/sample_runs/run-candidate/`

以及对应报告示例：

- `demo/reports/run-baseline.md`
- `demo/reports/compare-baseline-vs-candidate.md`

---

## 10. AI 工具使用说明

本项目开发过程中使用了 AI 辅助工具：

- Codex
- Claude / Claude Code

协作方式大致如下：

- 我负责整体框架设计、核心接口划分和关键 tradeoff 决策
- 我负责和 Claude 讨论实现细节，收敛最终设计方案
- 我编写 `RULES.md` 和 `DEVELOPMENT.md`，作为后续代码生成与实现约束
- Codex 主要负责按约束拆分实现各个子模块，并补充单元测试
- 我与 Claude 会对各模块代码进行 review，并持续提出修改建议和改进方向

AI 主要帮助的部分：

- 初始代码脚手架与局部实现补全
- 子模块代码生成与测试补全
- 文档整理与多轮 review
- 针对模块边界、异常处理和命名的一些重构建议

关键设计决定由我主导完成，包括：

- plugin provider 的扩展策略：给接入方充分自由度，同时由平台统一控制并发与限流
- evaluator 注册表机制
- 运行时状态与离线分析分离：SQLite + artifact 双存储
- compare/report 基于 artifact，而不是直接绑定数据库
- run 级并发与 provider 级限流分层
- 状态机、resume、state log 的组合方式
- v1 只做 CLI，不做 HTTP API / Web UI 的范围收敛

我验证 AI 生成代码正确性的方式：

- 使用单元测试和 CLI 测试覆盖关键主链路
- 用 mock provider 跑本地闭环，保证无 API key 也可运行
- 通过固定 sample runs 验证 compare/report 输出
- 对关键接口、异常路径和设计一致性做人工 review

---

## 11. 设计文档

主设计文档可优先看：

- [`docs/1_overall_design_ty.md`](docs/1_overall_design_ty.md)
- [`docs/7_v1_implementation_spec.md`](docs/7_v1_implementation_spec.md)
- [`docs/5_critical_design.md`](docs/5_critical_design.md)

如果想看更完整的设计演化过程，也可以继续看 `docs/` 下的其他文档。

---

## 12. Demo 说明

如果你希望直接看示例而不是自己组织命令，可阅读：

- [`demo/README.md`](demo/README.md)
- [`demo/quickstart/README.md`](demo/quickstart/README.md)

其中：

- `demo/quickstart/`：最小可运行示例
- `demo/sample_runs/`：两份固定产物，用于 compare 演示
- `demo/reports/`：预先导出的 Markdown 报告

---

## 13. 当前限制与后续可扩展点

当前版本有意识地保持了最小可用范围，仍存在这些边界：

- 只提供 CLI，不提供 HTTP API
- 不包含 Web UI
- 不包含 LLM-as-a-Judge evaluator
- `RUNNING` run 暂不支持完整的主动取消，当前推荐 `Ctrl + C` 后再 `resume`
- SQLite 为单机实现，不是分布式任务系统
- 如果后续要做更完整的工作流编排 / 取消 / 重试策略，更适合接入 Temporal、Prefect 一类框架
- HTML 报告是静态模板，不包含交互式图表

如果继续扩展，下一步我会优先考虑：

1. HTTP API + 异步任务提交
2. 更完整的取消/中断机制
3. 更强的 evaluator 插件系统
4. 更丰富的报告可视化
5. 更标准的 benchmark / trace 输出
