# Mini LLM Eval 设计文档
# 这个是 和 claude 商量出来的 第一个版本。没有做任何参考project，仅对于项目本身进行框架设计。可以进一步精简。-by tianyu

## 1. 项目背景

团队在做大模型微调、RAG、Agent 和工具调用系统。每次改模型、改 prompt、改工具链路之后，需要用一套固定评测集做回归，判断新版本是否真的更好、是否引入了异常、是否能上线。

## 2. 核心功能

- 提交一次评测任务
- 执行一批测试样例
- 调用模型或 mock 模型生成结果
- 用多种 evaluator 打分
- 聚合指标并生成报告
- 对比两次实验结果

## 3. 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            API Layer (FastAPI)                          │
│  POST /runs          - 创建评测任务                                      │
│  GET  /runs/{id}     - 查询任务状态和结果                                 │
│  GET  /runs/{id}/cases - 查询case级结果                                  │
│  POST /compare       - 对比两次运行                                      │
│  GET  /providers     - 列出可用providers                                 │
│  GET  /evaluators    - 列出可用evaluators                                │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────────┐
│                         Service Layer                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │ RunService   │  │ CompareService│  │ QueryService │                  │
│  │ 任务编排      │  │ 结果对比      │  │ 历史查询     │                  │
│  └──────┬───────┘  └──────────────┘  └──────────────┘                  │
│         │                                                               │
│  ┌──────▼────────────────────────────────────────────┐                 │
│  │              TaskExecutor (异步执行引擎)           │                 │
│  │  - asyncio.Queue 任务队列                         │                 │
│  │  - Semaphore 并发控制                             │                 │
│  │  - 状态机管理                                     │                 │
│  └──────┬───────────────────┬───────────────────────┘                 │
└─────────┼───────────────────┼───────────────────────────────────────────┘
          │                   │
┌─────────▼─────────┐ ┌───────▼───────────┐
│  Provider Layer   │ │  Evaluator Layer  │
│  (async IO)       │ │  (插件式)          │
├───────────────────┤ ├───────────────────┤
│ MockProvider      │ │ ExactMatch        │
│ OpenAIProvider    │ │ Contains          │
│ AnthropicProvider │ │ Regex             │
│ LocalLLMProvider  │ │ JsonField         │
└─────────┬─────────┘ │ LLMJudge (async)  │
          │           └───────────────────┘
          │
┌─────────▼───────────────────────────────────────────────────────────────┐
│                       Persistence Layer (SQLite)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐  │
│  │ runs        │  │ case_results│  │ state_logs  │  │ metrics       │  │
│  │ 评测任务     │  │ 单条结果    │  │ 状态变更    │  │ 聚合指标      │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## 4. 业界框架参考

| 框架 | 核心设计 | 借鉴点 |
|------|----------|--------|
| **OpenAI Evals** | `CompletionFn` + `Eval` 类 | 插件注册机制、YAML配置 |
| **promptfoo** | Provider + Assert + Output | 轻量、CLI友好、对比视图 |
| **Ragas** | Metrics + Dataset + LLM | 指标计算的抽象 |
| **MLflow** | Experiment → Run → Metrics | 实验跟踪、参数记录 |
| **Weights & Biases** | Run + Artifact + Table | 可视化、对比表格 |

## 5. 核心接口设计

### 5.1 Provider 接口

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class ProviderResponse:
    output: str
    latency_ms: float
    status: str           # "success" | "error" | "timeout"
    error: Optional[str] = None
    token_usage: Optional[dict] = None
    cost: Optional[float] = None

class BaseProvider(ABC):
    @abstractmethod
    async def generate(self, query: str, **kwargs) -> ProviderResponse:
        """异步生成响应"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名称"""
        pass
```

**设计要点**：
- 返回结构化响应，而不是裸字符串
- status 明确区分成功/失败/超时
- latency 在 provider 内部计量
- 支持异步调用

### 5.2 Evaluator 接口

```python
@dataclass
class EvalResult:
    passed: bool
    score: float          # 0.0 ~ 1.0
    reason: str           # 解释为什么pass/fail
    evaluator_type: str
    details: Optional[dict] = None

class BaseEvaluator(ABC):
    @abstractmethod
    def evaluate(self, output: str, expected: str, **kwargs) -> EvalResult:
        """执行评估"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Evaluator 名称"""
        pass
```

**设计要点**：
- `score` 支持部分得分（不只是0/1）
- `reason` 用于调试和报告
- `details` 存储额外信息

### 5.3 EvalCase 数据结构

```python
@dataclass
class EvalCase:
    case_id: str
    query: str
    expected_answer: str
    tags: List[str]
    difficulty: str       # easy | medium | hard
    eval_type: str        # 决定用哪个evaluator
    metadata: dict        # 额外信息如 locale, category 等
```

### 5.4 RunConfig 数据结构

```python
@dataclass
class RunConfig:
    run_id: str
    dataset_path: str
    provider_name: str
    model_config: dict    # 模型特定配置
    concurrency: int = 4
    timeout_ms: int = 30000
    max_retries: int = 3
```

### 5.5 CaseResult 数据结构

```python
@dataclass
class CaseResult:
    case_id: str
    query: str
    expected: str
    actual_output: str
    passed: bool
    score: float
    eval_type: str
    eval_reason: str
    latency_ms: float
    provider_status: str  # success | error | timeout
    error_message: Optional[str]
    retries: int
    created_at: datetime
```

### 5.6 RunResult 数据结构

```python
@dataclass
class RunSummary:
    total_cases: int
    passed_cases: int
    failed_cases: int
    error_cases: int
    pass_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    tag_metrics: Dict[str, TagMetric]  # 按tag聚合
    error_distribution: Dict[str, int] # 错误类型分布

@dataclass
class RunResult:
    run_id: str
    dataset_path: str
    provider_name: str
    status: str           # pending | running | succeeded | failed | cancelled
    started_at: datetime
    finished_at: datetime
    case_results: List[CaseResult]
    summary: RunSummary
```

## 6. 并发模型设计

### 6.1 分析

```
┌────────────────────────────────────────────────────────────┐
│                    并发模型分析                            │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  Provider 调用 LLM API                                     │
│  ├─ 特性: IO密集，等待网络响应                              │
│  ├─ 方案: asyncio + httpx  ✓                               │
│  └─ 并发数: 受API rate limit限制，需要Semaphore             │
│                                                            │
│  Evaluator 执行评分                                        │
│  ├─ exact_match, contains, regex: 微秒级，无需特殊处理      │
│  ├─ json_field_match: 毫秒级，无需特殊处理                  │
│  └─ llm_judge: 也是IO密集！也用asyncio                     │
│                                                            │
│  结论: 统一用 asyncio 即可                                  │
│  只有真正的CPU密集计算(如embedding相似度)才需要multiprocess  │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### 6.2 执行引擎设计

```python
class TaskExecutor:
    def __init__(self, concurrency: int = 10):
        self.queue = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(concurrency)
        self.running = False

    async def submit(self, task: EvalTask) -> str:
        """提交任务，返回 task_id"""
        await self.queue.put(task)
        return task.run_id

    async def execute_case(self, case: EvalCase, provider: BaseProvider,
                           evaluator: BaseEvaluator) -> CaseResult:
        """执行单个case，带重试和超时"""
        async with self.semaphore:  # 并发控制
            for retry in range(self.max_retries):
                try:
                    # 调用 provider
                    response = await asyncio.wait_for(
                        provider.generate(case.query),
                        timeout=self.timeout_ms / 1000
                    )

                    # 执行评估
                    eval_result = evaluator.evaluate(
                        response.output,
                        case.expected_answer
                    )

                    return CaseResult(
                        case_id=case.case_id,
                        passed=eval_result.passed,
                        # ... 其他字段
                    )
                except asyncio.TimeoutError:
                    if retry == self.max_retries - 1:
                        return CaseResult(
                            case_id=case.case_id,
                            provider_status="timeout",
                            error_message="Provider timeout"
                        )
                except Exception as e:
                    if retry == self.max_retries - 1:
                        return CaseResult(
                            case_id=case.case_id,
                            provider_status="error",
                            error_message=str(e)
                        )
```

## 7. 消息队列策略

### 7.1 阶段1（MVP）：内存队列

```python
# 用 asyncio.Queue 作为轻量任务队列
class TaskExecutor:
    def __init__(self, concurrency: int = 10):
        self.queue = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(concurrency)
```

### 7.2 阶段2：SQLite 作为任务队列（支持断点恢复）

```sql
-- 用数据库表模拟队列，支持断点恢复
CREATE TABLE task_queue (
    id INTEGER PRIMARY KEY,
    run_id TEXT,
    case_id TEXT,
    status TEXT,  -- pending, running, completed, failed
    payload JSON,
    created_at TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
```

### 7.3 阶段3（未来扩展）：真正的消息队列

如果需要分布式部署，再考虑 Redis/RabbitMQ/Celery。

## 8. SQLite 数据模型

```sql
-- 评测运行记录
CREATE TABLE runs (
    id TEXT PRIMARY KEY,           -- run_id (UUID)
    dataset_path TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    model_config JSON,
    concurrency INTEGER DEFAULT 1,
    timeout_ms INTEGER DEFAULT 30000,
    max_retries INTEGER DEFAULT 3,
    status TEXT DEFAULT 'pending', -- pending/running/succeeded/failed/cancelled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    error_message TEXT
);

-- 单条case结果
CREATE TABLE case_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    query TEXT,
    expected_answer TEXT,
    actual_output TEXT,
    passed BOOLEAN,
    score REAL,
    eval_type TEXT,
    eval_reason TEXT,
    latency_ms REAL,
    provider_status TEXT,          -- success/error/timeout
    error_message TEXT,
    retries INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

-- 状态变更日志（支持状态机方向A）
CREATE TABLE state_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    reason TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

-- 聚合指标
CREATE TABLE run_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    total_cases INTEGER,
    passed_cases INTEGER,
    failed_cases INTEGER,
    error_cases INTEGER,
    pass_rate REAL,
    avg_latency_ms REAL,
    p50_latency_ms REAL,
    p95_latency_ms REAL,
    p99_latency_ms REAL,
    tag_metrics JSON,             -- {"diagnostics": {"pass_rate": 0.8}, ...}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

-- 索引优化查询
CREATE INDEX idx_case_results_run_id ON case_results(run_id);
CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_runs_created_at ON runs(created_at);
```

## 9. 插件式 Evaluator 设计（开放方向B）

### 9.1 注册机制

```python
# src/evaluators/registry.py
from typing import Dict, Type
import importlib
import pkgutil

class EvaluatorRegistry:
    _evaluators: Dict[str, Type['BaseEvaluator']] = {}

    @classmethod
    def register(cls, name: str):
        """装饰器：注册evaluator"""
        def decorator(evaluator_cls: Type['BaseEvaluator']):
            cls._evaluators[name] = evaluator_cls
            return evaluator_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> 'BaseEvaluator':
        if name not in cls._evaluators:
            raise ValueError(f"Unknown evaluator: {name}")
        return cls._evaluators[name]()

    @classmethod
    def list_all(cls) -> list:
        return list(cls._evaluators.keys())

    @classmethod
    def auto_discover(cls, package_name: str = "src.evaluators"):
        """自动发现并加载所有evaluator模块"""
        package = importlib.import_module(package_name)
        for _, module_name, _ in pkgutil.iter_modules(package.__path__):
            importlib.import_module(f"{package_name}.{module_name}")
```

### 9.2 使用示例

```python
# src/evaluators/contains.py
from .registry import EvaluatorRegistry
from .base import BaseEvaluator, EvalResult

@EvaluatorRegistry.register("contains")
class ContainsEvaluator(BaseEvaluator):
    """检查输出是否包含期望答案"""

    @property
    def name(self) -> str:
        return "contains"

    def evaluate(self, output: str, expected: str, **kwargs) -> EvalResult:
        # 支持多个关键词，用 | 分隔
        keywords = [k.strip() for k in expected.split("|")]
        matched = [k for k in keywords if k.lower() in output.lower()]

        passed = len(matched) > 0
        score = len(matched) / len(keywords)

        return EvalResult(
            passed=passed,
            score=score,
            reason=f"Matched {len(matched)}/{len(keywords)} keywords: {matched}",
            evaluator_type="contains"
        )
```

**添加新 Evaluator 只需要：**
1. 创建新文件 `src/evaluators/my_new_eval.py`
2. 用 `@EvaluatorRegistry.register("my_new_eval")` 装饰
3. 不需要修改任何其他代码！

## 10. 状态机设计（开放方向A）

### 10.1 状态流转图

```
                    ┌──────────────┐
                    │   PENDING    │
                    └──────┬───────┘
                           │ start()
                           ▼
                    ┌──────────────┐
          ┌─────────│   RUNNING    │─────────┐
          │         └──────┬───────┘         │
          │                │                 │
          │ cancel()       │                 │ error
          ▼                ▼                 ▼
   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
   │  CANCELLED   │ │  SUCCEEDED   │ │    FAILED    │
   └──────────────┘ └──────────────┘ └──────────────┘
```

### 10.2 实现

```python
from enum import Enum
from typing import Optional

class RunStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

class RunStateMachine:
    TRANSITIONS = {
        RunStatus.PENDING: [RunStatus.RUNNING, RunStatus.CANCELLED],
        RunStatus.RUNNING: [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED],
        RunStatus.SUCCEEDED: [],
        RunStatus.FAILED: [],
        RunStatus.CANCELLED: [],
    }

    def __init__(self, run_id: str, db: Database):
        self.run_id = run_id
        self.db = db
        self.current_status = RunStatus.PENDING

    async def transition(self, to_status: RunStatus, reason: str = "") -> bool:
        """执行状态转换，记录日志"""
        if to_status not in self.TRANSITIONS[self.current_status]:
            raise InvalidTransitionError(
                f"Cannot transition from {self.current_status} to {to_status}"
            )

        from_status = self.current_status
        self.current_status = to_status

        # 记录状态变更日志
        await self.db.log_state_change(
            run_id=self.run_id,
            from_state=from_status.value,
            to_state=to_status.value,
            reason=reason
        )

        # 更新数据库
        await self.db.update_run_status(self.run_id, to_status.value)

        return True
```

## 11. API 设计

### 11.1 RESTful 接口

```python
# src/api/routes/runs.py
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Mini LLM Eval Runner")

class CreateRunRequest(BaseModel):
    dataset_path: str
    provider_name: str
    concurrency: int = 4
    timeout_ms: int = 30000
    max_retries: int = 3
    model_config: dict = {}

class RunResponse(BaseModel):
    run_id: str
    status: str
    message: str

@app.post("/runs", response_model=RunResponse)
async def create_run(req: CreateRunRequest, background_tasks: BackgroundTasks):
    """创建并启动一次评测"""
    run_id = generate_run_id()

    # 保存到数据库
    await db.create_run(run_id, req)

    # 后台执行
    background_tasks.add_task(execute_run, run_id)

    return RunResponse(
        run_id=run_id,
        status="pending",
        message="Run submitted successfully"
    )

@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    """查询评测任务状态和结果"""
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    if run.status in ["succeeded", "failed"]:
        metrics = await db.get_run_metrics(run_id)
        return {**run.dict(), "metrics": metrics}

    return run

@app.get("/runs/{run_id}/cases")
async def get_run_cases(
    run_id: str,
    passed: Optional[bool] = None,
    tag: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """查询case级结果，支持过滤和分页"""
    return await db.get_case_results(
        run_id, passed=passed, tag=tag, limit=limit, offset=offset
    )

@app.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """取消运行中的任务"""
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status != "running":
        raise HTTPException(400, "Can only cancel running tasks")

    await executor.cancel(run_id)
    return {"message": "Run cancelled"}

@app.post("/compare")
async def compare_runs(base_run_id: str, candidate_run_id: str):
    """对比两次评测结果"""
    return await compare_service.compare(base_run_id, candidate_run_id)

@app.get("/providers")
async def list_providers():
    """列出可用的provider"""
    return ProviderRegistry.list_all()

@app.get("/evaluators")
async def list_evaluators():
    """列出可用的evaluator"""
    return EvaluatorRegistry.list_all()
```

### 11.2 对比结果结构

```python
@dataclass
class CompareResult:
    base_run_id: str
    candidate_run_id: str

    # 总体变化
    pass_rate_change: float        # +0.05 表示提升5%
    avg_latency_change_ms: float

    # 按tag的变化
    tag_changes: Dict[str, TagChange]

    # case级变化
    new_failures: List[str]        # 之前pass现在fail的case_id
    new_passes: List[str]          # 之前fail现在pass的case_id
    still_failing: List[str]       # 两次都fail的case_id

    # 详细对比
    case_diffs: List[CaseDiff]     # 每个case的详细对比
```

## 12. 错误处理策略

### 12.1 异常类型定义

```python
# src/core/exceptions.py

class EvalRunnerException(Exception):
    """基础异常类"""
    pass

class DatasetLoadError(EvalRunnerException):
    """数据集加载失败"""
    pass

class InvalidCaseError(EvalRunnerException):
    """无效的评测case"""
    pass

class ProviderError(EvalRunnerException):
    """Provider调用失败"""
    pass

class ProviderTimeoutError(ProviderError):
    """Provider超时"""
    pass

class EvaluatorError(EvalRunnerException):
    """Evaluator执行失败"""
    pass

class InvalidTransitionError(EvalRunnerException):
    """无效的状态转换"""
    pass

class ResultWriteError(EvalRunnerException):
    """结果写入失败"""
    pass
```

### 12.2 处理策略

| 异常类型 | 处理策略 | 是否重试 |
|----------|----------|----------|
| 非法输入数据 | 跳过该case，记录error | 否 |
| Provider调用失败 | 重试N次，最后记录error | 是 |
| Provider超时 | 重试N次，最后记录timeout | 是 |
| Evaluator异常 | 捕获异常，记录error，不影响其他case | 否 |
| 单个case重试失败 | 记录最终状态，继续下一个case | - |
| 并发执行中的部分失败 | 收集所有结果，最终汇总 | - |
| 结果文件写入失败 | 重试写入，记录到日志 | 是 |

### 12.3 实现示例

```python
async def execute_case_safe(self, case: EvalCase) -> CaseResult:
    """安全执行单个case，捕获所有异常"""
    try:
        return await self.execute_case(case)
    except ProviderTimeoutError as e:
        return CaseResult(
            case_id=case.case_id,
            provider_status="timeout",
            error_message=str(e),
            passed=False
        )
    except ProviderError as e:
        return CaseResult(
            case_id=case.case_id,
            provider_status="error",
            error_message=str(e),
            passed=False
        )
    except EvaluatorError as e:
        return CaseResult(
            case_id=case.case_id,
            provider_status="success",
            eval_type="error",
            error_message=f"Evaluator error: {e}",
            passed=False
        )
    except Exception as e:
        # 未预期的异常
        logger.exception(f"Unexpected error for case {case.case_id}")
        return CaseResult(
            case_id=case.case_id,
            provider_status="error",
            error_message=f"Unexpected: {e}",
            passed=False
        )
```

## 13. 技术栈

```yaml
核心框架:
  - FastAPI: HTTP API
  - SQLAlchemy: ORM (async)
  - aiosqlite: 异步 SQLite
  - Pydantic: 数据校验

异步执行:
  - asyncio: 并发控制
  - httpx: 异步 HTTP 客户端

CLI工具:
  - typer: CLI 框架
  - rich: 美化输出

日志:
  - structlog: 结构化日志

测试:
  - pytest: 测试框架
  - pytest-asyncio: 异步测试
  - pytest-cov: 覆盖率

可选:
  - alembic: 数据库迁移
```

## 14. 目录结构

```
mini_llm_eval/
├── README.md
├── requirements.txt
├── config.yaml
├── alembic.ini                    # 数据库迁移配置
│
├── src/
│   ├── __init__.py
│   │
│   ├── api/                       # FastAPI 层
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI app
│   │   ├── routes/
│   │   │   ├── runs.py
│   │   │   ├── compare.py
│   │   │   └── admin.py
│   │   └── deps.py                # 依赖注入
│   │
│   ├── models/                    # 数据模型 (Pydantic + SQLAlchemy)
│   │   ├── __init__.py
│   │   ├── schemas.py             # Pydantic schemas (API)
│   │   └── db_models.py           # SQLAlchemy models (DB)
│   │
│   ├── providers/                 # Provider 插件
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── mock.py
│   │   ├── openai_provider.py
│   │   └── anthropic_provider.py
│   │
│   ├── evaluators/                # Evaluator 插件
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── exact_match.py
│   │   ├── contains.py
│   │   ├── regex_match.py
│   │   ├── json_field.py
│   │   └── llm_judge.py
│   │
│   ├── services/                  # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── run_service.py         # 评测任务管理
│   │   ├── executor.py            # 异步执行引擎
│   │   ├── state_machine.py       # 状态机
│   │   ├── aggregator.py          # 指标聚合
│   │   └── comparator.py          # 结果对比
│   │
│   ├── db/                        # 数据库层
│   │   ├── __init__.py
│   │   ├── database.py            # SQLite 连接
│   │   ├── repository.py          # CRUD 操作
│   │   └── migrations/            # 数据库迁移
│   │
│   ├── core/                      # 核心配置
│   │   ├── __init__.py
│   │   ├── config.py              # 配置加载
│   │   ├── exceptions.py          # 自定义异常
│   │   └── logging.py             # 日志配置
│   │
│   └── cli/                       # 命令行接口
│       ├── __init__.py
│       ├── main.py                # CLI 入口
│       ├── run_eval.py
│       └── compare_runs.py
│
├── data/
│   └── eval_cases.jsonl           # 评测数据集
│
├── outputs/                       # 输出目录
│   └── .gitkeep
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # pytest fixtures
│   ├── test_providers/
│   ├── test_evaluators/
│   ├── test_services/
│   └── test_api/
│
├── scripts/
│   ├── init_db.py                 # 初始化数据库
│   └── seed_data.py               # 填充示例数据
│
└── docs/
    ├── design.md                  # 本文档
    ├── api.md                     # API 文档
    └── architecture.png
```

## 15. 开放方向选择

本项目选择实现以下开放方向：

### A. 任务状态机 ✓
- 实现 PENDING → RUNNING → SUCCEEDED/FAILED/CANCELLED 状态流转
- 记录状态变化日志到 state_logs 表
- 支持任务取消

### B. 插件式 Evaluator ✓
- 使用装饰器注册机制
- 自动发现 evaluator 模块
- 新增 evaluator 无需修改主流程

### E. 并发与限流 ✓
- asyncio + Semaphore 实现并发控制
- 支持配置 provider 级并发上限
- 支持全局并发数限制

## 16. 关键 Tradeoff

| 决策 | 选择 | 理由 |
|------|------|------|
| 数据库 | SQLite | 轻量、无需额外服务、适合单机部署 |
| 并发模型 | asyncio | IO密集型场景，比多线程更高效 |
| 消息队列 | 内存队列+SQLite | MVP阶段够用，避免过度设计 |
| API框架 | FastAPI | 原生async、自动文档、类型友好 |
| 配置管理 | YAML + 环境变量 | 灵活且易于管理 |

## 16.1 实现决策记录

| # | 问题 | 决策 | 理由 |
|---|------|------|------|
| 1 | 评测数据集 | 用户自行准备 | 贴近实际业务场景 |
| 2 | Mock Provider 行为 | 映射 + 随机 fallback | 有映射用映射，没有则随机(80%正确/20%错误) |
| 3 | 配置管理 | 单一 config.yaml | MVP 简单优先 |
| 4 | API 认证 | 不实现 | MVP 阶段不需要 |
| 5 | 对比报告格式 | JSON + Markdown | 机器友好 + 人类友好 |
| 6 | CLI vs API 架构 | Service 层独立 | CLI 和 API 都调用 Service，CLI 可独立运行 |
| 7 | 测试数据隔离 | pytest tmp_path | 临时文件，方便调试 |

### CLI 与 API 架构说明

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   CLI ─────────────┐                                    │
│   (typer)          │                                    │
│                    ▼                                    │
│              ┌──────────┐                               │
│              │ Service  │  ◄─── 核心业务逻辑            │
│              │  Layer   │       纯 Python 函数/类       │
│              └──────────┘                               │
│                    ▲                                    │
│                    │                                    │
│   FastAPI ─────────┘                                    │
│   (HTTP API)                                            │
│                                                         │
└─────────────────────────────────────────────────────────┘

使用方式：
1. CLI 直接运行（不需要启动 HTTP 服务）
   python -m src.cli.main run --dataset data/eval.jsonl --provider mock-v1

2. HTTP API 方式
   uvicorn src.api.main:app --reload
   curl -X POST http://localhost:8000/runs -d '{...}'
```

## 17. 日志系统设计

### 17.1 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Application Code                         │
│   logger.info("eval_started", run_id="xxx", cases=20)          │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         structlog                               │
│   - 添加时间戳、level、logger name                               │
│   - 绑定上下文（run_id, request_id）                            │
│   - 格式化为 JSON                                               │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    标准 logging 后端                             │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│   │ Console     │  │ File        │  │ Remote      │            │
│   │ (开发环境)   │  │ (生产环境)   │  │ (Splunk)    │            │
│   └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

### 17.2 技术选型

选择 **structlog + 标准 logging 后端**：
- 原生支持结构化日志
- JSON 输出对 Splunk 友好
- 支持上下文绑定（run_id 自动附加到后续日志）
- 兼容标准 logging 生态

### 17.3 日志分类

| 日志类型 | 内容 | 文件 |
|----------|------|------|
| app | 应用日志：业务逻辑、评测过程 | app.log |
| access | 访问日志：HTTP 请求、响应 | access.log |
| audit | 审计日志：状态变更、敏感操作 | audit.log |

### 17.4 标准字段规范

```python
STANDARD_FIELDS = {
    "run_id": "评测运行ID",
    "case_id": "测试用例ID",
    "provider": "模型provider名",
    "evaluator": "评估器名",
    "latency_ms": "延迟毫秒",
    "status": "状态",
    "error": "错误信息",
    "trace_id": "链路追踪ID",
}
```

### 17.5 输出格式

**开发环境（彩色控制台）**：
```
2024-01-15 10:30:00 [info] eval_started run_id=run_abc123 total_cases=20
```

**生产环境（JSON，Splunk 友好）**：
```json
{"event": "eval_started", "run_id": "run_abc123", "total_cases": 20, "level": "info", "timestamp": "2024-01-15T10:30:00.000Z"}
```

### 17.6 Splunk 接入路径

- **阶段1**：写 JSON 文件，Splunk Forwarder 采集
- **阶段2**：直接用 Splunk HEC (HTTP Event Collector) 推送

## 18. 后续扩展方向

1. **分布式执行**: 引入 Celery + Redis
2. **Web UI**: 评测结果可视化
3. **Webhook 通知**: 任务完成后通知
4. **自定义指标**: 支持用户定义聚合逻辑
5. **A/B 测试**: 同时对比多个 provider
6. **版本管理**: 评测集版本控制
