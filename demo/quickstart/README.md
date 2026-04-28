# Quickstart Example

这是一个用户项目示例，展示如何使用 mini-llm-eval。

## 目录结构

```
quickstart/
├── config.yaml       # 项目配置
├── providers.yaml    # Provider 配置
├── plugins/          # 自定义 Provider
│   └── echo.py
├── data/             # 评测数据集
│   └── sample.jsonl
└── outputs/          # 输出目录（自动创建）
```

## 使用方式

```bash
# 1. 进入项目目录
cd demo/quickstart

# 2. 运行评测（使用 mock provider）
mini-llm-eval run \
  --dataset data/sample.jsonl \
  --provider mock-demo \
  --run-id demo-quickstart \
  --config config.yaml \
  --providers providers.yaml

# 3. 运行评测（使用自定义 plugin）
mini-llm-eval run \
  --dataset data/sample.jsonl \
  --provider my-plugin \
  --run-id demo-plugin \
  --config config.yaml \
  --providers providers.yaml

# 4. 查看结果
mini-llm-eval status demo-quickstart --config config.yaml

# 5. 查看输出文件
ls outputs/demo-quickstart/
```

## 配置说明

### providers.yaml

```yaml
# Mock Provider - 测试用
mock-demo:
  type: mock
  fallback:
    enabled: true
    success_rate: 1.0
    default_response: ""

# Plugin Provider - 自定义模型
my-plugin:
  type: plugin
  plugin: echo           # 对应 plugins/echo.py
  plugins_dir: ./plugins

# OpenAI Compatible - 真实模型
# qwen:
#   type: openai_compatible
#   base_url: https://api.example.com/v1
#   model: qwen-turbo
#   api_key_env: QWEN_API_KEY
```

### 自定义 Plugin

`mock-demo` 使用当前 `MockProvider` 已支持的 `fallback` 机制，在找不到显式 mapping 时直接返回 case 的 `expected_answer`，这样可以离线验证 run/status/show 主链路。

用户只需实现一个 `generate` 函数：

```python
# plugins/my_model.py
async def generate(query: str, config: dict, **kwargs) -> dict:
    # config 包含 providers.yaml 中的所有配置
    endpoint = config.get("endpoint", "http://localhost:8000")

    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{endpoint}/predict", json={"query": query})
        return {"output": resp.json()["answer"]}
```
