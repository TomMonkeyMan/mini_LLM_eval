# Mini LLM Eval v2 设计 - 队列解耦架构

> 版本: v2.0 Draft
> 作者: tianyu + Claude
> 创建时间: 2026-04-26
> 基于: v1 MVP 完成后的演进设计

---

## 1. 设计目标

### 1.1 核心目标

| 目标 | 说明 |
|------|------|
| **Provider/Evaluator 解耦** | 通过队列实现真正的解耦，独立扩展 |
| **支持 LLM Judge** | Evaluator 也能调用模型，需要独立并发控制 |
| **流水线并行** | Provider 完成一个 case 后，Evaluator 立即处理，同时 Provider 处理下一个 |
| **更好的容错** | 某个环节失败不影响其他环节 |

### 1.2 设计原则

- **Provider**: 用户写（Plugin 即插即拔）
- **Evaluator**: 产品工程师写，用户选择 + 配置
- **队列**: 内存队列（v2），可选持久化队列（v3）

---

## 2. 架构总览

### 2.1 v1 vs v2 对比

**v1 架构（当前）- 同一 task 内串行**：

```
┌─────────────────────────────────────────────────────┐
│                    Single Task                       │
│  case -> provider.generate() -> evaluator.evaluate() │
│                                           -> result  │
└─────────────────────────────────────────────────────┘
```

**v2 架构 - 队列解耦流水线**：

```
┌──────────┐    ┌──────────────────┐    ┌───────────────────┐    ┌────────────┐
│  Cases   │───▶│  Provider Pool   │───▶│  Evaluator Pool   │───▶│   Writer   │
│  Queue   │    │  (N workers)     │    │  (M workers)      │    │            │
└──────────┘    └──────────────────┘    └───────────────────┘    └────────────┘
     │                  │                        │                      │
     │            provider_queue           response_queue          result_queue
     │                  │                        │                      │
     └──────────────────┴────────────────────────┴──────────────────────┘
                              asyncio.Queue (内存)
```

### 2.2 数据流

```
              ┌─────────────────────────────────────────────────────────────┐
              │                        Run Orchestrator                      │
              │                                                              │
              │  1. Load dataset                                             │
              │  2. Push cases to provider_queue                             │
              │  3. Start worker pools                                       │
              │  4. Wait for completion                                      │
              └─────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Pipeline Stages                                 │
│                                                                              │
│   ┌─────────────┐      ┌─────────────┐      ┌─────────────┐                 │
│   │   Stage 1   │      │   Stage 2   │      │   Stage 3   │                 │
│   │  Provider   │ ───▶ │  Evaluator  │ ───▶ │   Writer    │                 │
│   │             │      │             │      │             │                 │
│   │ Semaphore:4 │      │ Semaphore:8 │      │ Serial:1    │                 │
│   └─────────────┘      └─────────────┘      └─────────────┘                 │
│                                                                              │
│   Input:               Input:               Input:                          │
│   - EvalCase           - ProviderResponse   - CaseResult                    │
│   - query              - case context       - eval_results                  │
│                                                                              │
│   Output:              Output:              Output:                          │
│   - ProviderResponse   - CaseResult         - DB record                     │
│   - latency, status    - eval_results       - JSONL line                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 队列设计

### 3.1 三级队列

```python
from asyncio import Queue
from dataclasses import dataclass

@dataclass
class ProviderTask:
    """Stage 1: Provider 队列任务"""
    case: EvalCase
    run_id: str
    retry_count: int = 0

@dataclass
class EvaluatorTask:
    """Stage 2: Evaluator 队列任务"""
    case: EvalCase
    response: ProviderResponse
    run_id: str

@dataclass
class WriterTask:
    """Stage 3: Writer 队列任务"""
    result: CaseResult
    run_id: str

class PipelineQueues:
    def __init__(self):
        self.provider_queue: Queue[ProviderTask | None] = Queue()
        self.evaluator_queue: Queue[EvaluatorTask | None] = Queue()
        self.writer_queue: Queue[WriterTask | None] = Queue()
```

### 3.2 Sentinel 模式

使用 `None` 作为 sentinel 信号，通知 worker 退出：

```python
# 发送退出信号（每个 worker 一个）
for _ in range(num_workers):
    await queue.put(None)

# Worker 收到 None 时退出
async def worker_loop():
    while True:
        task = await queue.get()
        if task is None:
            break
        await process(task)
```

---

## 4. Worker Pool 设计

### 4.1 Provider Worker Pool

```python
class ProviderWorkerPool:
    """Provider 调用池 - 控制模型并发"""

    def __init__(
        self,
        provider: BaseProvider,
        concurrency: int,
        timeout_ms: int,
        max_retries: int,
        queues: PipelineQueues,
    ):
        self.provider = provider
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout_ms = timeout_ms
        self.max_retries = max_retries
        self.queues = queues

    async def worker(self, worker_id: int):
        """单个 Provider Worker"""
        while True:
            task = await self.queues.provider_queue.get()
            if task is None:
                break

            async with self.semaphore:
                try:
                    response = await asyncio.wait_for(
                        self.provider.generate(task.case.query),
                        timeout=self.timeout_ms / 1000
                    )
                except asyncio.TimeoutError:
                    response = ProviderResponse(
                        output="",
                        latency_ms=self.timeout_ms,
                        status=ProviderStatus.TIMEOUT,
                        error="timeout"
                    )
                except Exception as e:
                    # 重试逻辑
                    if task.retry_count < self.max_retries:
                        task.retry_count += 1
                        await self.queues.provider_queue.put(task)
                        continue
                    response = ProviderResponse(
                        output="",
                        latency_ms=0,
                        status=ProviderStatus.ERROR,
                        error=str(e)
                    )

                # 推送到 Evaluator 队列
                await self.queues.evaluator_queue.put(
                    EvaluatorTask(
                        case=task.case,
                        response=response,
                        run_id=task.run_id
                    )
                )

    async def start(self, num_workers: int):
        """启动 worker pool"""
        workers = [
            asyncio.create_task(self.worker(i))
            for i in range(num_workers)
        ]
        return workers
```

### 4.2 Evaluator Worker Pool

```python
class EvaluatorWorkerPool:
    """Evaluator 执行池 - 支持 Rule 和 LLM Judge"""

    def __init__(
        self,
        evaluators: dict[str, BaseEvaluator],
        llm_judge_provider: BaseProvider | None,
        rule_concurrency: int,
        llm_concurrency: int,
        queues: PipelineQueues,
    ):
        self.evaluators = evaluators
        self.llm_judge_provider = llm_judge_provider
        self.rule_semaphore = asyncio.Semaphore(rule_concurrency)
        self.llm_semaphore = asyncio.Semaphore(llm_concurrency)
        self.queues = queues

    def _is_llm_evaluator(self, evaluator: BaseEvaluator) -> bool:
        """判断是否是 LLM Judge 类型"""
        return getattr(evaluator, 'requires_llm', False)

    async def _run_evaluator(
        self,
        evaluator: BaseEvaluator,
        output: str,
        expected: str,
        metadata: dict,
    ) -> EvalResult:
        """执行单个 evaluator，根据类型选择 semaphore"""
        if self._is_llm_evaluator(evaluator):
            async with self.llm_semaphore:
                return await evaluator.evaluate_async(
                    output, expected, metadata,
                    provider=self.llm_judge_provider
                )
        else:
            async with self.rule_semaphore:
                return evaluator.evaluate(output, expected, metadata)

    async def worker(self, worker_id: int):
        """单个 Evaluator Worker"""
        while True:
            task = await self.queues.evaluator_queue.get()
            if task is None:
                break

            eval_results: dict[str, EvalResult] = {}

            # 确定要执行的 evaluators
            eval_types = task.case.eval_types
            if eval_types == ["all"]:
                eval_types = list(self.evaluators.keys())

            # 执行所有 evaluators
            for eval_type in eval_types:
                evaluator = self.evaluators.get(eval_type)
                if evaluator is None:
                    eval_results[eval_type] = EvalResult(
                        passed=False,
                        reason=f"Unknown evaluator: {eval_type}",
                        evaluator_type=eval_type,
                        error=f"Unknown evaluator: {eval_type}"
                    )
                    continue

                try:
                    result = await self._run_evaluator(
                        evaluator,
                        task.response.output,
                        task.case.expected_answer,
                        task.case.metadata
                    )
                    eval_results[eval_type] = result
                except Exception as e:
                    eval_results[eval_type] = EvalResult(
                        passed=False,
                        reason=str(e),
                        evaluator_type=eval_type,
                        error=str(e)
                    )

            # 构建 CaseResult
            case_result = CaseResult(
                case_id=task.case.case_id,
                query=task.case.query,
                expected=task.case.expected_answer,
                actual_output=task.response.output,
                eval_results=eval_results,
                latency_ms=task.response.latency_ms,
                provider_status=task.response.status,
                error_message=task.response.error,
            )

            # 推送到 Writer 队列
            await self.queues.writer_queue.put(
                WriterTask(result=case_result, run_id=task.run_id)
            )

    async def start(self, num_workers: int):
        workers = [
            asyncio.create_task(self.worker(i))
            for i in range(num_workers)
        ]
        return workers
```

### 4.3 Writer Worker（单例）

```python
class WriterWorker:
    """结果写入器 - 串行写入，保证一致性"""

    def __init__(
        self,
        db: Database,
        file_storage: FileStorage,
        queues: PipelineQueues,
    ):
        self.db = db
        self.file_storage = file_storage
        self.queues = queues
        self._results: dict[str, list[CaseResult]] = {}  # run_id -> results

    async def run(self):
        """Writer 主循环"""
        while True:
            task = await self.queues.writer_queue.get()
            if task is None:
                break

            # 写入数据库
            await self.db.save_case_result(task.run_id, task.result)

            # 追加写入 JSONL
            self.file_storage.append_case_result(task.run_id, task.result)

            # 收集结果用于 summary
            if task.run_id not in self._results:
                self._results[task.run_id] = []
            self._results[task.run_id].append(task.result)

    def get_results(self, run_id: str) -> list[CaseResult]:
        return self._results.get(run_id, [])
```

---

## 5. Evaluator 分类

### 5.1 两类 Evaluator

| 类型 | 特点 | 并发控制 | 示例 |
|------|------|----------|------|
| **Rule Evaluator** | 纯 CPU 计算，毫秒级 | `rule_semaphore` | exact_match, contains, regex |
| **LLM Judge** | 需要调用模型，秒级 | `llm_semaphore` | llm_judge, semantic_similarity |

### 5.2 LLM Judge 接口

```python
class BaseEvaluator(ABC):
    """Evaluator 基类"""

    requires_llm: bool = False  # 是否需要 LLM

    @abstractmethod
    def evaluate(
        self,
        output: str,
        expected: str,
        metadata: dict = None,
    ) -> EvalResult:
        """同步评估（Rule Evaluator）"""
        pass

    async def evaluate_async(
        self,
        output: str,
        expected: str,
        metadata: dict = None,
        provider: BaseProvider = None,
    ) -> EvalResult:
        """异步评估（LLM Judge）"""
        # 默认调用同步方法
        return self.evaluate(output, expected, metadata)


@register("llm_judge")
class LLMJudgeEvaluator(BaseEvaluator):
    """使用 LLM 评判答案质量"""

    requires_llm = True

    def evaluate(self, output: str, expected: str, metadata: dict = None) -> EvalResult:
        raise NotImplementedError("LLM Judge requires async evaluate")

    async def evaluate_async(
        self,
        output: str,
        expected: str,
        metadata: dict = None,
        provider: BaseProvider = None,
    ) -> EvalResult:
        if provider is None:
            return EvalResult(
                passed=False,
                reason="LLM Judge requires a provider",
                evaluator_type="llm_judge",
                error="No provider configured"
            )

        # 构建 prompt
        prompt = self._build_judge_prompt(output, expected, metadata)

        # 调用 LLM
        response = await provider.generate(prompt)

        # 解析结果
        return self._parse_judge_response(response.output)

    def _build_judge_prompt(self, output: str, expected: str, metadata: dict) -> str:
        template = metadata.get("judge_prompt", DEFAULT_JUDGE_PROMPT)
        return template.format(
            output=output,
            expected=expected,
            criteria=metadata.get("criteria", "correctness and completeness")
        )

    def _parse_judge_response(self, response: str) -> EvalResult:
        # 解析 LLM 返回的 JSON 或结构化输出
        # ...
        pass


DEFAULT_JUDGE_PROMPT = """
You are an expert evaluator. Compare the model output with the expected answer.

Model Output:
{output}

Expected Answer:
{expected}

Evaluation Criteria: {criteria}

Respond with JSON:
{{"passed": true/false, "reason": "your explanation"}}
"""
```

### 5.3 配置示例

```yaml
# providers.yaml
judge-gpt4:
  type: openai_compatible
  base_url: https://api.openai.com/v1
  model: gpt-4

# config.yaml
evaluator_config:
  llm_judge_provider: judge-gpt4  # 用于 LLM Judge 的 provider
  llm_concurrency: 2               # LLM Judge 并发数（独立于 Provider）
  rule_concurrency: 10             # Rule Evaluator 并发数
```

```jsonl
// dataset
{
  "case_id": "qa-001",
  "query": "什么是机器学习？",
  "expected_answer": "机器学习是人工智能的一个分支...",
  "eval_types": ["contains", "llm_judge"],
  "metadata": {
    "criteria": "accuracy, completeness, clarity"
  }
}
```

---

## 6. Pipeline Orchestrator

### 6.1 完整流程

```python
class PipelineOrchestrator:
    """流水线编排器"""

    def __init__(
        self,
        db: Database,
        file_storage: FileStorage,
        providers: dict[str, ProviderConfig],
        config: Config,
    ):
        self.db = db
        self.file_storage = file_storage
        self.providers = providers
        self.config = config

    async def run(self, run_config: RunConfig) -> RunSummary:
        """执行完整的评测流程"""

        # 1. 初始化
        queues = PipelineQueues()
        provider = create_provider(run_config.provider_name, self.providers)
        evaluators = self._load_evaluators()
        llm_judge_provider = self._create_llm_judge_provider()

        # 2. 创建 run 记录
        await self.db.create_run(run_config)
        await self.db.update_run_status(run_config.run_id, RunStatus.RUNNING)

        # 3. 加载数据集
        cases = load_dataset(run_config.dataset_path)
        completed_ids = await self.db.get_completed_cases(run_config.run_id)
        pending_cases = [c for c in cases if c.case_id not in completed_ids]

        # 4. 推送任务到 Provider 队列
        for case in pending_cases:
            await queues.provider_queue.put(
                ProviderTask(case=case, run_id=run_config.run_id)
            )

        # 5. 启动 Workers
        provider_workers = await ProviderWorkerPool(
            provider=provider,
            concurrency=run_config.concurrency,
            timeout_ms=run_config.timeout_ms,
            max_retries=run_config.max_retries,
            queues=queues,
        ).start(num_workers=run_config.concurrency)

        evaluator_workers = await EvaluatorWorkerPool(
            evaluators=evaluators,
            llm_judge_provider=llm_judge_provider,
            rule_concurrency=self.config.rule_concurrency,
            llm_concurrency=self.config.llm_concurrency,
            queues=queues,
        ).start(num_workers=4)

        writer = WriterWorker(
            db=self.db,
            file_storage=self.file_storage,
            queues=queues,
        )
        writer_task = asyncio.create_task(writer.run())

        # 6. 发送 sentinel 并等待完成
        # Provider -> Evaluator -> Writer 级联关闭
        for _ in range(len(provider_workers)):
            await queues.provider_queue.put(None)
        await asyncio.gather(*provider_workers)

        for _ in range(len(evaluator_workers)):
            await queues.evaluator_queue.put(None)
        await asyncio.gather(*evaluator_workers)

        await queues.writer_queue.put(None)
        await writer_task

        # 7. 计算 summary 并完成
        results = writer.get_results(run_config.run_id)
        summary = self._compute_summary(results)
        await self.db.complete_run(run_config.run_id, summary)

        # 8. 清理
        await provider.close()
        if llm_judge_provider:
            await llm_judge_provider.close()

        return summary
```

---

## 7. 配置扩展

### 7.1 Config 新增字段

```python
class Config(BaseModel):
    # v1 字段
    timeout_ms: int = 30000
    max_retries: int = 3
    concurrency: int = 4
    output_dir: str = "./outputs"
    evaluators_package: str = "mini_llm_eval.evaluators"

    # v2 新增
    provider_concurrency: int = 4      # Provider 并发数
    rule_concurrency: int = 10         # Rule Evaluator 并发数
    llm_concurrency: int = 2           # LLM Judge 并发数
    llm_judge_provider: str | None = None  # LLM Judge 使用的 provider

    # Worker 配置
    provider_workers: int = 4          # Provider worker 数量
    evaluator_workers: int = 4         # Evaluator worker 数量
```

### 7.2 向后兼容

```python
# v1 配置仍然有效
concurrency: 4  # 同时控制 provider_concurrency 和 provider_workers

# v2 精细控制
provider_concurrency: 4
provider_workers: 4
rule_concurrency: 10
llm_concurrency: 2
```

---

## 8. 断点恢复

### 8.1 恢复逻辑

```python
async def resume(self, run_id: str) -> RunSummary:
    """断点恢复 - 跳过已完成的 cases"""

    # 1. 检查 run 状态
    run = await self.db.get_run(run_id)
    if run.status == RunStatus.SUCCEEDED:
        return run.summary  # 已完成

    # 2. 获取已完成的 case_ids
    completed_ids = await self.db.get_completed_cases(run_id)

    # 3. 加载数据集，过滤已完成
    cases = load_dataset(run.dataset_path)
    pending_cases = [c for c in cases if c.case_id not in completed_ids]

    # 4. 继续执行
    # ... 同 run() 流程
```

### 8.2 状态日志

```sql
-- 新增：阶段状态日志（可选）
CREATE TABLE IF NOT EXISTS stage_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    stage TEXT NOT NULL,  -- 'provider' | 'evaluator' | 'writer'
    status TEXT NOT NULL, -- 'started' | 'completed' | 'error'
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
```

---

## 9. 性能对比

### 9.1 预期收益

| 场景 | v1 | v2 | 提升 |
|------|-----|-----|------|
| 100 cases, 纯 Rule | 100s | 100s | - |
| 100 cases, Rule + LLM Judge | 200s | 120s | 40% |
| Provider 慢, Evaluator 快 | 串行等待 | 流水线并行 | 显著 |
| 部分 case 失败 | 影响后续 | 隔离处理 | 更稳定 |

### 9.2 资源占用

```
v1: 1 event loop, N provider tasks
v2: 1 event loop, N+M+1 workers, 3 queues

内存增长：可控（Queue 有 maxsize）
CPU：更好利用多核（Worker 并行）
```

---

## 10. 实施计划

### Phase 1: 队列基础设施
- [ ] 定义 ProviderTask, EvaluatorTask, WriterTask
- [ ] 实现 PipelineQueues
- [ ] Sentinel 退出机制

### Phase 2: Worker Pools
- [ ] ProviderWorkerPool（基于 v1 Executor 改造）
- [ ] EvaluatorWorkerPool（双 Semaphore）
- [ ] WriterWorker（基于 v1 writer_loop）

### Phase 3: LLM Judge
- [ ] BaseEvaluator 增加 `requires_llm` 和 `evaluate_async`
- [ ] 实现 LLMJudgeEvaluator
- [ ] 配置 llm_judge_provider

### Phase 4: Pipeline Orchestrator
- [ ] 整合所有组件
- [ ] 断点恢复适配
- [ ] 配置兼容

### Phase 5: 测试
- [ ] 队列单元测试
- [ ] Worker 单元测试
- [ ] 端到端集成测试
- [ ] 性能对比测试

---

## 11. 后续演进（v3）

| 特性 | 说明 |
|------|------|
| **持久化队列** | Redis / SQLite 队列，支持跨进程 |
| **分布式 Worker** | 多机部署 |
| **动态扩缩容** | 根据队列积压自动调整 worker 数量 |
| **优先级队列** | 高优先级 case 先执行 |
| **Rate Limiting** | Provider 级别限流 |

---

*文档版本: v2.0 Draft*
*最后更新: 2026-04-26*
