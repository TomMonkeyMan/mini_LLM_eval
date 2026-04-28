# Review #7: Rate Limiter 与交付补齐

> 审查人：Claude
>
> 日期：2026-04-27
>
> 涉及提交：rate_limited.py, factory.py, config.py, demo/, docs/12

---

## 1. 总体评价

本轮修改质量较高，主要完成两件事：

1. **Provider 级限流框架**：新增 `RateLimitedProvider` wrapper
2. **交付物补齐**：demo artifacts、gap report、README 更新

测试全部通过 (76 tests)，代码结构清晰。

---

## 2. RateLimitedProvider 实现分析

### 2.1 设计亮点

```python
class ProviderRateLimiter:
    def __init__(
        self,
        requests_per_second: float,
        *,
        monotonic: Callable[[], float] | None = None,  # 可注入
        sleeper: Callable[[float], Awaitable[None]] | None = None,  # 可注入
    ) -> None:
```

优点：
- **可测试性**：通过注入 `monotonic` 和 `sleeper` 避免真实 sleep，测试更快更可靠
- **关注点分离**：RateLimiter 独立于 Provider，wrapper 模式不侵入原有 provider
- **配置驱动**：factory 自动根据 config 决定是否 wrap

### 2.2 实现细节

```python
async def acquire(self) -> float:
    async with self._lock:
        now = self._monotonic()
        scheduled_at = max(now, self._next_available_at)
        self._next_available_at = scheduled_at + self._interval_seconds
        wait_seconds = max(0.0, scheduled_at - now)

    if wait_seconds > 0:
        await self._sleeper(wait_seconds)
    return wait_seconds
```

评价：
- 使用 `asyncio.Lock` 保护状态，正确处理并发
- 返回实际等待时间，方便日志记录
- 在 lock 外执行 sleep，避免阻塞其他请求获取 slot

### 2.3 factory 集成

```python
if config.provider_concurrency_limit is None and config.requests_per_second is None:
    return provider

return RateLimitedProvider(
    provider,
    provider_concurrency_limit=config.provider_concurrency_limit,
    requests_per_second=config.requests_per_second,
)
```

评价：
- 条件判断清晰，不配置则不 wrap
- Plugin provider 自动继承限流能力

---

## 3. 问题与建议

### 3.1 [低优先级] RateLimiter 缺少 `__slots__`

`ProviderRateLimiter` 和 `RateLimitedProvider` 都没有使用 `__slots__`。

建议添加：
```python
class ProviderRateLimiter:
    __slots__ = ("_interval_seconds", "_monotonic", "_sleeper", "_lock", "_next_available_at")
```

但考虑到这两个类实例数量少，影响不大，可以后续统一处理。

### 3.2 [低优先级] requests_per_second=0 的边界处理

当前代码：
```python
if requests_per_second <= 0:
    raise ValueError("requests_per_second must be > 0")
```

建议：改为在 Pydantic config 层面用 `Field(gt=0)` 约束，提前暴露配置错误。

```python
requests_per_second: float | None = Field(default=None, gt=0)
```

### 3.3 [信息] concurrency vs provider_concurrency_limit 语义

README 更新了说明：

> - `concurrency` 控制 run 级并发
> - `provider_concurrency_limit` 控制单个 provider 的并发上限

当前逻辑：
- run-level `concurrency` 控制 executor 的 case 并发数
- `provider_concurrency_limit` 控制单个 provider 的 in-flight 请求数

如果 `provider_concurrency_limit < concurrency`，会出现 case 并发被 provider semaphore 限流的情况。这是预期行为，但文档可以更明确说明这种场景。

### 3.4 [低优先级] 日志事件名称

```python
extra={
    "event": "provider_rate_limit_wait",
    ...
}
```

建议保持与其他日志事件命名风格一致，如 `provider_rate_limited` 或 `rate_limiter_wait`。

---

## 4. 测试质量

### 4.1 FakeClock 测试模式

```python
class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
```

这种依赖注入 + fake clock 的测试模式非常好：
- 测试不依赖真实时间
- 可以精确验证等待时间
- 运行速度快

### 4.2 并发测试

```python
async def test_rate_limited_provider_enforces_provider_concurrency_limit() -> None:
    class TrackingProvider(MockProvider):
        ...
        async def generate(self, query: str, **kwargs):
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            ...
```

通过 `TrackingProvider` 验证最大并发数，测试设计合理。

---

## 5. docs/12_raw_requirement_gap_report.md 评价

文档结构清晰，对照 raw requirement 逐项列出满足状态：
- 已满足
- 部分满足
- 尚未满足

明确标注剩余 gap 不影响最低验收，属于增强项。

建议：可以考虑在文档末尾加一个简表，方便快速扫描。

---

## 6. demo/ 目录评价

结构合理：
```
demo/
├── README.md
├── quickstart/
│   ├── README.md
│   ├── config.yaml
│   ├── providers.yaml
│   ├── plugins/echo.py
│   ├── data/sample.jsonl
│   └── outputs/
├── demo_cases.jsonl
├── sample_runs/
│   ├── run-baseline/
│   └── run-candidate/
└── compare_example.md
```

优点：
- quickstart 独立可运行
- sample_runs 提供两份完整产物，支持 compare 演示
- compare_example.md 展示对比输出

---

## 7. 总结

| 项目 | 评价 |
|------|------|
| RateLimitedProvider 设计 | 良好 - wrapper 模式、可测试、不侵入原有代码 |
| 测试覆盖 | 良好 - fake clock、并发验证、config 解析 |
| 文档更新 | 良好 - README 限流说明、gap report 清晰 |
| demo 补齐 | 良好 - 满足交付展示要求 |
| 代码规范 | 可改进 - 缺少 __slots__，但影响小 |

**结论：本轮修改可以接受，无阻塞性问题。**

建议在后续版本统一补充 `__slots__`，以及在 Pydantic 层面添加字段约束。
