# Code Review #6 - 代码规范与标准

> 审查时间: 2026-04-26
> 审查者: Claude
> 审查范围: 全局代码规范、性能、可读性

---

## 1. 总体评价

**代码质量: 良好，但规范性有提升空间**

Codex 的代码功能正确，结构清晰，但缺乏统一的编码标准。需要建立规范以便后续维护和扩展。

---

## 2. 优点确认

| 项目 | 状态 | 说明 |
|------|------|------|
| 类型注解 | ✅ | 全面使用 Python 3.10+ 语法 (`str \| None`) |
| Future imports | ✅ | 统一 `from __future__ import annotations` |
| 模块 docstring | ✅ | 每个模块都有说明 |
| 异常链 | ✅ | `raise X from exc` 正确使用 |
| 模块划分 | ✅ | 按功能清晰拆分 |

---

## 3. 需要改进的问题

### 3.1 `__slots__` 缺失 - 高优先级

**问题**: 非 Pydantic 类没有使用 `__slots__`

```python
# 当前代码 - src/mini_llm_eval/services/executor.py
class Executor:
    def __init__(self, concurrency: int = 4, timeout_ms: int = 30000):
        self.provider_semaphore = asyncio.Semaphore(concurrency)
        self.timeout_ms = timeout_ms
        self.result_queue = ...
        self._sentinel = object()
```

**影响**:
- 每个实例额外占用 ~64 bytes（`__dict__`）
- 属性访问速度下降 ~20%
- 无法防止意外添加属性

**建议**:

```python
class Executor:
    __slots__ = ('provider_semaphore', 'timeout_ms', 'result_queue', '_sentinel')

    def __init__(self, concurrency: int = 4, timeout_ms: int = 30000):
        self.provider_semaphore = asyncio.Semaphore(concurrency)
        self.timeout_ms = timeout_ms
        ...
```

**需要添加 `__slots__` 的类**:

| 文件 | 类 |
|------|-----|
| `services/executor.py` | `Executor` |
| `services/run_service.py` | `RunService` |
| `db/database.py` | `Database` |
| `db/file_storage.py` | `FileStorage` |
| `providers/base.py` | `BaseProvider` 子类 |
| `evaluators/base.py` | `BaseEvaluator` 子类 |

---

### 3.2 私有属性命名不一致 - 中优先级

**问题**: 有的用 `_name`，有的用 `name`

```python
# OpenAICompatibleProvider - 使用私有
self._name = name
self._config = config
self._client = client

# RunService - 使用公开
self.db = db
self.file_storage = file_storage
self.providers = providers
```

**建议标准**:

| 类型 | 前缀 | 示例 |
|------|------|------|
| 私有属性（不对外暴露） | `_` | `self._client` |
| 受保护属性（子类可用） | `_` | `self._config` |
| 公开属性（依赖注入） | 无 | `self.db` |
| 常量 | `_` + 大写 | `_SENTINEL` |

**统一规则**:
- 外部传入的依赖（db, storage）：公开
- 内部创建的资源（client, semaphore）：私有 `_`
- 配置对象：私有 `_config`

---

### 3.3 全局状态管理 - 高优先级

**问题**: 模块级全局变量缺乏线程安全

```python
# src/mini_llm_eval/core/config.py
_config_cache: Config | None = None
_providers_cache: dict[str, ProviderConfig] | None = None

def set_runtime_config(...):
    global _config_cache, _providers_cache
    _config_cache = config
    ...
```

**风险**:
- 多线程/多进程环境下状态污染
- 测试隔离困难
- 隐式依赖难以追踪

**建议方案 A - contextvars（推荐）**:

```python
from contextvars import ContextVar

_config_var: ContextVar[Config | None] = ContextVar('config', default=None)
_providers_var: ContextVar[dict[str, ProviderConfig] | None] = ContextVar('providers', default=None)

def get_config() -> Config:
    config = _config_var.get()
    if config is None:
        config = load_config()
        _config_var.set(config)
    return config

def set_runtime_config(config: Config | None = None, ...):
    _config_var.set(config)
    ...
```

**建议方案 B - 依赖注入**:

```python
@dataclass
class RuntimeContext:
    config: Config
    providers: dict[str, ProviderConfig]

# 显式传递
service = RunService(context=runtime_context)
```

---

### 3.4 返回类型缺乏结构约束 - 中优先级

**问题**: 大量使用 `dict[str, Any]`

```python
# src/mini_llm_eval/db/database.py
async def get_run(self, run_id: str) -> dict[str, Any] | None:
    ...
```

**影响**:
- 类型检查无效
- IDE 自动补全失效
- 重构容易出错

**建议**: 使用 TypedDict

```python
from typing import TypedDict

class RunRecord(TypedDict):
    run_id: str
    dataset_path: str
    provider_name: str
    model_config_json: str
    status: str
    summary_json: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    updated_at: str

async def get_run(self, run_id: str) -> RunRecord | None:
    ...
```

**需要添加 TypedDict 的返回类型**:

| 方法 | 建议 TypedDict |
|------|----------------|
| `db.get_run()` | `RunRecord` |
| `db.get_case_results()` | `list[CaseResultRecord]` |
| `db.get_state_logs()` | `list[StateLogRecord]` |
| `run_service._build_meta()` | `RunMeta` |
| `run_service._build_summary()` | `RunSummaryDict` |

---

### 3.5 常量定义 - 低优先级

**问题**: 字符串字面量散落各处

```python
# 多处出现
RunStatus.PENDING.value
"pending"
"completed"
"run_created"
```

**建议**: 集中定义常量

```python
# src/mini_llm_eval/core/constants.py

class Events:
    RUN_CREATED = "run_created"
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_CANCELLED = "run_cancelled"
    RUN_RESUMED = "run_resumed"

class CaseStatusValue:
    PENDING = "pending"
    COMPLETED = "completed"
    ERROR = "error"
```

---

### 3.6 重复代码模式 - 中优先级

**问题 1**: Provider 清理模式重复

```python
# start_run 和 resume_run 都有这个模式
provider = None
try:
    provider = self._create_provider(...)
    # ... 业务逻辑
except Exception:
    raise
finally:
    if provider is not None:
        await provider.close()
```

**建议**: 使用 async context manager

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def managed_provider(self, provider_name: str):
    provider = self._create_provider(provider_name)
    try:
        yield provider
    finally:
        await provider.close()

# 使用
async with self.managed_provider(run_config.provider_name) as provider:
    results = await executor.execute_batch(...)
```

**问题 2**: CLI 中多次 `asyncio.run()`

```python
# src/mini_llm_eval/cli/main.py:92-93
asyncio.run(service.start_run(run_config))
run_record = asyncio.run(db.get_run(resolved_run_id))
```

**建议**: 合并为单个 async 函数

```python
async def _execute_run(service, run_config, db):
    await service.start_run(run_config)
    return await db.get_run(run_config.run_id)

run_record = asyncio.run(_execute_run(service, run_config, db))
```

---

### 3.7 文档字符串标准 - 低优先级

**问题**: docstring 风格不统一

```python
# 有的简单一行
"""Load dataset from path."""

# 有的无参数说明
async def execute_batch(self, run_id, cases, provider, evaluators, on_result):
    """Execute cases concurrently and write results through a writer queue."""
```

**建议**: 采用 Google 风格

```python
async def execute_batch(
    self,
    run_id: str,
    cases: list[EvalCase],
    provider: BaseProvider,
    evaluators: dict[str, BaseEvaluator],
    on_result: ResultWriter,
) -> list[CaseResult]:
    """Execute cases concurrently with bounded provider concurrency.

    Args:
        run_id: Unique identifier for this run.
        cases: List of evaluation cases to process.
        provider: Model provider instance.
        evaluators: Mapping from evaluator name to instance.
        on_result: Callback for writing results to storage.

    Returns:
        List of case results in completion order.

    Raises:
        EvaluatorError: If a required evaluator is not found.
    """
```

---

### 3.8 性能优化建议 - 低优先级

**问题 1**: Pydantic `model_dump()` 频繁调用

```python
# 每次都完整序列化
payload = result.model_dump(mode="json")
eval_results_json = json.dumps(payload["eval_results"], ...)
payload_json = json.dumps(payload, ...)
```

**建议**: 直接序列化

```python
payload_json = result.model_dump_json()
# 如果只需要部分字段
eval_results_json = json.dumps(
    {k: v.model_dump(mode="json") for k, v in result.eval_results.items()}
)
```

**问题 2**: 列表推导可以优化

```python
# 当前
remaining_cases = [case for case in cases if case.case_id not in completed_case_ids]

# 如果 completed_case_ids 很大，应该确保是 set
completed_case_ids: set[str] = await self.db.get_completed_cases(run_id)  # ✅ 已经是 set
```

---

### 3.9 错误处理标准 - 中优先级

**问题**: 错误消息不规范

```python
raise ProviderInitError("openai_compatible provider requires base_url")
raise PersistenceError(f"Run not found: {run_id}")
raise EvaluatorError(f"Unknown evaluator: {name}")
```

**建议**: 引入错误代码系统

```python
# src/mini_llm_eval/core/error_codes.py
from enum import Enum

class ErrorCode(str, Enum):
    PROVIDER_MISSING_BASE_URL = "E1001"
    PROVIDER_MISSING_MODEL = "E1002"
    PROVIDER_MISSING_API_KEY = "E1003"
    RUN_NOT_FOUND = "E2001"
    INVALID_TRANSITION = "E2002"
    EVALUATOR_NOT_FOUND = "E3001"
    DATASET_LOAD_FAILED = "E4001"

class EvalRunnerException(Exception):
    def __init__(self, code: ErrorCode, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code.value}] {message}")

# 使用
raise ProviderInitError(
    ErrorCode.PROVIDER_MISSING_BASE_URL,
    "openai_compatible provider requires base_url"
)
```

---

## 4. 标准规范总结

### 4.1 必须执行（P0）

| 规范 | 说明 |
|------|------|
| `__slots__` | 所有非 Pydantic 类必须定义 |
| TypedDict | 返回 `dict[str, Any]` 的方法改用 TypedDict |
| async context manager | Provider 资源管理统一使用 |

### 4.2 建议执行（P1）

| 规范 | 说明 |
|------|------|
| 私有属性命名 | 统一 `_` 前缀规则 |
| contextvars | 替代模块级全局变量 |
| 错误代码 | 引入结构化错误码 |
| docstring | 采用 Google 风格，复杂函数必须有参数说明 |

### 4.3 可选优化（P2）

| 规范 | 说明 |
|------|------|
| 常量集中 | 创建 `constants.py` |
| 合并 asyncio.run | CLI 中减少事件循环创建 |
| Pydantic 序列化 | 使用 `model_dump_json()` |

---

## 5. 检查清单模板

```python
# 新增类检查清单
# [ ] 是否定义了 __slots__?
# [ ] 属性命名是否符合规范（公开 vs 私有）?
# [ ] 是否有完整的 docstring?
# [ ] 返回类型是否有 TypedDict 约束?
# [ ] 是否使用了 context manager 管理资源?
# [ ] 错误是否使用标准错误码?
```

---

## 6. 建议的文件结构

```
src/mini_llm_eval/
├── core/
│   ├── __init__.py
│   ├── config.py
│   ├── exceptions.py
│   ├── constants.py       # 新增：常量定义
│   ├── error_codes.py     # 新增：错误码
│   └── types.py           # 新增：TypedDict 定义
├── models/
│   └── schemas.py
├── ...
```

---

## 7. 下一步行动

### 立即可做
1. [ ] 为 `Executor`, `RunService`, `Database`, `FileStorage` 添加 `__slots__`
2. [ ] 创建 `core/types.py` 定义 TypedDict

### 后续迭代
3. [ ] 引入 `contextvars` 替代全局缓存
4. [ ] 创建 `error_codes.py`
5. [ ] 统一 docstring 风格

---

*文档版本: v1.0*
*最后更新: 2026-04-26*
