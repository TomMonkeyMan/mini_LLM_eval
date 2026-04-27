# Raw Requirement Gap Report

> 文档状态：对 `docs/raw_requirement.txt` 的当前实现差异清单
>
> 更新日期：2026-04-27
>
> 说明：
> - 本文档只回答一个问题：如果直接按 `raw_requirement.txt` 验收，当前项目还差什么
> - 它不是 v1 实现权威规格；实现边界仍以 `docs/7_v1_implementation_spec.md` 为准
> - 因此本文会同时区分：
>   - 已满足
>   - 部分满足
>   - 尚未满足

---

## 1. 结论

当前项目对 `raw_requirement.txt` 的覆盖情况可以概括为：

- 核心执行系统：**已满足**
- compare 基础能力：**已满足**
- README / 设计文档 / 自动化测试：**已满足**
- 交付物完整性：**本轮已明显补齐**

在补充 demo artifact 和 gap report 之后，当前最主要的剩余 gap 已不在执行主干，而在增强能力：

1. 还没有独立报告生成器
2. `RUNNING` run 主动取消尚未实现
3. provider 级限流仍只有基础版本

---

## 2. 逐项对照

### 2.1 已满足

以下 raw requirement 已经满足：

| 要求 | 当前状态 | 说明 |
|------|----------|------|
| 本地评测集加载 | 已满足 | 支持 JSONL / JSON |
| 至少 20 条测试样例 | 已满足 | `data/eval_cases.jsonl` 当前为 20 条 |
| 覆盖 2-3 类场景 | 已满足 | 数据集已覆盖多类 case |
| Provider 抽象 | 已满足 | 统一 `BaseProvider` 接口 |
| mock provider | 已满足 | 可离线运行 |
| second provider | 已满足 | `openai_compatible` + `plugin` |
| Provider 配置不能写死 | 已满足 | 通过 `providers.yaml` 和 plugin/provider config |
| Evaluator 抽象 | 已满足 | 统一 evaluator 接口 |
| 至少 3 种 evaluator | 已满足 | 当前已实现多种 evaluator |
| evaluator 失败不导致整体 crash | 已满足 | 单 case / 单 evaluator 错误隔离 |
| 可提交并执行评测任务 | 已满足 | CLI `run` 已实现 |
| 支持并发执行 case | 已满足 | asyncio 并发执行器已实现 |
| 运行结果聚合 | 已满足 | pass rate、tag pass rate、latency、error distribution 均有 |
| 对比两次实验结果 | 已满足 | CLI `compare` + `Comparator` 已实现 |
| CLI 或 HTTP API 二选一 | 已满足 | 已选择 CLI 方案 |
| 鲁棒性异常处理 | 已满足 | dataset/provider/timeout/evaluator/persistence 等异常均有处理 |
| 开放方向至少选 1 个深入实现 | 已满足 | 已实现状态机、断点恢复、插件式 evaluator、并发执行 |
| design.md 或等价设计说明 | 已满足 | `docs/7_v1_implementation_spec.md` 等文档已覆盖 |
| 至少 3 个自动化测试 | 已满足 | 当前测试远超最低要求 |
| README AI 工具说明 | 已满足 | README 已说明 AI 工具、帮助范围、关键决策、验证方式 |
| 至少 2 份示例 run output | 已满足 | 已补充 `demo/sample_runs/run-baseline` 和 `demo/sample_runs/run-candidate` |

### 2.2 部分满足

以下要求已经有等价落地，但从“交付感知”上看仍可补强：

| 要求 | 当前状态 | 说明 |
|------|----------|------|
| 聚合指标并生成报告 | 部分满足 | 当前已有 `meta.json`、`case_results.jsonl`、CLI compare 输出和 demo，但没有独立 report exporter |

### 2.3 尚未满足或明确未做

如果严格按 `raw_requirement.txt` 外延理解，以下仍属于未做或未完全做：

| 项目 | 当前状态 | 说明 |
|------|----------|------|
| 完整报告生成器 | 未做 | 当前没有独立 Markdown / HTML report service |
| HTTP API | 未做 | 但 raw requirement 允许 CLI / HTTP API 二选一，因此不影响最低验收 |
| `RUNNING` run 主动取消 | 未做 | 当前仅可靠支持 `PENDING -> CANCELLED` |
| provider 级限流 | 部分满足 | 已支持 `provider_concurrency_limit` 和 `requests_per_second`，但还不是自适应/分布式版本 |

---

## 3. 当前剩余 gap

从“项目能不能用”角度看，核心执行已经可用；从“按题目交付是否完整”角度看，本轮补齐后剩余的 gap 主要是增强项。

### 3.1 独立报告生成器仍未实现

当前项目已经有：

- `meta.json`
- `case_results.jsonl`
- CLI summary / compare 表格输出
- `demo/` 中的样例产物

但如果严格按“生成报告”理解，仍缺少单独的：

- Markdown report exporter
- HTML report exporter
- 独立 report service

### 3.2 `RUNNING` cancel 仍然只是设计完成

当前只支持：

- `PENDING -> CANCELLED`

尚不支持：

- `RUNNING -> CANCELLED` 的真实中断执行路径

### 3.3 provider 级限流仍是基础版本

当前已实现：

- `provider_concurrency_limit`
- `requests_per_second`

但还没有进一步实现：

- 更明确的 provider-level concurrency cap
- 429 驱动的自适应退让
- 多进程 / 多 worker 共享限流
- 更细粒度的突发流量控制

---

## 4. 本轮已补齐内容

本轮已新增：

1. `docs/12_raw_requirement_gap_report.md`
2. `demo/README.md`
3. `demo/quickstart/README.md`
4. `demo/demo_cases.jsonl`
5. 两份完整 demo artifact：
   - `demo/sample_runs/run-baseline`
   - `demo/sample_runs/run-candidate`
6. `demo/compare_example.md`
7. README 中的 demo 入口说明

---

## 5. 鲁棒性条款对照

`raw_requirement.txt` 要求“至少处理 4 类异常”，当前项目对所列 7 类异常的覆盖如下：

| 异常类型 | 当前状态 | 说明 |
|------|----------|------|
| 非法输入数据 | 已满足 | 数据集文件不存在、格式非法、字段缺失、空数据集等都会被显式拒绝 |
| provider 调用失败 | 已满足 | 单 case 会转为错误结果，不会直接打挂整批 run |
| provider 超时 | 已满足 | provider 层和 executor 层均有 timeout 保护 |
| evaluator 异常 | 已满足 | evaluator 异常会被捕获并写入结构化结果 |
| 单个 case 重试失败 | 已满足 | retry budget 耗尽后落为 case error，而非 run fatal |
| 并发执行中的部分失败 | 已满足 | 单 case task 错误隔离，其余 case 继续执行 |
| 结果文件写入失败 | 部分满足 | 主输出目录不可写时支持 fallback；但数据库级持久化 fatal 仍会导致 run 失败 |

结论：

- 已覆盖 7 类中的至少 6 类
- 明显超过 raw requirement 的“至少 4 类”门槛
- “程序不能因为单条 case 失败而整体不可用”这一点对 provider/evaluator/case 级失败是满足的
- 系统级持久化失败当前仍按 run 级 fatal error 处理，这属于当前实现的明确边界

---

## 6. 当前验收判断

在本轮补齐后，项目对 `raw_requirement.txt` 的状态可以表述为：

- **最低功能要求已满足**
- **交付展示要求基本满足**
- **剩余未做项主要属于增强项而非核心缺陷**

仍可继续增强但不再构成主要 gap 的内容包括：

- 独立报告导出器
- `RUNNING` run cancel
- 更完整的 provider 级限流
- HTTP API
