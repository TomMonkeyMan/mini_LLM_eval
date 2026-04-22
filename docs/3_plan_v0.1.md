# Mini LLM Eval 实现计划

## 阶段概览

```
阶段 1: 基础设施     ──► 阶段 2: 核心模块     ──► 阶段 3: 服务层
   │                        │                        │
   ├─ 项目结构               ├─ Provider              ├─ RunService
   ├─ 配置系统               ├─ Evaluator             ├─ Executor
   ├─ 日志系统               ├─ 数据模型              ├─ Aggregator
   └─ 数据库                 └─ 注册机制              └─ Comparator
                                    │
                                    ▼
                            阶段 4: 接口层     ──► 阶段 5: 测试与文档
                                    │                   │
                                    ├─ CLI              ├─ 单元测试
                                    ├─ FastAPI          ├─ 集成测试
                                    └─ 报告生成         └─ 示例输出

```

---

## 阶段 1: 基础设施

### 1.1 项目结构初始化

```
mini_llm_eval/
├── src/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── exceptions.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schemas.py
│   │   └── db_models.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py
│   │   └── repository.py
│   ├── providers/
│   │   └── __init__.py
│   ├── evaluators/
│   │   └── __init__.py
│   ├── services/
│   │   └── __init__.py
│   ├── api/
│   │   └── __init__.py
│   └── cli/
│       └── __init__.py
├── data/
├── outputs/
├── tests/
│   └── conftest.py
├── config.yaml
└── requirements.txt
```

**任务清单**:
- [ ] 创建目录结构
- [ ] 创建 requirements.txt
- [ ] 创建 config.yaml 模板

### 1.2 配置系统

```python
# src/core/config.py
# 功能：
# - 加载 config.yaml
# - 支持环境变量覆盖 ${ENV_VAR}
# - Pydantic 校验配置结构
```

**任务清单**:
- [ ] 定义 Config Pydantic 模型
- [ ] 实现 YAML 加载
- [ ] 实现环境变量替换
- [ ] 单例模式获取配置

### 1.3 日志系统

```python
# src/core/logging.py
# 功能：
# - structlog 配置
# - 开发环境：彩色控制台
# - 生产环境：JSON 格式
# - 上下文绑定（run_id 等）
```

**任务清单**:
- [ ] 安装 structlog
- [ ] 实现 setup_logging()
- [ ] 实现 get_logger()
- [ ] 测试 JSON 输出格式

### 1.4 异常定义

```python
# src/core/exceptions.py
# 定义所有自定义异常
```

**任务清单**:
- [ ] EvalRunnerException (基类)
- [ ] DatasetLoadError
- [ ] InvalidCaseError
- [ ] ProviderError
- [ ] ProviderTimeoutError
- [ ] EvaluatorError
- [ ] InvalidTransitionError

### 1.5 数据库层

```python
# src/db/database.py
# 功能：
# - SQLite 连接管理
# - 表创建
# - 异步支持 (aiosqlite)
```

**任务清单**:
- [ ] 安装 aiosqlite, SQLAlchemy
- [ ] 定义表结构 (runs, case_results, state_logs, run_metrics)
- [ ] 实现 Database 类
- [ ] 实现 init_db() 创建表
- [ ] 实现基本 CRUD 操作

**验收标准**:
```bash
# 能够运行
python -c "from src.db.database import Database; import asyncio; asyncio.run(Database(':memory:').init())"
```

---

## 阶段 2: 核心模块

### 2.1 数据模型

```python
# src/models/schemas.py
# Pydantic 模型，用于 API 和内部传递
```

**任务清单**:
- [ ] EvalCase
- [ ] ProviderResponse
- [ ] EvalResult
- [ ] CaseResult
- [ ] RunConfig
- [ ] RunSummary
- [ ] RunResult
- [ ] CompareResult

### 2.2 Provider 基础架构

```python
# src/providers/base.py      - 基类
# src/providers/registry.py  - 注册机制
# src/providers/mock.py      - Mock 实现
```

**任务清单**:
- [ ] BaseProvider 抽象类
- [ ] ProviderRegistry 注册器
- [ ] @ProviderRegistry.register 装饰器
- [ ] MockProvider 实现
  - [ ] 映射文件加载
  - [ ] 随机 fallback (80% 正确)
  - [ ] 可配置延迟
- [ ] 自动发现机制

**验收标准**:
```python
provider = ProviderRegistry.get("mock-v1")
response = await provider.generate("测试问题")
assert response.status == "success"
assert response.latency_ms > 0
```

### 2.3 Evaluator 基础架构

```python
# src/evaluators/base.py      - 基类
# src/evaluators/registry.py  - 注册机制
# src/evaluators/exact_match.py
# src/evaluators/contains.py
# src/evaluators/regex_match.py
# src/evaluators/json_field.py
```

**任务清单**:
- [ ] BaseEvaluator 抽象类
- [ ] EvaluatorRegistry 注册器
- [ ] @EvaluatorRegistry.register 装饰器
- [ ] ExactMatchEvaluator
- [ ] ContainsEvaluator (支持 | 分隔多关键词)
- [ ] RegexMatchEvaluator
- [ ] JsonFieldEvaluator
- [ ] 自动发现机制

**验收标准**:
```python
evaluator = EvaluatorRegistry.get("contains")
result = evaluator.evaluate("答案包含关键词ABC", "ABC")
assert result.passed == True
```

### 2.4 数据集加载器

```python
# src/services/dataset_loader.py
# 功能：加载 JSONL/JSON/CSV 格式的评测集
```

**任务清单**:
- [ ] 支持 JSONL 格式
- [ ] 支持 JSON 格式
- [ ] 支持 CSV 格式
- [ ] 数据校验 (Pydantic)
- [ ] 错误处理 (跳过无效行，记录日志)

---

## 阶段 3: 服务层

### 3.1 状态机

```python
# src/services/state_machine.py
# 状态流转：PENDING → RUNNING → SUCCEEDED/FAILED/CANCELLED
```

**任务清单**:
- [ ] RunStatus 枚举
- [ ] RunStateMachine 类
- [ ] transition() 方法
- [ ] 状态变更日志记录

### 3.2 任务执行器

```python
# src/services/executor.py
# 异步执行评测任务
```

**任务清单**:
- [ ] TaskExecutor 类
- [ ] asyncio.Semaphore 并发控制
- [ ] 单 case 执行 (带超时、重试)
- [ ] 批量 case 并发执行
- [ ] 错误隔离 (单 case 失败不影响整体)
- [ ] 进度回调

**关键代码结构**:
```python
class TaskExecutor:
    async def execute_run(self, run_id: str, cases: List[EvalCase]) -> List[CaseResult]:
        semaphore = asyncio.Semaphore(self.concurrency)
        tasks = [self._execute_case_safe(case, semaphore) for case in cases]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results
```

### 3.3 指标聚合器

```python
# src/services/aggregator.py
# 计算通过率、延迟分位数、按 tag 聚合
```

**任务清单**:
- [ ] 计算总通过率
- [ ] 计算 avg/p50/p95/p99 延迟
- [ ] 按 tag 聚合通过率
- [ ] 错误类型分布统计
- [ ] 生成 RunSummary

### 3.4 结果对比器

```python
# src/services/comparator.py
# 对比两次评测结果
```

**任务清单**:
- [ ] 通过率变化计算
- [ ] 按 tag 通过率变化
- [ ] 识别新增失败 case
- [ ] 识别修复成功 case
- [ ] 延迟变化统计
- [ ] 生成 CompareResult

### 3.5 RunService (主服务)

```python
# src/services/run_service.py
# 编排整个评测流程
```

**任务清单**:
- [ ] create_run() - 创建任务
- [ ] execute_run() - 执行任务
- [ ] get_run() - 查询任务
- [ ] get_run_cases() - 查询 case 结果
- [ ] cancel_run() - 取消任务
- [ ] wait_for_run() - 等待完成

**流程编排**:
```
create_run()
    │
    ├─► 保存到数据库 (status=PENDING)
    ├─► 记录状态日志
    └─► 返回 run_id

execute_run()
    │
    ├─► 状态转换 PENDING → RUNNING
    ├─► 加载数据集
    ├─► 获取 Provider 和 Evaluator
    ├─► TaskExecutor 执行所有 case
    ├─► 保存 case 结果到数据库
    ├─► Aggregator 计算指标
    ├─► 保存指标到数据库
    └─► 状态转换 RUNNING → SUCCEEDED/FAILED
```

---

## 阶段 4: 接口层

### 4.1 CLI

```python
# src/cli/main.py
# src/cli/commands/run.py
# src/cli/commands/compare.py
# src/cli/commands/list.py
```

**任务清单**:
- [ ] 安装 typer, rich
- [ ] `run` 命令 - 执行评测
- [ ] `compare` 命令 - 对比结果
- [ ] `list` 命令 - 列出历史运行
- [ ] `show` 命令 - 查看单次运行详情
- [ ] 进度条显示
- [ ] 彩色输出

**CLI 接口设计**:
```bash
# 执行评测
python -m src.cli.main run \
  --dataset data/eval_cases.jsonl \
  --provider mock-v1 \
  --concurrency 4 \
  --timeout 30000

# 对比结果
python -m src.cli.main compare \
  --base run_xxx \
  --candidate run_yyy \
  --format markdown

# 列出历史
python -m src.cli.main list --limit 10

# 查看详情
python -m src.cli.main show run_xxx --cases --failed-only
```

### 4.2 FastAPI

```python
# src/api/main.py
# src/api/routes/runs.py
# src/api/routes/compare.py
# src/api/deps.py
```

**任务清单**:
- [ ] FastAPI 应用初始化
- [ ] 依赖注入 (Database, Services)
- [ ] POST /runs - 创建评测
- [ ] GET /runs - 列出评测
- [ ] GET /runs/{id} - 查询状态
- [ ] GET /runs/{id}/cases - 查询 case 结果
- [ ] POST /runs/{id}/cancel - 取消
- [ ] POST /compare - 对比
- [ ] GET /providers - 列出 providers
- [ ] GET /evaluators - 列出 evaluators
- [ ] 错误处理中间件
- [ ] 请求日志中间件

### 4.3 报告生成

```python
# src/services/reporter.py
# 生成 JSON 和 Markdown 报告
```

**任务清单**:
- [ ] JSON 报告生成
- [ ] Markdown 报告生成
- [ ] 对比报告 (JSON)
- [ ] 对比报告 (Markdown)
- [ ] 保存到 outputs/ 目录

**Markdown 报告示例**:
```markdown
# 评测报告: run_abc123

## 概览
| 指标 | 值 |
|------|-----|
| 通过率 | 85.0% |
| 总用例 | 20 |
| 通过 | 17 |
| 失败 | 3 |

## 按 Tag 统计
| Tag | 通过率 | 数量 |
|-----|--------|------|
| knowledge | 90% | 10 |
| extraction | 80% | 10 |

## 失败用例
| Case ID | 预期 | 实际 | 原因 |
|---------|------|------|------|
| case_003 | ... | ... | ... |
```

---

## 阶段 5: 测试与文档

### 5.1 单元测试

```
tests/
├── conftest.py              # fixtures
├── test_providers/
│   ├── test_mock.py
│   └── test_registry.py
├── test_evaluators/
│   ├── test_exact_match.py
│   ├── test_contains.py
│   └── test_registry.py
├── test_services/
│   ├── test_executor.py
│   ├── test_aggregator.py
│   └── test_comparator.py
└── test_api/
    └── test_runs.py
```

**任务清单**:
- [ ] conftest.py fixtures (db, provider, evaluator)
- [ ] Provider 测试 (至少 3 个)
- [ ] Evaluator 测试 (每种至少 2 个)
- [ ] Executor 测试 (并发、超时、重试)
- [ ] Aggregator 测试
- [ ] Comparator 测试
- [ ] API 测试 (httpx TestClient)

### 5.2 集成测试

**任务清单**:
- [ ] 完整评测流程测试
- [ ] CLI 端到端测试
- [ ] API 端到端测试

### 5.3 示例输出

**任务清单**:
- [ ] 生成 outputs/run_001.json
- [ ] 生成 outputs/run_002.json
- [ ] 生成对比报告 outputs/compare_001_002.md

### 5.4 文档完善

**任务清单**:
- [ ] README.md 完善
- [ ] API 文档 (FastAPI 自动生成)
- [ ] 使用示例

---

## 依赖关系图

```
阶段 1.1 项目结构
    │
    ├──► 1.2 配置系统
    │        │
    ├──► 1.3 日志系统
    │        │
    ├──► 1.4 异常定义
    │        │
    └──► 1.5 数据库
             │
             ▼
        阶段 2.1 数据模型
             │
      ┌──────┴──────┐
      ▼             ▼
  2.2 Provider   2.3 Evaluator
      │             │
      └──────┬──────┘
             │
             ▼
        2.4 数据集加载器
             │
             ▼
        阶段 3.1 状态机
             │
             ▼
        3.2 执行器
             │
      ┌──────┴──────┐
      ▼             ▼
  3.3 聚合器    3.4 对比器
      │             │
      └──────┬──────┘
             │
             ▼
        3.5 RunService
             │
      ┌──────┴──────┐
      ▼             ▼
  4.1 CLI       4.2 API
      │             │
      └──────┬──────┘
             │
             ▼
        4.3 报告生成
             │
             ▼
        阶段 5 测试与文档
```

---

## 验收标准

### 最小可运行版本 (MVP)

1. **CLI 能跑通**:
```bash
python -m src.cli.main run --dataset data/eval_cases.jsonl --provider mock-v1
# 输出: 通过率、延迟、失败 case 列表
```

2. **API 能跑通**:
```bash
uvicorn src.api.main:app
curl -X POST http://localhost:8000/runs -d '{"dataset_path": "data/eval_cases.jsonl", "provider_name": "mock-v1"}'
```

3. **对比能跑通**:
```bash
python -m src.cli.main compare --base run_001 --candidate run_002
# 输出: 通过率变化、新增失败、修复成功
```

4. **测试通过**:
```bash
pytest tests/ -v
# 至少 3 个测试文件，覆盖核心模块
```

### 完整版本

- [ ] 所有 6 种异常处理实现
- [ ] 状态机日志完整
- [ ] Markdown 报告美观
- [ ] 至少 20 条测试用例
- [ ] 2 份示例输出用于对比展示

---

## 建议实现顺序

```
Day 1-2: 阶段 1 (基础设施)
         ├─ 项目结构、配置、日志、异常、数据库
         └─ 验证: 数据库初始化成功

Day 2-3: 阶段 2 (核心模块)
         ├─ 数据模型、Provider、Evaluator
         └─ 验证: Mock Provider 和 Evaluator 可用

Day 3-4: 阶段 3 (服务层)
         ├─ 状态机、执行器、聚合器、对比器、RunService
         └─ 验证: 完整评测流程可运行

Day 4-5: 阶段 4 (接口层)
         ├─ CLI、API、报告生成
         └─ 验证: CLI 和 API 都能用

Day 5-6: 阶段 5 (测试与文档)
         ├─ 单元测试、集成测试、示例输出
         └─ 验证: pytest 全部通过

Day 7: 收尾
       ├─ 文档完善
       ├─ 代码清理
       └─ 最终验收
```

---

## 风险与备选方案

| 风险 | 影响 | 备选方案 |
|------|------|----------|
| asyncio 复杂度高 | 实现变慢 | 先用同步版本，后续改 async |
| SQLAlchemy async 坑多 | 调试耗时 | 直接用 aiosqlite 原生 SQL |
| 时间不够 | 功能缺失 | 砍 API，只保留 CLI |

**优先级排序**:
1. CLI 可用 (必须)
2. Mock Provider (必须)
3. 3 种 Evaluator (必须)
4. 指标聚合 (必须)
5. 对比功能 (必须)
6. API (高优先)
7. 状态机日志 (中优先)
8. Markdown 报告 (中优先)
9. 完整测试覆盖 (低优先)
