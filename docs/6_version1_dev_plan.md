# Mini LLM Eval v1 开发计划

> 本文档是 v1 版本的实施计划，聚焦核心功能，报表层后续迭代。
>
> 设计参考：`5_critical_design.md`, `3.2_design_decisions.md`, `raw_requirement.txt`

---

## 目标范围

### 包含（v1 核心）
- 加载评测数据集
- Provider 调用（mock + openai_compatible）
- Evaluator 执行（5 种规则类）
- 异步并发执行
- 结果持久化（SQLite + 文件）
- 断点恢复
- CLI 入口

### 不包含（后续迭代）
- HTTP API（FastAPI 封装）
- 实验对比报表
- LLM Judge evaluator
- 缓存
- Web UI

---

## Phase 1: 项目结构和基础配置

### 目标
搭建项目骨架，配置加载机制。

### 参考
- `5_critical_design.md` §4.4 配置管理
- `2_design_v0.1.md` §14 目录结构

### 任务

```
mini_llm_eval/                  # 项目根目录 (git repo)
├── src/
│   └── mini_llm_eval/          # Python 包 (src layout)
│       ├── __init__.py         # from mini_llm_eval import xxx
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py       # 配置加载
│       │   └── exceptions.py   # 异常定义
│       ├── models/
│       │   ├── __init__.py
│       │   └── schemas.py      # Pydantic 数据模型
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── factory.py
│       │   ├── mock.py
│       │   └── openai_compatible.py
│       ├── evaluators/
│       │   ├── __init__.py
│       │   ├── registry.py
│       │   ├── base.py
│       │   └── ...             # 各 evaluator
│       ├── services/
│       │   ├── __init__.py
│       │   ├── dataset.py
│       │   ├── executor.py
│       │   └── run_service.py
│       ├── db/
│       │   ├── __init__.py
│       │   ├── database.py
│       │   └── file_storage.py
│       └── cli/
│           ├── __init__.py
│           └── main.py
├── tests/                      # 测试
│   └── __init__.py
├── data/                       # 评测数据集
│   └── eval_cases.jsonl
├── outputs/                    # 运行输出
│   └── .gitkeep
├── demo/                       # 示例脚本
│   └── .gitkeep
├── docs/                       # 文档
│   └── design.md
├── config.yaml                 # 项目级配置（示例）
├── providers.yaml              # Provider 配置（示例）
├── pyproject.toml              # 打包配置
└── README.md
```

### 打包配置 (`pyproject.toml`)

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mini-llm-eval"
version = "0.1.0"
description = "Mini LLM Evaluation Framework"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.0",
    "httpx>=0.25",
    "aiosqlite>=0.19",
    "typer>=0.9",
    "rich>=13.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
]

[project.scripts]
mini-llm-eval = "mini_llm_eval.cli.main:app"

[tool.hatch.build.targets.sdist]
include = ["src/mini_llm_eval"]

[tool.hatch.build.targets.wheel]
packages = ["src/mini_llm_eval"]
```

### 开发安装

```bash
# 开发模式安装（editable）
pip install -e .

# 然后就可以
from mini_llm_eval.evaluators import registry
from mini_llm_eval.providers import create_provider

# CLI
mini-llm-eval run --dataset data/cases.jsonl --provider qwen
```

### 1.1 配置加载 (`src/mini_llm_eval/core/config.py`)

```python
# 配置文件查找顺序：--config > ./config.yaml > ~/.mini_llm_eval/config.yaml
# 参考：5_critical_design.md §4.4

from pydantic import BaseModel
from typing import List, Optional
import yaml
import os

class Config(BaseModel):
    timeout_ms: int = 30000
    max_retries: int = 3
    concurrency: int = 4
    output_dir: str = "./outputs"
    evaluators_package: str = "mini_llm_eval.evaluators"  # 可配置，非写死
    defaults: dict = {"evaluators": ["contains"]}

class ProviderConfig(BaseModel):
    type: str  # mock | openai_compatible
    base_url: Optional[str] = None
    model: Optional[str] = None
    # api_key 从环境变量读取，不在配置文件中

def load_config(config_path: str = None) -> Config:
    """加载配置，支持环境变量模板 ${VAR}"""
    pass

def load_providers(providers_path: str = None) -> dict[str, ProviderConfig]:
    """加载 Provider 配置"""
    pass
```

### 1.2 异常定义 (`src/mini_llm_eval/core/exceptions.py`)

```python
# 参考：5_critical_design.md §4.2 错误处理架构
# 参考：2_design_v0.1.md §12.1 异常类型定义

class EvalRunnerException(Exception):
    """基础异常类"""
    pass

class DatasetLoadError(EvalRunnerException):
    """数据集加载失败 - FATAL"""
    pass

class ProviderInitError(EvalRunnerException):
    """Provider 初始化失败 - FATAL"""
    pass

class ProviderError(EvalRunnerException):
    """Provider 调用失败 - 可重试"""
    pass

class EvaluatorError(EvalRunnerException):
    """Evaluator 执行失败 - 记录但不中断"""
    pass
```

### 验收标准
- [ ] `load_config()` 能正确加载 config.yaml
- [ ] `load_providers()` 能正确加载 providers.yaml
- [ ] 环境变量模板 `${VAR}` 能正确替换
- [ ] 配置文件不存在时使用默认值

---

## Phase 2: 数据模型

### 目标
定义核心数据结构，使用 Pydantic v2。

### 参考
- `3.2_design_decisions.md` §P0-1 ProviderResponse
- `3.2_design_decisions.md` §P0-2 EvalResult, EvalCase, CaseResult
- `5_critical_design.md` §4.3 存储设计（表结构）
- `raw_requirement.txt` 评测数据集字段

### 任务

### 2.1 数据模型 (`src/mini_llm_eval/models/schemas.py`)

```python
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum

# === Provider 相关 ===

class ProviderStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"

class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ProviderResponse(BaseModel):
    """Provider 返回结构 - 参考 3.2 §P0-1"""
    output: str
    latency_ms: float
    status: ProviderStatus
    error: Optional[str] = None
    token_usage: Optional[TokenUsage] = None
    cost: Optional[float] = None
    model_name: Optional[str] = None
    request_id: Optional[str] = None

# === Evaluator 相关 ===

class EvalResult(BaseModel):
    """Evaluator 返回结构 - 参考 3.2 §P0-2（已更新：无 score）"""
    passed: bool
    reason: str
    evaluator_type: str
    details: Optional[dict] = None
    error: Optional[str] = None  # evaluator 执行出错时记录

# === Case 相关 ===

class EvalCase(BaseModel):
    """评测用例 - 参考 raw_requirement.txt"""
    case_id: str
    query: str
    expected_answer: str
    tags: List[str] = []
    difficulty: str = "medium"  # easy | medium | hard
    eval_types: List[str] = ["contains"]  # 支持多个，独立执行
    metadata: dict = {}

class CaseResult(BaseModel):
    """单条 case 结果 - 参考 5_critical_design.md §4.1"""
    case_id: str
    query: str
    expected: str
    actual_output: str
    output_path: Optional[str] = None  # 大文本存文件，DB 存路径

    # 每个 evaluator 独立结果，不合并
    eval_results: Dict[str, EvalResult] = {}

    # Provider 相关
    latency_ms: float
    provider_status: ProviderStatus
    error_message: Optional[str] = None
    retries: int = 0

    created_at: datetime = None

# === Run 相关 ===

class RunStatus(str, Enum):
    """Run 状态机 - 参考 raw_requirement 方向 A + 5_critical_design.md §4.3"""
    PENDING = "pending"       # 任务已创建，未开始
    RUNNING = "running"       # 执行中
    SUCCEEDED = "succeeded"   # 成功完成（部分 case 失败也算）
    FAILED = "failed"         # FATAL 错误导致整体失败
    CANCELLED = "cancelled"   # 用户取消/中断

class CaseStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    ERROR = "error"

class RunConfig(BaseModel):
    """运行配置 - 参考 raw_requirement.txt"""
    run_id: str
    dataset_path: str
    provider_name: str
    model_config: dict = {}
    concurrency: int = 4
    timeout_ms: int = 30000
    max_retries: int = 3
```

### 验收标准
- [ ] 所有 Model 能正确序列化/反序列化 JSON
- [ ] Enum 值与设计文档一致
- [ ] 字段类型与设计文档一致

---

## Phase 3: Provider 层

### 目标
实现 Provider 抽象和两个内置实现。

### 参考
- `5_critical_design.md` §5 Provider 设计（配置驱动）
- `3.2_design_decisions.md` §P0-1 Provider 接口设计
- `3.2_design_decisions.md` RETRY_CONFIG

### 任务

### 3.1 Provider 基类 (`src/mini_llm_eval/providers/base.py`)

```python
# 参考：3.2_design_decisions.md §P0-1

from abc import ABC, abstractmethod
from mini_llm_eval.models.schemas import ProviderResponse

class BaseProvider(ABC):
    @abstractmethod
    async def generate(self, query: str, **kwargs) -> ProviderResponse:
        """异步生成响应"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 唯一标识"""
        pass

    async def health_check(self) -> bool:
        """健康检查（可选）"""
        return True

    async def close(self) -> None:
        """清理资源（可选）"""
        pass
```

### 3.2 Provider 工厂 (`src/mini_llm_eval/providers/factory.py`)

```python
# 参考：5_critical_design.md §5.2 配置驱动

from mini_llm_eval.core.config import ProviderConfig

def create_provider(name: str, config: ProviderConfig) -> BaseProvider:
    """根据 type 创建 Provider 实例"""
    if config.type == "mock":
        from .mock import MockProvider
        return MockProvider(name, config)
    elif config.type == "openai_compatible":
        from .openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(name, config)
    else:
        raise ValueError(f"Unknown provider type: {config.type}")
```

### 3.3 Mock Provider (`src/mini_llm_eval/providers/mock.py`)

```python
# 参考：3.2_design_decisions.md Mock Provider 配置

class MockProvider(BaseProvider):
    """
    测试用 Provider，无需 API
    - 支持映射表匹配
    - 支持 fallback 默认响应
    - 模拟延迟
    """
    pass
```

### 3.4 OpenAI Compatible Provider (`src/mini_llm_eval/providers/openai_compatible.py`)

```python
# 参考：5_critical_design.md §5.3 内置 Provider 类型

import httpx

class OpenAICompatibleProvider(BaseProvider):
    """
    OpenAI 兼容 API（覆盖 Qwen、GPT、大部分模型）
    - base_url 可配置
    - api_key 从环境变量读取
    - 支持重试（指数退避）
    """
    pass
```

### 3.5 重试逻辑 (`src/mini_llm_eval/providers/retry.py`)

```python
# 参考：3.2_design_decisions.md RETRY_CONFIG

RETRY_CONFIG = {
    "max_retries": 3,
    "retry_delays": [1, 2, 4],  # 指数退避
    "retryable_errors": ["timeout", "connection_error", "rate_limit", "server_error"],
    "non_retryable_errors": ["bad_request", "unauthorized", "forbidden", "not_found"],
}

async def with_retry(func, max_retries: int = 3):
    """带重试的异步函数执行"""
    pass
```

### 验收标准
- [ ] MockProvider 能返回映射表中的响应
- [ ] MockProvider fallback 能随机返回
- [ ] OpenAICompatibleProvider 能调用真实 API（用 Qwen 测试）
- [ ] 重试逻辑正确（可重试错误重试，不可重试错误直接返回）

---

## Phase 4: Evaluator 层

### 目标
实现 Evaluator 注册机制和 5 个基础 Evaluator。

### 参考
- `5_critical_design.md` §1 Evaluator 插件机制（装饰器 + 自动发现）
- `5_critical_design.md` §3.2 MVP Evaluator 范围
- `3.2_design_decisions.md` §P0-2 Evaluator 接口

### 任务

### 4.1 注册机制 (`src/mini_llm_eval/evaluators/registry.py`)

```python
# 参考：5_critical_design.md §1.2 注册机制实现

from typing import Type, Dict
import importlib
import pkgutil

_EVALUATORS: Dict[str, Type['BaseEvaluator']] = {}

def register(name: str):
    """装饰器：注册 Evaluator"""
    def decorator(cls):
        _EVALUATORS[name] = cls
        return cls
    return decorator

def get(name: str) -> 'BaseEvaluator':
    """按名称获取 Evaluator 实例"""
    if name not in _EVALUATORS:
        raise ValueError(f"Unknown evaluator: {name}")
    return _EVALUATORS[name]()

def list_all() -> list[str]:
    """列出所有已注册的 Evaluator"""
    return list(_EVALUATORS.keys())

def auto_discover(package_name: str = None):
    """启动时自动发现并加载所有 Evaluator 模块"""
    # package_name 从配置读取，不写死
    pass
```

### 4.2 Evaluator 基类 (`src/mini_llm_eval/evaluators/base.py`)

```python
# 参考：3.2_design_decisions.md §P0-2 Evaluator 基类

from abc import ABC, abstractmethod
from mini_llm_eval.models.schemas import EvalResult

class BaseEvaluator(ABC):
    @abstractmethod
    def evaluate(
        self,
        output: str,
        expected: str,
        case_metadata: dict = None,
        config: dict = None
    ) -> EvalResult:
        """执行评估"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Evaluator 名称"""
        pass
```

### 4.3 实现 5 个基础 Evaluator

| Evaluator | 文件 | 说明 |
|-----------|------|------|
| `exact_match` | `src/mini_llm_eval/evaluators/exact_match.py` | 精确匹配 |
| `contains` | `src/mini_llm_eval/evaluators/contains.py` | 包含关键词（支持 `\|` 分隔多个） |
| `regex` | `src/mini_llm_eval/evaluators/regex.py` | 正则匹配 |
| `json_field` | `src/mini_llm_eval/evaluators/json_field.py` | JSON 字段匹配 |
| `numeric_tolerance` | `src/mini_llm_eval/evaluators/numeric_tolerance.py` | 数值容差（如 ±5%） |

每个 Evaluator 示例结构：

```python
# src/evaluators/contains.py
from .registry import register
from .base import BaseEvaluator
from mini_llm_eval.models.schemas import EvalResult

@register("contains")
class ContainsEvaluator(BaseEvaluator):
    @property
    def name(self) -> str:
        return "contains"

    def evaluate(self, output: str, expected: str,
                 case_metadata: dict = None, config: dict = None) -> EvalResult:
        # 支持多个关键词，用 | 分隔
        keywords = [k.strip() for k in expected.split("|")]
        matched = [k for k in keywords if k.lower() in output.lower()]
        passed = len(matched) > 0

        return EvalResult(
            passed=passed,
            reason=f"Matched {len(matched)}/{len(keywords)} keywords: {matched}",
            evaluator_type="contains"
        )
```

### 验收标准
- [ ] `@register` 装饰器能正确注册 Evaluator
- [ ] `auto_discover()` 能自动加载所有 Evaluator
- [ ] `list_all()` 返回所有已注册的名称
- [ ] 5 个 Evaluator 全部实现并通过单元测试

---

## Phase 5: 存储层

### 目标
实现 SQLite 持久化和文件存储。

### 参考
- `5_critical_design.md` §4.3 存储设计
- `2_design_v0.1.md` §8 SQLite 数据模型

### 任务

### 5.1 数据库管理 (`src/mini_llm_eval/db/database.py`)

```python
# 参考：5_critical_design.md §4.3 表结构 + 队列设计
# SQLite 表即队列，参考 Prefect/Temporal/Celery 模式

import aiosqlite

SCHEMA = """
-- runs 表（同时作为任务队列）
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    dataset_path TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    model_config JSON,
    status TEXT DEFAULT 'pending',  -- pending | running | succeeded | failed | cancelled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,           -- 开始执行时间
    finished_at TIMESTAMP,          -- 完成时间
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- case_results 表
CREATE TABLE IF NOT EXISTS case_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending | completed | error
    output_path TEXT,  -- 大文本存文件
    eval_results JSON,
    latency_ms REAL,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_case_results_run_id ON case_results(run_id);
CREATE INDEX IF NOT EXISTS idx_case_results_status ON case_results(status);
"""

class Database:
    async def init(self, db_path: str = "eval.db"):
        """初始化数据库"""
        pass

    # === 队列操作 ===

    async def create_run(self, run_config: RunConfig) -> str:
        """创建 run 记录，状态为 pending（入队）"""
        pass

    async def claim_pending_run(self) -> Optional[str]:
        """取出一个 pending 任务，更新为 running（出队）

        SQL: SELECT ... WHERE status='pending' ORDER BY created_at LIMIT 1
             UPDATE ... SET status='running', started_at=NOW()
        """
        pass

    async def complete_run(self, run_id: str, success: bool):
        """完成任务，更新为 succeeded 或 failed"""
        pass

    async def cancel_run(self, run_id: str):
        """取消任务，更新为 cancelled"""
        pass

    # === Case 结果操作 ===

    async def save_case_result(self, result: CaseResult):
        """保存单条 case 结果（实时写入）"""
        pass

    async def get_completed_cases(self, run_id: str) -> set[str]:
        """获取已完成的 case_id（断点恢复用）"""
        pass

    async def update_run_status(self, run_id: str, status: str):
        """更新 run 状态"""
        pass
```

### 5.2 文件存储 (`src/mini_llm_eval/db/file_storage.py`)

```python
# 参考：5_critical_design.md §4.3 大文本存储

class FileStorage:
    def __init__(self, output_dir: str = "./outputs"):
        self.output_dir = output_dir

    def save_output(self, run_id: str, case_id: str, content: str) -> str:
        """
        保存大文本到文件，返回文件路径
        结构：outputs/{run_id}/{case_id}_output.json
        """
        pass

    def read_output(self, path: str) -> str:
        """读取文件内容"""
        pass
```

### 5.3 写入失败降级 (`src/mini_llm_eval/db/fallback.py`)

```python
# 参考：5_critical_design.md §4.2 结果文件写入失败处理

import tempfile

def save_with_fallback(path: str, content: str) -> str:
    """
    尝试写入，失败则降级到 /tmp
    同时 stdout 告知用户
    """
    try:
        # 尝试原路径
        pass
    except Exception as e:
        # 降级到 /tmp
        fallback_path = tempfile.mktemp(suffix=".json")
        print(f"⚠️ 写入失败，已降级到: {fallback_path}")
        return fallback_path
```

### 验收标准
- [ ] 数据库表结构正确创建
- [ ] case 结果能实时写入
- [ ] 断点恢复能正确查询已完成的 case
- [ ] 大文本正确存储到文件
- [ ] 写入失败时正确降级到 /tmp

---

## Phase 6: Service 层（核心）

### 目标
实现核心执行逻辑。

### 参考
- `5_critical_design.md` §6 CLI + API 架构（Service Layer 为核心）
- `5_critical_design.md` §4.2 错误处理架构
- `2_design_v0.1.md` §6 并发模型设计

### 任务

### 6.1 数据集加载 (`src/mini_llm_eval/services/dataset.py`)

```python
# 参考：raw_requirement.txt 评测数据集格式

import json
from pathlib import Path
from mini_llm_eval.models.schemas import EvalCase

def load_dataset(path: str) -> list[EvalCase]:
    """
    加载 JSONL 数据集
    支持格式：.jsonl, .json
    """
    pass
```

### 6.2 执行引擎 (`src/mini_llm_eval/services/executor.py`)

```python
# 参考：2_design_v0.1.md §6.2 执行引擎设计
# 参考：5_critical_design.md §4.1 多 Evaluator 执行

import asyncio
from mini_llm_eval.models.schemas import EvalCase, CaseResult

class Executor:
    def __init__(self, concurrency: int = 4, timeout_ms: int = 30000):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout_ms = timeout_ms

    async def execute_case(
        self,
        case: EvalCase,
        provider: BaseProvider,
        evaluators: list[BaseEvaluator]
    ) -> CaseResult:
        """
        执行单个 case
        1. 调用 provider
        2. 对每个 evaluator 独立执行（不合并）
        3. 返回结果
        """
        async with self.semaphore:
            # provider 调用（带超时和重试）
            # evaluator 执行（每个独立，出错记录 trace）
            pass

    async def execute_batch(
        self,
        cases: list[EvalCase],
        provider: BaseProvider,
        evaluators: dict[str, BaseEvaluator],
        on_result: callable = None  # 实时回调，用于写入数据库
    ) -> list[CaseResult]:
        """
        批量执行，支持并发
        """
        pass
```

### 6.3 Run 服务 (`src/mini_llm_eval/services/run_service.py`)

```python
# 参考：5_critical_design.md §4.3 断点恢复

class RunService:
    def __init__(self, db: Database, file_storage: FileStorage):
        self.db = db
        self.file_storage = file_storage

    async def start_run(self, config: RunConfig) -> str:
        """
        启动评测
        1. 创建 run 记录
        2. 加载数据集
        3. 初始化 provider
        4. 加载 evaluators
        5. 执行
        6. 更新状态
        """
        pass

    async def resume_run(self, run_id: str) -> str:
        """
        断点恢复
        1. 查询已完成的 case
        2. 只执行未完成的
        """
        pass
```

### 验收标准
- [ ] 能正确加载 JSONL 数据集
- [ ] 并发执行正常（Semaphore 限制生效）
- [ ] 单条 case 失败不影响其他 case
- [ ] evaluator 出错时记录 trace
- [ ] 断点恢复正确跳过已完成的 case

---

## Phase 7: CLI 封装

### 目标
提供命令行入口。

### 参考
- `5_critical_design.md` §6 CLI + API 架构
- `raw_requirement.txt` CLI 使用示例

### 任务

### 7.1 CLI 入口 (`src/mini_llm_eval/cli/main.py`)

```python
# 参考：raw_requirement.txt CLI 示例
# python run_eval.py --dataset data/cases.jsonl --provider mock-v1 --concurrency 4

import typer
from rich.console import Console

app = typer.Typer()
console = Console()

@app.command()
def run(
    dataset: str = typer.Option(..., help="数据集路径"),
    provider: str = typer.Option(..., help="Provider 名称"),
    concurrency: int = typer.Option(4, help="并发数"),
    timeout: int = typer.Option(30000, help="超时毫秒"),
    run_id: str = typer.Option(None, help="指定 run_id"),
    config: str = typer.Option(None, help="配置文件路径"),
):
    """启动评测"""
    pass

@app.command()
def resume(
    run_id: str = typer.Argument(..., help="要恢复的 run_id"),
):
    """断点恢复"""
    pass

@app.command()
def status(
    run_id: str = typer.Argument(..., help="查询 run_id"),
):
    """查看运行状态"""
    pass

if __name__ == "__main__":
    app()
```

### 7.2 输出格式

```python
# 使用 rich 美化输出

# 进度条
# [████████████████████████████████████████] 100% 20/20

# 结果摘要
# ┌──────────────────────────────────────┐
# │ Run: run_20240422_abc123             │
# ├──────────────────────────────────────┤
# │ Total: 20  Passed: 18  Failed: 2     │
# │ Pass Rate: 90%                       │
# │ Avg Latency: 1234ms                  │
# └──────────────────────────────────────┘

# 错误高亮（用户侧错误）
# ⚠️ Case diag_003: Invalid eval_type 'unknown'
```

### 验收标准
- [ ] `python -m mini_llm_eval.cli.main run --dataset ... --provider ...` 能运行
- [ ] `python -m mini_llm_eval.cli.main resume <run_id>` 能恢复
- [ ] 进度条正常显示
- [ ] 错误高亮提示

---

## Phase 8: 测试

### 目标
基础测试覆盖。

### 任务

```
tests/
├── conftest.py           # fixtures
├── test_config.py        # 配置加载测试
├── test_providers/
│   ├── test_mock.py
│   └── test_openai.py
├── test_evaluators/
│   ├── test_registry.py
│   ├── test_exact_match.py
│   ├── test_contains.py
│   ├── test_regex.py
│   ├── test_json_field.py
│   └── test_numeric.py
├── test_services/
│   ├── test_dataset.py
│   ├── test_executor.py
│   └── test_run_service.py
└── test_db/
    ├── test_database.py
    └── test_file_storage.py
```

### 验收标准
- [ ] 核心模块测试覆盖 > 80%
- [ ] CI 能跑通所有测试

---

## 实施顺序

```
Week 1:
├── Phase 1: 项目结构和配置
├── Phase 2: 数据模型
└── Phase 4.1-4.2: Evaluator 注册机制 + 基类

Week 2:
├── Phase 4.3: 5 个 Evaluator
├── Phase 3: Provider 层
└── Phase 5: 存储层

Week 3:
├── Phase 6: Service 层
├── Phase 7: CLI
└── Phase 8: 测试
```

---

## 验收 Checklist

### 功能验收

- [ ] 无 API key 能用 mock provider 运行
- [ ] 用 Qwen 能跑真实评测
- [ ] 数据集 20 条 case 能正常执行
- [ ] 断点恢复正常
- [ ] 错误不会导致整体崩溃

### 代码质量

- [ ] 类型注解完整
- [ ] 异常处理完善
- [ ] 日志输出清晰
- [ ] 测试覆盖 > 80%

---

*文档版本: v1.0*
*创建时间: 2024-04-22*
*作者: tianyu + Claude*
