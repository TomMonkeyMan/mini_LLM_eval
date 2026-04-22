# Mini LLM Eval v1 Implementation Spec

> 本文档是 v1 实现阶段的权威规格说明。
>
> 如与历史讨论文档冲突，以本文为准。
>
> 参考来源：
> - `docs/raw_requirement.txt`
> - `docs/5_critical_design.md`
> - `docs/6_version1_dev_plan.md`

---

## 1. 文档定位

本项目已有多轮设计讨论。为了进入实现阶段，需要有一份单一、准确、无冲突的 v1 规格文档，明确：

- v1 做什么，不做什么
- 哪些设计已经冻结
- 哪些点只是后续扩展，不进入当前实现
- 核心模块如何解耦
- 状态机、存储和产物格式如何统一

本文只约束 v1 实现，不覆盖未来版本的全部功能。

---

## 2. v1 目标

v1 的目标不是做完整评测平台，而是做一个可运行、可维护、可扩展到后续版本的核心执行系统。

v1 需要满足以下目标：

- 可以提交并执行一次评测任务
- 可以加载本地评测集并逐条执行
- 可以通过统一抽象调用不同 Provider
- 可以通过统一抽象执行多个 Evaluator
- 可以并发执行 case，并处理单 case 失败
- 可以记录运行状态、状态变更和 case 结果
- 可以中断后恢复未完成 case
- 可以为后续 API、对比分析、更多 Provider 留出稳定接口

---

## 3. v1 范围

### 3.1 v1 包含

- CLI 入口
- 数据集加载
- Provider 抽象
- `mock` Provider
- 第二类 Provider 的接入机制
- Evaluator 抽象
- 规则类 Evaluator
- 异步并发执行
- 任务状态机
- SQLite 持久化
- 文件产物输出
- 断点恢复
- 基础自动化测试

### 3.2 v1 不包含

- 实验对比功能
- FastAPI / HTTP API
- Web UI
- LLM Judge
- 分布式队列
- 缓存系统
- 可视化报表

### 3.3 关于实验对比

`raw_requirement` 中包含“对比两次实验结果”，但本项目当前决策是将其视为后续数据分析能力，不进入 v1 核心实现。

原因：

- 对比逻辑不改变当前核心执行架构
- 先把运行器、状态机、结果产物、持久化做稳更关键
- 只要 v1 冻结好结果产物和元数据结构，后续增加 compare 不需要改 core 主流程

因此，v1 的职责是为 compare 提供稳定输入，而不是在 v1 内完成 compare 功能。

---

## 4. 设计原则

### 4.1 Service Layer 是核心

系统核心应为纯 Python 的 Service Layer。

- CLI 调用 Service Layer
- 后续 API 也调用同一套 Service Layer
- Provider 和 Evaluator 由 Service Layer 编排

这样可以保证：

- v1 先做 CLI，不阻碍后续 API
- 接口层变化不会影响执行核心
- 测试可以绕过 CLI，直接测试核心逻辑

### 4.2 先做解耦，再做功能扩展

v1 虽然不做完整平台，但不应把未来扩展路径堵死。

因此以下边界必须在 v1 明确：

- Provider 和 Runner 解耦
- Evaluator 和 Runner 解耦
- 执行调度和接口层解耦
- 状态机与执行逻辑解耦
- 持久化与产物输出解耦

### 4.3 v1 可以保留“最终版本的骨架”

本项目决定在 v1 就保留任务队列和状态机骨架，而不是只写一个“直接 for-loop 跑完”的脚本。

原因：

- `PENDING/RUNNING/SUCCEEDED/FAILED/CANCELLED` 是 raw requirement 的开放方向
- 后续版本需要 API 化和更强调度能力
- 没有 queue 和状态流转，模块边界会过于耦合
- 断点恢复、状态查询、取消等能力都会变得临时和脆弱

但 v1 的 queue 只做单进程、单机版本，不引入 Redis / Celery。

---

## 5. 系统范围与模块边界

### 5.1 模块划分

v1 采用以下模块划分：

- `core`
  - 配置
  - 异常
  - 通用常量和枚举
- `models`
  - Pydantic 数据模型
- `providers`
  - Provider 抽象
  - 内置 Provider 实现
  - Provider factory
- `evaluators`
  - Evaluator 抽象
  - 注册机制
  - 内置 Evaluator
- `services`
  - 数据集加载
  - 执行引擎
  - RunService
  - 状态机
- `db`
  - SQLite 访问
  - 文件存储
- `cli`
  - 命令行入口

### 5.2 依赖方向

依赖方向必须单向：

`cli/api -> services -> providers/evaluators/db -> core/models`

约束：

- Provider 不依赖 CLI 或 API
- Evaluator 不依赖具体 Provider
- 数据库层不包含业务编排逻辑
- CLI 不直接调用 Provider 或 DB

---

## 6. 运行模型

### 6.1 运行流程

单次 run 的标准流程如下：

1. 接收运行配置
2. 创建 run 记录，状态置为 `PENDING`
3. 进入执行阶段，状态转为 `RUNNING`
4. 加载数据集
5. 初始化 Provider
6. 解析并加载 Evaluator
7. 生产待执行 case
8. 并发执行 Provider 调用
9. 在 case task 内执行规则 Evaluator
10. 将 `CaseResult` 投递到 writer queue
11. writer 串行写入数据库和结果文件
12. 聚合 summary
13. 写入最终元数据和状态日志
14. run 结束，转为 `SUCCEEDED`、`FAILED` 或 `CANCELLED`

### 6.2 单 case 流程

单条 case 的执行流程如下：

1. 调用 Provider
2. 捕获 Provider 超时、失败、重试
3. 获得 `output`
4. 按配置执行一个或多个规则 Evaluator
5. Evaluator 单独捕获异常，不影响其他 Evaluator
6. 生成结构化 `CaseResult`
7. 将结果推送到 writer queue
8. 由 writer 串行持久化到数据库并追加写入 `case_results.jsonl`

---

## 7. 状态机规范

### 7.1 Run 状态是生命周期状态，不是业务质量状态

这里必须统一语义。

`RunStatus` 表示“任务执行生命周期”，不表示“评测效果是否令人满意”。

因此：

- `SUCCEEDED` 表示任务执行流程完成，结果已产出
- 不代表所有 case 通过
- 不代表 pass rate 达标
- 业务质量由 `summary` 字段表达

### 7.2 Run 状态定义

v1 中 Run 状态固定为：

- `PENDING`
- `RUNNING`
- `SUCCEEDED`
- `FAILED`
- `CANCELLED`

状态含义：

- `PENDING`
  - run 已创建，尚未开始执行
- `RUNNING`
  - run 已被 worker/执行器领取，正在执行
- `SUCCEEDED`
  - run 执行完成并成功产出结果
  - 即使部分 case 失败或 evaluator 报错，仍可为 `SUCCEEDED`
- `FAILED`
  - 发生 FATAL 错误，run 无法完成
- `CANCELLED`
  - run 被用户取消，或被明确中止

### 7.3 什么情况算 FAILED

以下属于 `FAILED`：

- 数据集无法加载
- Provider 初始化失败
- 数据库不可用且无法恢复
- 运行过程中发生无法继续的系统级错误

以下不算 `FAILED`：

- 单个 case provider 调用失败
- 单个 case 超时
- 单个 case evaluator 异常
- 部分 case 最终未通过

这些属于 run 成功完成但结果中存在失败项，应体现在 summary 中。

### 7.4 Case 状态定义

Case 级状态固定为：

- `PENDING`
- `COMPLETED`
- `ERROR`

含义：

- `PENDING`
  - 尚未执行
- `COMPLETED`
  - 已完成执行并有结果
  - 可能 pass，也可能 fail
- `ERROR`
  - 该 case 在 provider 或 evaluator 阶段产生错误，无法形成完整正常结果

### 7.5 状态流转

Run 合法流转：

- `PENDING -> RUNNING`
- `RUNNING -> SUCCEEDED`
- `RUNNING -> FAILED`
- `RUNNING -> CANCELLED`

Case 合法流转：

- `PENDING -> COMPLETED`
- `PENDING -> ERROR`

所有状态变更都必须记录到 `state_logs`。

---

## 8. Queue 与执行调度

### 8.1 为什么 v1 保留 queue

本项目在 v1 中保留 queue 语义，但只实现最小版本。

原因：

- 将“提交任务”和“执行任务”分离
- 给状态机一个稳定落点
- 方便后续增加 API、后台 worker、取消和查询
- 避免 Runner 和执行细节强耦合

### 8.2 v1 queue 形态

v1 queue 不是分布式消息队列，而是：

- `runs` 表作为持久化任务池
- 进程内 run 级执行调度
- case 级并发任务执行
- 单独的 writer queue

这意味着：

- v1 不解决多进程竞争
- v1 不解决分布式消费
- v1 的重点是接口、状态语义和单机并发执行模型先稳定

### 8.3 领取逻辑

推荐实现方式：

1. 创建 run 时写入 `runs` 表，状态为 `PENDING`
2. 执行器领取一个 pending run
3. 原子更新为 `RUNNING`
4. 执行完成后更新为终态

这样 `submit`、`start`、`resume`、`status` 的职责都更清晰。

### 8.4 v1 推荐执行模型

v1 推荐采用以下模型：

```text
run submit
  -> runs table / run queue
  -> run executor
    -> case producer
    -> N 个 case task 并发调用 provider
    -> case task 内执行规则 evaluator
    -> result push 到 writer queue
  -> writer 串行写 DB + case_results.jsonl
```

这个模型的关键点是：

- run 级别有 queue 和状态机
- case 级别有真正并发
- Provider 是主要并发瓶颈，使用 Semaphore 控制
- Evaluator 当前以内联执行为主
- 写入通过 writer queue 串行化

### 8.5 为什么 v1 不做多 stage worker

以下架构不进入 v1：

```text
provider queue -> provider worker -> evaluator queue -> evaluator worker -> writer worker
```

原因：

- 当前规则 Evaluator 很轻，单独起 worker 收益不高
- SQLite 不适合过早做多写入并发
- 单进程内引入多阶段调度会显著增加复杂度
- 当前主要瓶颈在 Provider I/O，而不是 Evaluator

因此 v1 先采用“provider 并发 + evaluator 内联 + writer queue”。

但这不否定后续扩展方向，见本文后续 roadmap。

---

## 9. Provider 设计

### 9.1 决策

Provider 采用配置驱动，不采用插件注册作为主扩展方式。

这是一个明确的架构决策。

### 9.2 原因

Provider 和 Evaluator 不是同一个层级的问题。

Evaluator 更像规则逻辑插件，适合：

- 装饰器注册
- 自动发现
- 纯 Python 扩展

Provider 更像模型服务客户端，核心诉求是：

- 配置不同模型实例
- 切换 base URL / model / auth 环境变量
- 让用户方便接入自有模型服务

因此 Provider 更适合：

- 少量内置实现
- 外部配置实例化
- factory 按 `type` 构造

### 9.3 Provider 的真实定位

在真实场景里，Provider 主要面向“远程部署的模型服务”，而不是本地推理引擎。

也就是说，Provider 更接近：

- 远程模型服务的客户端抽象
- 通过 HTTP API 调用用户自有模型、托管模型或兼容 OpenAI 的网关

而不是：

- 本地模型推理框架封装
- GPU 推理服务内部实现

因此 v1 的 Provider 设计目标是“异步 HTTP client 抽象”。

### 9.4 Provider 的异步调用约束

因为 Provider 主要调用远程 HTTP 服务，所以它是典型的 I/O bound 场景。

v1 约束如下：

- Provider 接口保持 `async def`
- 异步 HTTP 客户端默认采用 `httpx.AsyncClient`
- 不在异步调用链中使用 `requests`

原因：

- `requests` 是同步阻塞客户端
- 放在异步路径里会阻塞事件循环
- 会直接破坏 case 级并发收益

允许的实现方向：

- `httpx.AsyncClient`
- 后续如有特殊需要，可替换为 `aiohttp`

但 v1 默认标准实现统一为 `httpx.AsyncClient`，避免引入两套 HTTP 客户端风格。

### 9.5 v1 Provider 范围

v1 至少支持：

- `mock`
- `openai_compatible`

其中：

- `mock` 是 v1 必须完整可跑的 Provider
- `openai_compatible` 是后续真实模型接入的标准入口
- 即使暂时不作为默认验收路径，也应保留其配置和实现边界

### 9.6 用户扩展方式

用户未来最常见的需求不是“写一个新的 Provider 框架”，而是“接入自己训练/部署的模型”。

因此 v1 必须保证用户主要通过改配置完成切换。

例如：

```yaml
# providers.yaml
mock-default:
  type: mock
  mode: mapping
  mapping_file: ./data/mock_responses.json

my-qwen:
  type: openai_compatible
  base_url: ${MY_QWEN_BASE_URL}
  model: qwen-plus
  api_key_env: MY_QWEN_API_KEY

my-vllm:
  type: openai_compatible
  base_url: ${MY_VLLM_BASE_URL}
  model: my-ft-model
  api_key_env: MY_VLLM_API_KEY
```

### 9.7 v1 Provider 接口

Provider 的统一返回结构至少包含：

- `output`
- `latency_ms`
- `status`
- `error`

可选字段：

- `token_usage`
- `cost`
- `model_name`
- `request_id`

### 9.8 Provider 错误边界

Provider 错误必须被结构化处理，不允许直接把异常抛到 run 顶层导致整个进程退出。

可重试：

- timeout
- connection error
- 429
- 5xx

不可重试：

- 4xx 请求错误
- 认证错误
- 明显的响应解析错误

---

## 10. Evaluator 设计

### 10.1 决策

Evaluator 使用插件式机制：

- 装饰器注册
- 自动发现
- Runner 主流程不需要为新增 Evaluator 改代码

### 10.2 v1 Evaluator 范围

v1 的规则类 Evaluator 包括：

- `exact_match`
- `contains`
- `regex`
- `json_field`
- `numeric_tolerance`

### 10.3 多 Evaluator 语义

v1 支持一个 case 配置多个 Evaluator。

约束如下：

- 每个 Evaluator 独立执行
- 每个 Evaluator 独立记录结果
- 不在执行阶段做合并决策
- 聚合含义由 summary/report 层决定

### 10.4 `eval_type` 与 `eval_types`

raw requirement 使用 `eval_type` 单数。

当前设计为了支持多 Evaluator，内部模型采用 `eval_types: list[str]` 更合理。

本规格在实现层面的结论是：

- 核心执行模型以 `eval_types` 为准
- `eval_type` 可以视为原始需求中的概念性字段名称
- 数据集加载层是否兼容单数字段，属于解析策略问题，不影响核心架构

换句话说，这不是 Runner 核心设计分歧，而是数据导入兼容策略，后续可单独细化。

### 10.5 Evaluator 异常边界

Evaluator 异常不能让整个 run crash。

处理要求：

- 捕获异常
- 记录错误信息和 trace
- 在该 evaluator 的结果上标记 error
- 不影响同一 case 的其他 evaluator
- 不影响其他 case

---

## 11. 数据集规范

### 11.1 v1 数据集要求

v1 需要至少一份本地数据集：

- 至少 20 条 case
- 覆盖 2-3 类场景

建议场景：

- 领域知识问答
- 结构化抽取
- SQL / 数据查询解释
- 工具调用决策
- 多语言或中英混合输入

### 11.2 推荐字段

每条 case 推荐字段：

- `case_id`
- `query`
- `expected_answer`
- `tags`
- `difficulty`
- `eval_type` 或 `eval_types`
- `metadata`

### 11.3 校验原则

数据集加载器需要负责：

- 基础字段校验
- 格式校验
- 记录非法输入

非法输入数据属于必须覆盖的鲁棒性场景之一。

---

## 12. 结果持久化与产物格式

### 12.1 设计目标

结果存储要同时满足：

- 运行中可恢复
- 运行后可查询
- 后续可做 compare
- 不把所有职责都压给数据库
- 不把核心元数据只放在文件里

### 12.2 冻结后的职责分工

v1 冻结如下职责分工：

- 数据库是运行态和元数据的权威存储
- 文件是可移植、可导出的结果产物

也就是说：

- run 状态、配置、summary、状态流转日志，以数据库为准
- case 级详细结果以文件产物导出，同时可在数据库留索引或摘要

### 12.3 v1 文件产物

v1 文件产物固定为：

- `outputs/{run_id}/case_results.jsonl`
- `outputs/{run_id}/meta.json`

语义如下：

`case_results.jsonl`

- 逐行写入 case 结果
- 作为后续 compare 的稳定输入之一
- 包含 case_id、provider 结果、eval 结果、错误信息等

`meta.json`

- run 完成后从数据库导出的便携元数据快照
- 用于归档、离线分析和后续 compare
- 不是运行中的唯一真相来源

### 12.4 数据库仍是 meta 的权威来源

这里明确一下你提到的问题：

- `meta` 不应该只存在文件里
- 数据库才应该是运行时和查询时的权威来源

因此 v1 的规定是：

- DB 为 source of truth
- `meta.json` 为导出快照

如果两者在运行中出现不一致：

- 以数据库为准

如果 run 已完成并归档：

- `meta.json` 是可移植产物

### 12.5 推荐数据库表

v1 推荐三张核心表：

- `runs`
- `case_results`
- `state_logs`

`runs` 至少包含：

- `run_id`
- `dataset_path`
- `provider_name`
- `model_config`
- `status`
- `summary_json`
- `created_at`
- `started_at`
- `finished_at`
- `updated_at`

`case_results` 至少包含：

- `run_id`
- `case_id`
- `status`
- `output_path`
- `eval_results_json`
- `latency_ms`
- `error`
- `created_at`

`state_logs` 至少包含：

- `run_id`
- `from_status`
- `to_status`
- `event`
- `message`
- `created_at`

### 12.6 为什么不把所有大文本都塞进 SQLite

不建议把完整输出全文、完整 trace、完整比较产物全部直接塞进 DB。

原因：

- 不利于后续迁移
- 不利于归档
- 不利于 compare 复用
- 对 SQLite 并不友好

因此 v1 采用 DB + 文件的混合模式。

---

## 13. 聚合指标

v1 run 结束后至少需要产出以下 summary：

- `total_cases`
- `passed_cases`
- `failed_cases`
- `error_cases`
- `pass_rate`
- `tag_pass_rates`
- `avg_latency_ms`
- `p95_latency_ms`
- `error_count`
- `error_distribution`

注意：

- 这些指标属于 run summary
- 它们表达业务结果
- 它们不应与 run 状态机语义混用

---

## 14. 错误处理策略

### 14.1 必须覆盖的鲁棒性场景

v1 至少覆盖以下场景中的 4 类，推荐尽量全覆盖：

- 非法输入数据
- provider 调用失败
- provider 超时
- evaluator 异常
- 单个 case 重试失败
- 并发执行中的部分失败
- 结果文件写入失败

### 14.2 错误处理原则

- 单条 case 失败不影响整体 run
- 所有错误先结构化记录
- 可重试错误按策略重试
- FATAL 错误才允许终止整个 run

### 14.3 写入失败降级

如果文件写入失败：

- 尝试降级到临时目录
- 在日志和 CLI 中明确提示
- 不能静默吞掉问题

实现注意：

- 不要使用 `tempfile.mktemp()`
- 应使用安全的临时文件创建方式

---

## 15. 并发模型

v1 并发模型保持简单但是真正并发：

- `asyncio`
- run 级 queue / 调度
- case 级并发任务
- Provider 侧用 Semaphore 控制并发上限
- Evaluator 规则执行默认在 case task 内同步执行
- writer queue 串行写数据库和结果文件

解释：

- 当前瓶颈主要在 Provider I/O
- 规则 Evaluator 通常很轻
- 没必要在 v1 里把 Provider worker 池和 Evaluator worker 池拆成两套复杂调度
- writer queue 可以显著降低 SQLite 和文件 append 的并发复杂度

如果后续加入 LLM Judge，再单独升级 Evaluator 执行模型。

---

## 16. 后续演进路线

### 16.1 v2 方向

v2 可以在不推翻 v1 核心抽象的前提下，演进为多 stage worker：

```text
run queue
  -> case queue
  -> provider worker pool
  -> evaluator queue
  -> evaluator worker pool
  -> writer queue
  -> DB / artifact sink
```

适用场景：

- 加入 `llm_judge`
- Evaluator 变成异步 I/O 密集
- Provider 和 Evaluator 需要独立扩缩容
- 需要更明确的阶段级监控

### 16.2 v3 方向

v3 再考虑：

- Redis / Celery / 其他外部消息队列
- 多进程或分布式 worker
- provider queue 和 evaluator queue 的独立消费组
- 更细粒度的 backpressure 与限流
- API 驱动的后台任务系统

### 16.3 v1 到 v2 的前提

为了让 v1 能平滑升级到 v2，当前实现应保持以下边界：

- Provider 与 Evaluator 都只接受明确输入并返回结构化输出
- CaseResult 在写入前已经完整成型
- writer 是独立职责
- run / case 状态流转不依赖 CLI
- queue 语义先存在，即便实现仍是单机版

---

## 16. 配置管理

### 16.1 配置分层

v1 采用两类配置：

- `config.yaml`
  - 项目级运行配置
- `providers.yaml`
  - Provider 实例配置

### 16.2 原则

- 敏感信息只走环境变量
- Provider 名称由配置定义，不写死在业务逻辑中
- 用户切换模型主要通过改配置完成

### 16.3 `config.yaml` 推荐字段

- `timeout_ms`
- `max_retries`
- `concurrency`
- `output_dir`
- `evaluators_package`
- `defaults.evaluators`

### 16.4 `providers.yaml` 推荐字段

- `type`
- `base_url`
- `model`
- `api_key_env`
- `timeout_ms`
- `max_retries`
- `provider_concurrency_limit`

---

## 17. 代码层面的冻结约束

这些是进入实现前就要固定的工程约束。

### 17.1 Pydantic 默认值

所有可变默认值必须使用 `default_factory`。

禁止：

```python
tags: list[str] = []
metadata: dict = {}
eval_results: dict = {}
model_config: dict = {}
```

应改为：

```python
from pydantic import Field

tags: list[str] = Field(default_factory=list)
metadata: dict = Field(default_factory=dict)
eval_results: dict = Field(default_factory=dict)
model_config: dict = Field(default_factory=dict)
```

### 17.2 文件写入

- 使用原子写或尽量接近原子写的策略
- 目录创建要幂等
- 临时文件要安全创建

### 17.3 状态常量

- 状态值只能来自统一 Enum
- 不允许文档或代码同时混用 `COMPLETED` 和 `SUCCEEDED` 表示 run 终态

规则：

- run 用 `SUCCEEDED`
- case 用 `COMPLETED`

---

## 18. 推荐实施顺序

### Phase 1

- 项目结构
- 配置系统
- 数据模型
- 状态枚举和异常定义

### Phase 2

- Evaluator 注册机制
- 规则类 Evaluator
- 数据集加载

### Phase 3

- Provider factory
- Mock Provider
- OpenAI-compatible Provider 框架

### Phase 4

- SQLite 层
- 文件产物输出
- 状态日志

### Phase 5

- Executor
- RunService
- 并发控制
- 断点恢复

### Phase 6

- CLI
- 自动化测试
- 示例数据与示例输出

---

## 19. v1 验收标准

### 19.1 功能验收

- 无外部 API key 时可以用 `mock` 完整运行
- 可以提交一次 run 并完成执行
- 可以并发执行至少 20 条 case
- 可以记录 run 状态和状态变更日志
- 可以在中断后恢复未完成 case
- 可以生成 `case_results.jsonl`
- 可以导出 `meta.json`

### 19.2 工程验收

- Provider 配置不写死在业务逻辑中
- 新增 Evaluator 不需要改 Runner 主流程
- 单条 case 失败不会导致整体不可用
- 至少有 3 个自动化测试或等价验证
- README 说明 AI 工具使用、关键设计决定和验证方式

---

## 20. 文档收敛原则

从现在开始，文档分工建议固定为：

- `docs/raw_requirement.txt`
  - 原始需求，不改语义
- `docs/7_v1_implementation_spec.md`
  - v1 权威实现规格
- `docs/6_version1_dev_plan.md`
  - 按 spec 展开的开发计划
- 其他文档
  - 作为历史讨论和参考材料，不再作为实现依据

这样后续实现、review 和迭代时，入口会清晰得多。
