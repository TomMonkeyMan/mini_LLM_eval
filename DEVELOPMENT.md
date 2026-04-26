# Mini LLM Eval 开发规范

> 版本: v1.0
> 最后更新: 2026-04-26
> 适用范围: 所有贡献者（人类 & AI）

---

## 1. Python 版本与环境

```yaml
python: ">=3.11"
package_manager: pip / conda
formatter: ruff format
linter: ruff check
type_checker: pyright (strict mode)
```

---

## 2. 代码风格

### 2.1 Import 规范

```python
# 1. 标准库（按字母排序）
from __future__ import annotations  # 必须第一行

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

# 2. 第三方库
import httpx
from pydantic import BaseModel, Field

# 3. 项目内部
from mini_llm_eval.core.config import Config
from mini_llm_eval.core.exceptions import EvalRunnerException
from mini_llm_eval.models.schemas import CaseResult
```

### 2.2 类型注解

```python
# ✅ 使用 Python 3.10+ 语法
def process(items: list[str]) -> dict[str, int]: ...
def get_user(id: int) -> User | None: ...

# ❌ 不使用旧语法
from typing import List, Dict, Optional  # 不需要
def process(items: List[str]) -> Dict[str, int]: ...
```

### 2.3 字符串格式化

```python
# ✅ f-string（首选）
message = f"Run {run_id} completed with {count} cases"

# ✅ 多行 f-string
query = f"""
    SELECT * FROM runs
    WHERE run_id = {run_id!r}
    AND status = {status!r}
"""

# ❌ 不使用 .format() 或 %
message = "Run {} completed".format(run_id)  # 避免
message = "Run %s completed" % run_id  # 避免
```

---

## 3. 类设计规范

### 3.1 `__slots__` 规则

**所有非 Pydantic 类必须定义 `__slots__`**：

```python
# ✅ 正确
class Executor:
    __slots__ = ('_semaphore', '_timeout_ms', '_queue', '_sentinel')

    def __init__(self, concurrency: int = 4, timeout_ms: int = 30000):
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout_ms = timeout_ms
        ...

# ❌ 错误 - 缺少 __slots__
class Executor:
    def __init__(self, concurrency: int = 4):
        self.semaphore = asyncio.Semaphore(concurrency)
```

**例外**：
- Pydantic `BaseModel` 子类（Pydantic 自己管理）
- 需要动态属性的类（必须注释说明原因）

### 3.2 属性命名规范

| 类型 | 前缀 | 示例 | 说明 |
|------|------|------|------|
| 私有属性 | `_` | `self._client` | 内部创建的资源 |
| 公开属性 | 无 | `self.db` | 外部传入的依赖 |
| 类常量 | `_` + 大写 | `_SENTINEL` | 类级别常量 |
| 模块常量 | 大写 | `SCHEMA` | 模块级别常量 |

```python
class RunService:
    __slots__ = ('db', 'file_storage', '_config', '_providers')

    def __init__(
        self,
        db: Database,                    # 依赖注入 -> 公开
        file_storage: FileStorage,       # 依赖注入 -> 公开
        config: Config | None = None,    # 内部使用 -> 私有
    ):
        self.db = db
        self.file_storage = file_storage
        self._config = config or get_config()
```

### 3.3 资源管理

**使用 async context manager 管理资源**：

```python
from contextlib import asynccontextmanager

class RunService:
    @asynccontextmanager
    async def _managed_provider(self, provider_name: str):
        """Context manager for provider lifecycle."""
        provider = self._create_provider(provider_name)
        try:
            yield provider
        finally:
            await provider.close()

    async def start_run(self, run_config: RunConfig) -> str:
        async with self._managed_provider(run_config.provider_name) as provider:
            results = await executor.execute_batch(...)
```

---

## 4. 类型定义规范

### 4.1 TypedDict 用于结构化返回

```python
# src/mini_llm_eval/core/types.py

from typing import TypedDict

class RunRecord(TypedDict):
    """Database run record structure."""
    run_id: str
    dataset_path: str
    provider_name: str
    model_config_json: str
    status: str
    summary_json: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None

class CaseResultRecord(TypedDict):
    """Database case result record structure."""
    id: int
    run_id: str
    case_id: str
    status: str
    output_path: str | None
    eval_results_json: str
    latency_ms: float
    error: str | None
    payload_json: str
    created_at: str
```

### 4.2 Protocol 用于接口定义

```python
from typing import Protocol

class ResultWriter(Protocol):
    """Protocol for result writing callback."""
    async def __call__(self, result: CaseResult) -> None: ...

class ProviderProtocol(Protocol):
    """Protocol for model providers."""
    @property
    def name(self) -> str: ...
    async def generate(self, query: str, **kwargs) -> ProviderResponse: ...
    async def close(self) -> None: ...
```

---

## 5. 错误处理规范

### 5.1 异常层次

```python
# src/mini_llm_eval/core/exceptions.py

class EvalRunnerException(Exception):
    """Base exception for all project errors."""
    pass

# 致命错误 - 导致 run 失败
class DatasetLoadError(EvalRunnerException): ...
class ProviderInitError(EvalRunnerException): ...
class PersistenceError(EvalRunnerException): ...

# 可重试错误
class ProviderError(EvalRunnerException): ...
class ProviderTimeoutError(ProviderError): ...

# 记录但不中断
class EvaluatorError(EvalRunnerException): ...
class InvalidTransitionError(EvalRunnerException): ...
```

### 5.2 异常链

```python
# ✅ 保留原始异常信息
try:
    result = do_something()
except ValueError as exc:
    raise ConfigError(f"Invalid config: {exc}") from exc

# ❌ 丢失异常链
except ValueError as exc:
    raise ConfigError(f"Invalid config: {exc}")
```

### 5.3 错误消息格式

```python
# 格式: "[组件] 动作失败: 原因"
raise ProviderInitError("openai_compatible provider requires base_url")
raise PersistenceError(f"Failed to query run {run_id}: {exc}")
raise EvaluatorError(f"Unknown evaluator: {name}")
```

---

## 6. 文档规范

### 6.1 模块 docstring

```python
"""SQLite persistence layer.

This module provides async SQLite operations for run metadata,
case results, and state transition logging.

Example:
    db = Database("eval.db")
    await db.init()
    await db.create_run(run_config)
"""
```

### 6.2 类 docstring

```python
class Executor:
    """Execute evaluation cases with bounded provider concurrency.

    This class manages the parallel execution of evaluation cases,
    controlling provider concurrency via semaphore and serializing
    result writes through a queue.

    Attributes:
        _semaphore: Limits concurrent provider calls.
        _timeout_ms: Per-case timeout in milliseconds.

    Example:
        executor = Executor(concurrency=4, timeout_ms=30000)
        results = await executor.execute_batch(...)
    """
```

### 6.3 函数 docstring（Google 风格）

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
        provider: Model provider instance for generating responses.
        evaluators: Mapping from evaluator name to instance.
        on_result: Async callback for persisting results.

    Returns:
        List of case results in completion order.

    Raises:
        EvaluatorError: If a required evaluator is not registered.

    Example:
        results = await executor.execute_batch(
            run_id="run-123",
            cases=cases,
            provider=provider,
            evaluators={"contains": ContainsEvaluator()},
            on_result=db.save_case_result,
        )
    """
```

### 6.4 何时需要完整 docstring

| 情况 | docstring 要求 |
|------|----------------|
| 公开 API（`__init__`, 公开方法） | 完整（Args, Returns, Raises） |
| 私有方法 `_xxx` | 一行简述即可 |
| 显而易见的方法（getter） | 可省略 |
| 复杂算法 | 必须详细说明 |

---

## 7. 测试规范

### 7.1 测试文件命名

```
tests/
├── test_config.py           # 测试 core/config.py
├── test_schemas.py          # 测试 models/schemas.py
├── test_evaluators.py       # 测试 evaluators/
├── test_providers.py        # 测试 providers/
├── test_database.py         # 测试 db/database.py
├── test_executor.py         # 测试 services/executor.py
├── test_run_service.py      # 测试 services/run_service.py
├── test_cli.py              # 测试 cli/
└── conftest.py              # 共享 fixtures
```

### 7.2 测试函数命名

```python
# 格式: test_<module>_<scenario>_<expected_outcome>
def test_config_load_missing_file_returns_default(): ...
def test_executor_timeout_returns_error_result(): ...
def test_run_service_resume_skips_completed_cases(): ...
```

### 7.3 Fixture 规范

```python
# conftest.py
import pytest
from pathlib import Path

@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Temporary database path."""
    return tmp_path / "test.db"

@pytest.fixture
def sample_cases() -> list[EvalCase]:
    """Sample evaluation cases for testing."""
    return [
        EvalCase(case_id="case-1", query="Q1", expected_answer="A1"),
        EvalCase(case_id="case-2", query="Q2", expected_answer="A2"),
    ]
```

### 7.4 Async 测试

```python
import pytest

@pytest.mark.asyncio
async def test_database_create_run(tmp_db: Path):
    db = Database(str(tmp_db))
    await db.init()
    run_id = await db.create_run(run_config)
    assert run_id == run_config.run_id
```

---

## 8. Git 规范

### 8.1 分支命名

```
main              # 稳定版本
dev               # 开发分支
feature/xxx       # 新功能
fix/xxx           # Bug 修复
refactor/xxx      # 重构
docs/xxx          # 文档更新
```

### 8.2 Commit 消息格式

```
<type>: <subject>

<body>

<footer>
```

**Type**:
- `feat`: 新功能
- `fix`: Bug 修复
- `refactor`: 重构（无功能变化）
- `docs`: 文档
- `test`: 测试
- `chore`: 构建/依赖/配置

**示例**:

```
feat: add plugin provider support

- Implement PluginProvider class for dynamic loading
- Support plugins_dir configuration
- Add tests for plugin loading and validation

Closes #123
```

### 8.3 PR 规范

```markdown
## Summary
- 1-3 bullet points describing changes

## Changes
- [ ] Added X
- [ ] Modified Y
- [ ] Removed Z

## Test Plan
- [ ] Unit tests pass
- [ ] Manual testing done

## Related Issues
Closes #xxx
```

---

## 9. 性能规范

### 9.1 避免的模式

```python
# ❌ 循环中重复创建对象
for case in cases:
    evaluator = ContainsEvaluator()  # 每次创建新实例
    result = evaluator.evaluate(...)

# ✅ 复用对象
evaluator = ContainsEvaluator()
for case in cases:
    result = evaluator.evaluate(...)
```

```python
# ❌ 不必要的完整序列化
payload = result.model_dump(mode="json")
json_str = json.dumps(payload)

# ✅ 直接序列化
json_str = result.model_dump_json()
```

### 9.2 并发控制

```python
# ✅ 使用 Semaphore 限制并发
semaphore = asyncio.Semaphore(concurrency)
async with semaphore:
    result = await provider.generate(query)

# ❌ 无限并发
tasks = [provider.generate(q) for q in queries]
await asyncio.gather(*tasks)  # 可能压垮服务
```

### 9.3 内存管理

```python
# ✅ 流式处理大数据集
async for result in executor.stream_results():
    await db.save(result)

# ❌ 全部加载到内存
results = await executor.get_all_results()
for result in results:
    await db.save(result)
```

---

## 10. 检查清单

### 新增类检查清单

- [ ] 定义了 `__slots__`？
- [ ] 属性命名符合规范（公开 vs 私有）？
- [ ] 有类 docstring？
- [ ] 返回类型有 TypedDict 约束？
- [ ] 资源使用 context manager 管理？

### 新增函数检查清单

- [ ] 有完整类型注解？
- [ ] 公开 API 有 docstring？
- [ ] 异常链正确（`from exc`）？
- [ ] 有对应的单元测试？

### PR 检查清单

- [ ] 所有测试通过？
- [ ] 代码格式化（`ruff format`）？
- [ ] 类型检查通过（`pyright`）？
- [ ] 文档已更新？

---

## 11. 工具配置

### pyproject.toml

```toml
[tool.ruff]
target-version = "py311"
line-length = 100
select = ["E", "F", "I", "W", "UP", "B", "SIM"]

[tool.ruff.isort]
known-first-party = ["mini_llm_eval"]

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "strict"
```

### .pre-commit-config.yaml

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```
