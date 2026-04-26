# Code Review #4 - Claude

> 审查时间: 2026-04-25
> 审查者: Claude
> 审查范围: Executor + RunService 实现

---

## 总体评价

**整体质量: 优秀**

Codex 完成了 Service 层的核心实现，包括 Executor（并发执行）和 RunService（完整 run 编排）。代码架构清晰，符合设计文档。38 个测试全部通过。

**这是 MVP 核心功能的完成里程碑。**

---

## Review #4 修复确认

Codex 修复了 `provider.close()` 异常路径问题：

### 修复内容

```python
# start_run 和 resume_run 都使用了这个模式
provider = None
try:
    provider = self._create_provider(...)
    # ... 执行逻辑
except Exception:
    # ... 错误处理
    raise
finally:
    if provider is not None:
        await provider.close()
```

### 验证结论

| 检查项 | 状态 |
|-------|------|
| `provider.close()` 异常路径 | ✅ 稳，`None` 初始化 + `finally` + 非空检查 |
| 回归测试 `test_run_service_closes_provider_on_failure` | ✅ 命中真正风险路径 |

---

## Executor 实现评价

### 1. 并发控制 - 优秀

- 使用 `Semaphore` 限制 Provider 并发数
- 独立的 timeout 控制
- Queue + sentinel 模式实现优雅的 writer 协调

### 2. Writer Queue 模式 - 优秀

- 单独的 writer 协程串行化写入，避免并发写冲突
- Sentinel 模式优雅退出
- `finally` 块确保 writer 正确关闭

### 3. eval_types: ["all"] 支持 - 优秀

符合设计文档的 `eval_types` 语义。

---

## RunService 实现评价

### 1. 完整 Run 流程 - 优秀

生命周期：创建 → RUNNING → 执行 → SUCCEEDED/FAILED → meta.json

### 2. Resume 支持 - 优秀

正确跳过已完成 cases，合并结果计算 summary。

### 3. Summary 统计 - 完善

包含 pass_rate、tag_pass_rates、avg/p95 latency、error_distribution。

---

## 验收清单

- [x] Semaphore 并发控制
- [x] Writer queue 串行化写入
- [x] 完整 run 生命周期
- [x] Resume 跳过已完成 cases
- [x] provider.close() 异常路径修复
- [x] 38 个测试全部通过

**评分: 9.5/10**

---

## 后续设计建议：Plugin Provider（用户想法）

> **注意**: 以下设计建议来自用户 @tiashi 的想法，不是当前代码的 review 内容。

### 背景

用户指出当前 Provider 框架性不够强。实际场景中：
- 用户训练了 8B 模型，部署到自定义服务
- 不同模型请求 payload 不同（有的要 CoT，有的有 system prompt）
- 有些服务已封装成简单的 QA 接口

### 用户核心想法

> "我希望可以像 Lua 语言那样即插即拔"

Lua 的特点：**单文件、约定接口、放进去就能用、删掉就没了**

### 设计方案：Plugin Provider

#### 用户体验

```
mini_llm_eval/
├── plugins/              # 插件目录
│   ├── my_8b_model.py    # 放进来就能用
│   └── qa_service.py     # 删掉就没了
└── providers.yaml
```

#### 用户只需写一个函数

```python
# plugins/my_8b_model.py
"""我的 8B 模型插件"""

async def generate(query: str, config: dict) -> dict:
    """
    唯一需要实现的函数

    Args:
        query: 用户输入
        config: providers.yaml 中的配置

    Returns:
        {"output": "模型输出"}  # output 必须，其他可选
    """
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            config["endpoint"],
            json={
                "query": query,
                "enable_cot": config.get("enable_cot", False),
            }
        )
        return {"output": resp.json()["answer"]}
```

#### 配置引用

```yaml
# providers.yaml
my-8b-model:
  type: plugin
  plugin: my_8b_model          # 对应 plugins/my_8b_model.py
  endpoint: http://localhost:8000/predict
  enable_cot: true
```

#### 即插即拔特性

| 特性 | 实现 |
|-----|------|
| **即插** | 放 `.py` 文件到 `plugins/` 目录 |
| **即拔** | 删除文件即可 |
| **零继承** | 只需实现 `generate(query, config)` 函数 |
| **配置透传** | `providers.yaml` 中的所有字段都传给插件 |

#### 框架实现要点

```python
# src/mini_llm_eval/providers/plugin.py

class PluginProvider(BaseProvider):
    def _load_plugin(self) -> PluginGenerateFn:
        plugin_name = self._config.extra.get("plugin")
        plugins_dir = Path(config.extra.get("plugins_dir", "./plugins"))
        plugin_path = plugins_dir / f"{plugin_name}.py"

        # 动态加载模块
        spec = importlib.util.spec_from_file_location(plugin_name, plugin_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return module.generate  # 获取 generate 函数

    async def generate(self, query: str, **kwargs) -> ProviderResponse:
        result = await self._generate_fn(query, self._config.extra)
        return ProviderResponse(output=result["output"], ...)
```

#### 插件示例

```python
# plugins/simple_qa.py
async def generate(query: str, config: dict) -> dict:
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(config["endpoint"], json={"question": query})
        return {"output": resp.json()["answer"]}
```

```python
# plugins/vllm_server.py
async def generate(query: str, config: dict) -> dict:
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config['endpoint']}/generate",
            json={"prompt": query, "max_tokens": config.get("max_tokens", 1024)},
        )
        return {"output": resp.json()["text"][0]}
```

### 实现优先级

- **当前**: CLI 完成后再实现
- **依赖**: 无新增依赖（使用标准库 `importlib.util`）

---

## 下一步

1. **Phase 7: CLI**（当前目标）
2. **后续**: Plugin Provider 实现（基于用户想法）
