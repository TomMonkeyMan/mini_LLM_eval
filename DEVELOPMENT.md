# Mini LLM Eval Development Guide

> 版本: v1.1
> 最后更新: 2026-04-26
> 适用范围: 当前仓库的实际开发协作

---

## 1. 文档定位

本文件不是通用编程守则，也不是未来愿景清单。

它只回答三个问题：

1. 当前仓库已经采用了什么
2. 当前开发时哪些约束应当遵守
3. 哪些东西只是后续计划，当前不强制

文档优先级如下：

1. `docs/7_v1_implementation_spec.md`
   当前 v1 的权威实现规格
2. `RULES.md`
   通用工程行为守则
3. `DEVELOPMENT.md`
   当前仓库的实际开发约束和建议

如果本文件与 `docs/7_v1_implementation_spec.md` 冲突，以规格文档为准。

---

## 2. 当前项目现实

当前仓库已经采用的技术与结构如下：

- Python `3.11`
- 包结构：`src/mini_llm_eval/`
- 配置：YAML + Pydantic
- 数据库：`aiosqlite`
- CLI：`typer` + `rich`
- HTTP Provider：`httpx.AsyncClient`
- 测试：`pytest` + `pytest-asyncio`
- 运行时日志：标准库 `logging`，JSON line 输出

当前核心模块边界如下：

- `core`
  - 配置
  - 异常
  - logging
  - shared types
- `models`
  - Pydantic schemas
- `providers`
  - provider 抽象
  - factory
  - 内置 provider
  - plugin provider
- `evaluators`
  - evaluator 抽象
  - registry
  - 内置规则
- `services`
  - dataset loader
  - executor
  - run service
- `db`
  - SQLite persistence
  - file artifact storage
- `cli`
  - run / resume / status

---

## 3. 当前强约束

下面这些是当前仓库开发时应当直接遵守的。

### 3.1 范围约束

v1 当前不做：

- compare
- FastAPI / HTTP API
- Web UI
- 分布式队列
- 可视化报表

如果新改动会把代码明显往这些方向扩展，默认不做，除非明确提出。

### 3.2 架构约束

依赖方向保持单向：

`cli -> services -> providers/evaluators/db -> core/models`

具体要求：

- CLI 不直接编排 Provider 或数据库细节
- Provider 不依赖 CLI
- Evaluator 不依赖具体 Provider
- 数据库层不承载业务编排逻辑
- 可复用能力优先放在 service 层

### 3.3 Provider 约束

当前 Provider 体系采用：

- config-driven provider 配置
- `factory.py` 创建 provider
- plugin provider 作为用户扩展入口

因此：

- 不要再引入第二套内部 `ProviderRegistry` 机制
- 新增 provider 时优先遵守当前 factory / config 模式
- HTTP 型 provider 默认按异步远程服务处理

### 3.4 状态与产物约束

Run 状态语义固定为：

- `PENDING`
- `RUNNING`
- `SUCCEEDED`
- `FAILED`
- `CANCELLED`

Case 状态语义固定为：

- `PENDING`
- `COMPLETED`
- `ERROR`

当前 v1 的结果产物约定为：

- `outputs/{run_id}/case_results.jsonl`
- `outputs/{run_id}/meta.json`

新改动不要破坏这两个产物入口。

### 3.5 日志约束

当前运行时日志采用标准库 `logging`。

要求：

- 使用 `mini_llm_eval.core.logging`
- 输出结构化字段，适合 JSON line 消费
- 关键事件必须带稳定字段，例如：
  - `event`
  - `run_id`
  - `case_id`
  - `provider_name`
  - `status`

不要在当前阶段再引入 `structlog` 或第二套日志框架。

### 3.6 持久化约束

当前数据库层采用 `aiosqlite` 原生 SQL。

因此：

- 不要引入 SQLAlchemy 作为当前 v1 的默认实现
- 小型持久化逻辑可以继续留在 `database.py`
- 文件产物输出继续由 `file_storage.py` 负责

---

## 4. 当前推荐实践

下面这些是推荐做法，但不是“写了别的就一定错”。

### 4.1 类型

- 优先使用 Python 3.10+ 原生类型写法
  - `list[str]`
  - `dict[str, Any]`
  - `User | None`
- 稳定结构优先使用 `TypedDict`
  - 例如 DB record
  - run meta
  - summary payload

### 4.2 错误处理

- 项目异常优先继承现有异常体系
- 保留异常链：`raise X(...) from exc`
- 用户可见错误消息要具体，直接说明失败动作和对象

### 4.3 测试

有改动时，优先补最靠近改动点的测试。

当前重点测试面：

- config
- schemas
- providers
- evaluators
- dataset
- services
- storage
- cli
- logging

规则：

- 修 bug，优先补回归测试
- 加 evaluator / provider，至少补对应模块测试
- 改 CLI 路径，至少跑 `tests/test_cli.py`
- 改核心编排路径，至少跑 `tests/test_services.py`

### 4.4 文档

- 公开模块建议写简短 docstring
- 对外可用的新能力，需要更新 `README.md`
- 如果涉及范围、架构、产物格式变化，需要同步看 `docs/7_v1_implementation_spec.md`

### 4.5 代码风格

- 默认保持现有代码风格，不做无关统一
- import 顺序、命名、注释保持一致即可
- 不要求当前仓库所有类统一加 `__slots__`
- 不要求所有公开方法都补 Google 风格长 docstring

---

## 5. 当前不强制的事项

下面这些可以作为后续工程化方向，但当前不应写成硬性规定：

- `ruff format`
- `ruff check`
- `pyright strict`
- `pre-commit`
- 全项目统一 `__slots__`
- 全项目统一 async context manager 包装
- 全项目统一长 docstring 模板
- Protocol 全覆盖
- 按理想目录重拆测试文件

这些事项如果后续真的要落地，应先：

1. 明确决定采用
2. 在仓库里实际配置好
3. 再把它升级为强约束

在那之前，它们只能算 planned，不算 enforced。

---

## 6. 提交与协作

### 6.1 Commit 原则

- commit 保持单一主题
- 不把无关文件混进来
- review 文件默认不要提交，除非明确要求
- 文档改动和代码改动可以同 commit，但要高度相关

### 6.2 Review 关注点

当前 review 优先关注：

- 是否符合 v1 范围
- 是否破坏现有模块边界
- 是否引入不必要复杂度
- 是否补了必要测试
- 是否破坏状态语义或结果产物格式

不要把 review 重点放在：

- 为了风格而风格的重构
- 当前未落地工具链的“违规”
- 和当前架构路线不一致的理想化建议

---

## 7. 建议工作流

一个比较适合当前仓库的开发顺序是：

1. 先确认需求是否属于 v1 范围
2. 找到会受影响的模块边界
3. 优先做最小实现
4. 补对应测试
5. 跑受影响测试，必要时跑全量
6. 更新 README 或相关 docs
7. 再提交

---

## 8. 一句话原则

当前项目最重要的不是“把文档写得像一个成熟大平台”，而是：

- 保持 v1 核心路径稳定
- 保持架构方向一致
- 不提前引入 v2/v3 的复杂度
- 每次改动都真实、可验证、可维护
