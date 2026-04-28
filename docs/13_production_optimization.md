# 生产级分布式架构优化方案

> 文档状态：架构规划
>
> 创建日期：2026-04-27
>
> 目标：梳理从 v1 单体演进到生产级分布式系统的优化方向

---

## 1. 核心洞察

### 1.1 Provider 本质是 LLM API Gateway

当前 Provider 的核心职责：

```
接收请求 → 限流 → 转发 LLM API → 重试 → 返回响应
```

这与 nginx/envoy 的反向代理模式几乎一致：

| 功能 | nginx/envoy | Provider |
|------|-------------|----------|
| 连接管理 | ✓ | ✓ |
| 负载均衡 | ✓ | ✓ (多 provider) |
| 限流 | ✓ | ✓ (RPS, concurrency) |
| 重试 | ✓ | ✓ |
| 超时 | ✓ | ✓ |
| 健康检查 | ✓ | 待实现 |
| 熔断 | ✓ | 待实现 |

### 1.2 Evaluator 是计算密集但 IO-bound

- Rule-based evaluator：CPU 密集但计算量小，Python 足够
- LLM Judge evaluator：IO-bound（等 LLM 响应），语言不是瓶颈

### 1.3 架构分离是关键

```
当前: 单进程 asyncio，Provider + Evaluator 耦合
目标: Provider Gateway (Go) + Evaluator Workers (Python) + 队列解耦
```

---

## 2. Provider Gateway 重构方案

### 2.1 为什么用 Go

| 维度 | Python (当前) | Go (目标) |
|------|---------------|-----------|
| 并发模型 | asyncio (单线程) | goroutine (M:N 调度) |
| 内存占用 | 较高 | 低 |
| 启动时间 | 慢 | 快 |
| 10k+ 并发 | 勉强 | 轻松 |
| 网络库成熟度 | httpx (良好) | net/http (生产级) |
| 长期运行稳定性 | 一般 | 优秀 |

### 2.2 替代方案：Envoy + 自定义 Filter

如果不想从零写 Go 服务，可以用 Envoy：

```yaml
# envoy.yaml 示例
static_resources:
  listeners:
    - address:
        socket_address:
          address: 0.0.0.0
          port_value: 8080
      filter_chains:
        - filters:
            - name: envoy.filters.http.router
              typed_config:
                "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
  clusters:
    - name: openai_cluster
      type: STRICT_DNS
      lb_policy: ROUND_ROBIN
      load_assignment:
        cluster_name: openai_cluster
        endpoints:
          - lb_endpoints:
              - endpoint:
                  address:
                    socket_address:
                      address: api.openai.com
                      port_value: 443
```

优点：
- 开箱即用的限流、熔断、重试
- 丰富的可观测性
- 社区维护

缺点：
- 定制性受限
- 学习曲线

### 2.3 Go Provider Gateway 核心组件

```go
// 核心结构
type ProviderGateway struct {
    upstreams     map[string]*Upstream    // LLM API 上游
    rateLimiter   *AdaptiveRateLimiter    // 自适应限流
    circuitBreaker *CircuitBreaker        // 熔断器
    requestQueue  *PriorityQueue          // 优先级队列
    cache         *PromptCache            // Prompt 缓存
    metrics       *PrometheusMetrics      // 指标
}

// 请求处理流程
func (g *ProviderGateway) Handle(ctx context.Context, req *Request) (*Response, error) {
    // 1. 检查缓存
    if cached := g.cache.Get(req.PromptHash); cached != nil {
        return cached, nil
    }

    // 2. 限流
    if err := g.rateLimiter.Acquire(ctx, req.Provider); err != nil {
        return nil, ErrRateLimited
    }

    // 3. 熔断检查
    if !g.circuitBreaker.Allow(req.Provider) {
        return nil, ErrCircuitOpen
    }

    // 4. 转发请求
    resp, err := g.upstreams[req.Provider].Forward(ctx, req)

    // 5. 更新熔断状态
    g.circuitBreaker.Record(req.Provider, err)

    // 6. 缓存响应
    if err == nil && req.Cacheable {
        g.cache.Set(req.PromptHash, resp)
    }

    return resp, err
}
```

---

## 3. 限流/调度优化

### 3.1 当前实现 vs 生产目标

| 功能 | 当前 (v1) | 生产目标 |
|------|-----------|----------|
| RPS 限制 | 固定 RPS | Token Bucket / Leaky Bucket |
| 并发限制 | Semaphore | 分布式 Semaphore (Redis) |
| 429 处理 | 固定重试 | 自适应退让 |
| 优先级 | 无 | 优先级队列 |
| 配额 | 无 | 租户/项目配额 |

### 3.2 自适应限流算法

```python
class AdaptiveRateLimiter:
    """429 驱动的自适应限流"""

    def __init__(self, initial_rps: float, min_rps: float, max_rps: float):
        self.current_rps = initial_rps
        self.min_rps = min_rps
        self.max_rps = max_rps
        self.backoff_factor = 0.5
        self.recovery_factor = 1.1
        self.consecutive_success = 0
        self.recovery_threshold = 10

    def on_success(self):
        self.consecutive_success += 1
        if self.consecutive_success >= self.recovery_threshold:
            self.current_rps = min(self.current_rps * self.recovery_factor, self.max_rps)
            self.consecutive_success = 0

    def on_rate_limited(self):
        self.current_rps = max(self.current_rps * self.backoff_factor, self.min_rps)
        self.consecutive_success = 0
```

### 3.3 优先级队列

```
┌─────────────────────────────────┐
│       Priority Queue            │
├─────────────────────────────────┤
│ P0: Critical (production runs)  │ ──▶ 立即处理
├─────────────────────────────────┤
│ P1: Normal (standard runs)      │ ──▶ 正常排队
├─────────────────────────────────┤
│ P2: Low (batch/background)      │ ──▶ 可被抢占
└─────────────────────────────────┘
```

---

## 4. 请求级优化

### 4.1 Prompt 缓存

```python
class PromptCache:
    """基于 prompt hash 的结果缓存"""

    def __init__(self, redis_client, ttl_seconds: int = 3600):
        self.redis = redis_client
        self.ttl = ttl_seconds

    def _hash(self, prompt: str, model: str) -> str:
        return hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()

    async def get(self, prompt: str, model: str) -> str | None:
        key = f"prompt_cache:{self._hash(prompt, model)}"
        return await self.redis.get(key)

    async def set(self, prompt: str, model: str, response: str):
        key = f"prompt_cache:{self._hash(prompt, model)}"
        await self.redis.setex(key, self.ttl, response)
```

适用场景：
- 相同 prompt 多次请求（AB 测试、重跑）
- 固定 prompt 模板 + 有限参数组合

### 4.2 Batch Inference

部分 LLM API 支持批量推理：

```python
# 单请求
response = await provider.generate("prompt1")

# 批量请求 (部分 API 支持)
responses = await provider.generate_batch(["prompt1", "prompt2", "prompt3"])
```

优化效果：
- 减少 HTTP 连接开销
- 部分 API 有批量折扣

### 4.3 Request Coalescing

```python
class RequestCoalescer:
    """短时间内相同请求去重"""

    def __init__(self, window_ms: int = 100):
        self.pending: dict[str, asyncio.Future] = {}
        self.window_ms = window_ms

    async def execute(self, key: str, fn: Callable) -> Any:
        if key in self.pending:
            return await self.pending[key]

        future = asyncio.Future()
        self.pending[key] = future

        try:
            result = await fn()
            future.set_result(result)
            return result
        finally:
            await asyncio.sleep(self.window_ms / 1000)
            del self.pending[key]
```

---

## 5. 队列解耦架构

### 5.1 目标架构

```
┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ API/CLI │────▶│   Provider  │────▶│  Evaluator  │────▶│   Writer    │
└─────────┘     │    Queue    │     │    Queue    │     │    Queue    │
                └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
                       │                   │                   │
                ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
                │     Go      │     │   Python    │     │   Go/Py     │
                │   Workers   │     │   Workers   │     │   Workers   │
                │  (Gateway)  │     │ (Evaluator) │     │  (Storage)  │
                └─────────────┘     └─────────────┘     └─────────────┘
```

### 5.2 队列选择

| 队列 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **Kafka** | 高吞吐、持久化、replay | 运维复杂 | 大规模生产 |
| **Redis Streams** | 轻量、低延迟 | 持久化较弱 | 中等规模 |
| **RabbitMQ** | 灵活路由、优先级 | 吞吐中等 | 复杂路由需求 |

### 5.3 消息格式

```json
// Provider Queue Message
{
  "run_id": "run_abc123",
  "case_id": "case_001",
  "prompt": "...",
  "provider": "openai",
  "model": "gpt-4",
  "priority": 1,
  "timeout_ms": 30000,
  "retry_count": 0,
  "enqueued_at": "2026-04-27T10:00:00Z"
}

// Evaluator Queue Message
{
  "run_id": "run_abc123",
  "case_id": "case_001",
  "provider_response": {
    "output": "...",
    "latency_ms": 234.5
  },
  "eval_types": ["contains", "json_field"],
  "expected_answer": "...",
  "metadata": {}
}
```

---

## 6. 存储层升级

### 6.1 当前 vs 目标

| 组件 | 当前 (v1) | 生产目标 |
|------|-----------|----------|
| 元数据 | SQLite | PostgreSQL |
| 产物 | 本地文件 | S3/MinIO |
| 缓存 | 无 | Redis |
| 限流状态 | 进程内 | Redis |

### 6.2 PostgreSQL Schema

```sql
-- 分区表支持大规模数据
CREATE TABLE case_results (
    id BIGSERIAL,
    run_id UUID NOT NULL,
    case_id TEXT NOT NULL,
    status TEXT NOT NULL,
    passed BOOLEAN,
    latency_ms REAL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- 按月分区
CREATE TABLE case_results_2026_04 PARTITION OF case_results
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

-- 索引
CREATE INDEX idx_case_results_run_id ON case_results (run_id);
CREATE INDEX idx_case_results_status ON case_results (status) WHERE status = 'failed';
```

### 6.3 S3 产物结构

```
s3://eval-artifacts/
├── runs/
│   ├── run_abc123/
│   │   ├── meta.json
│   │   ├── case_results.jsonl
│   │   └── logs/
│   │       └── execution.log
│   └── run_def456/
│       └── ...
└── cache/
    └── prompts/
        └── {hash}.json
```

---

## 7. 可观测性

### 7.1 Metrics (Prometheus)

```python
# 关键指标
provider_request_total = Counter(
    "provider_request_total",
    "Total provider requests",
    ["provider", "status"]
)

provider_latency_seconds = Histogram(
    "provider_latency_seconds",
    "Provider request latency",
    ["provider"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30]
)

evaluator_pass_rate = Gauge(
    "evaluator_pass_rate",
    "Current pass rate",
    ["run_id", "evaluator"]
)

queue_depth = Gauge(
    "queue_depth",
    "Current queue depth",
    ["queue_name"]
)
```

### 7.2 Tracing (OpenTelemetry)

```
Trace: run_abc123
├── Span: submit_run (API)
│   └── Span: create_run_record (DB)
├── Span: process_case (case_001)
│   ├── Span: provider_request (openai)
│   │   ├── Span: rate_limit_wait
│   │   └── Span: http_request
│   └── Span: evaluate
│       ├── Span: contains_evaluator
│       └── Span: json_field_evaluator
└── Span: write_artifacts (S3)
```

### 7.3 成本归因

```sql
-- 按 run 统计 token 消耗
SELECT
    run_id,
    SUM(prompt_tokens) as total_prompt_tokens,
    SUM(completion_tokens) as total_completion_tokens,
    SUM(prompt_tokens * 0.00003 + completion_tokens * 0.00006) as estimated_cost_usd
FROM provider_logs
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY run_id
ORDER BY estimated_cost_usd DESC;
```

---

## 8. 多租户与隔离

### 8.1 租户隔离级别

| 级别 | 隔离方式 | 适用场景 |
|------|----------|----------|
| 逻辑隔离 | 同一集群，tenant_id 区分 | 成本敏感 |
| 资源隔离 | 独立队列、独立 worker pool | 性能敏感 |
| 物理隔离 | 独立集群 | 安全敏感 |

### 8.2 配额管理

```python
class TenantQuota:
    """租户配额管理"""

    async def check_and_consume(self, tenant_id: str, tokens: int) -> bool:
        key = f"quota:{tenant_id}:tokens"
        remaining = await self.redis.decrby(key, tokens)
        if remaining < 0:
            await self.redis.incrby(key, tokens)  # 回滚
            return False
        return True

    async def reset_daily_quota(self, tenant_id: str, limit: int):
        key = f"quota:{tenant_id}:tokens"
        await self.redis.setex(key, 86400, limit)
```

---

## 9. 架构演进路径

```
┌─────────────────────────────────────────────────────────────────┐
│ v1 (当前)                                                        │
│ Python 单体，SQLite，本地文件                                      │
│ 适用：开发/测试环境，小规模评测                                     │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ v2 (近期)                                                        │
│ Python，Provider/Evaluator 队列解耦                               │
│ PostgreSQL + S3，Redis 缓存                                       │
│ 适用：团队内部使用，中等规模评测                                     │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ v3 (中期)                                                        │
│ Provider Gateway 用 Go 重写（或 Envoy）                           │
│ Evaluator 保持 Python（Serverless）                               │
│ Kafka/Redis Streams 做队列                                       │
│ 适用：生产环境，大规模评测                                          │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ v4 (远期)                                                        │
│ 全托管平台                                                        │
│ 多租户、成本计费、Prompt 缓存                                       │
│ LLM Provider 自动选择/路由                                        │
│ 适用：SaaS 服务                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 10. 投入优先级建议

### 10.1 高 ROI 优化

| 优化 | 投入 | 收益 | 优先级 |
|------|------|------|--------|
| Go Provider Gateway | 高 | 高 (性能、稳定性) | P0 |
| 队列解耦 | 中 | 高 (可扩展性) | P0 |
| PostgreSQL + S3 | 中 | 高 (可靠性) | P1 |
| Prompt 缓存 | 低 | 中 (成本节约) | P1 |
| 自适应限流 | 中 | 中 (稳定性) | P2 |

### 10.2 可延后优化

| 优化 | 说明 |
|------|------|
| Batch Inference | 依赖 LLM API 支持 |
| 多租户隔离 | SaaS 阶段再做 |
| 分布式 Tracing | 规模大了再加 |

---

## 11. 总结

核心架构决策：

1. **Provider Gateway 用 Go 重写** — 本质是 LLM API 反向代理，Go 更适合
2. **Evaluator 保持 Python** — IO-bound，语言不是瓶颈，Serverless 化即可
3. **队列解耦** — Kafka/Redis Streams 做 back-pressure 和扩展
4. **存储升级** — PostgreSQL + S3 + Redis 标准三件套

最大投入应在 **Provider Gateway** 和 **队列系统**，这是分布式的核心。
