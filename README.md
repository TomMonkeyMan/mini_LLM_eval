# Mini LLM Eval

一个面向 LLM 回归测试的最小可用评测运行器。

当前实现已经支持从 CLI 端到端执行一次评测任务：

- 加载本地评测集
- 调用 Provider
- 执行多个 Evaluator
- 持久化到 SQLite
- 输出 `case_results.jsonl` 和 `meta.json`
- 支持 `resume`

权威实现规格见 [docs/7_v1_implementation_spec.md](docs/7_v1_implementation_spec.md)。

## 当前能力

- 数据集加载
  - 支持 `.jsonl`
  - 支持 `.json`
  - 支持 `eval_type -> eval_types` 兼容转换
- Provider
  - `mock`
  - `openai_compatible`
  - `plugin`
- Evaluator
  - `exact_match`
- `contains`
- `contains_all`
- `regex`
- `json_field`
- `length_range`
- `not_contains`
- `numeric_tolerance`
- 执行模型
  - Provider 并发执行
  - Evaluator 内联执行
  - writer queue 串行写入
- 持久化
  - SQLite: `runs / case_results / state_logs`
  - 文件产物: `case_results.jsonl / meta.json`
- CLI
  - `run`
  - `resume`
  - `status`
  - `list`
  - `show`
  - `cancel`

## 项目结构

```text
mini_LLM_eval/
├── config.yaml
├── providers.yaml
├── data/
│   └── eval_cases.jsonl
├── outputs/
├── reviews/
├── src/mini_llm_eval/
│   ├── cli/
│   ├── core/
│   ├── db/
│   ├── evaluators/
│   ├── models/
│   ├── providers/
│   └── services/
└── tests/
```

## 环境准备

### 1. Conda 环境

如果还没有环境：

```bash
conda create -y -n mini-llm-eval python=3.11
conda activate mini-llm-eval
```

### 2. 安装项目

开发模式安装：

```bash
python -m pip install -e ".[dev]"
```

安装完成后可直接使用：

```bash
mini-llm-eval --help
```

## 配置文件

### `config.yaml`

项目级配置：

```yaml
timeout_ms: 30000
max_retries: 3
concurrency: 4
log_level: "INFO"
output_dir: "./outputs"
evaluators_package: "mini_llm_eval.evaluators"
defaults:
  evaluators:
    - contains
```

主要字段：

- `timeout_ms`: Provider 调用超时
- `max_retries`: Provider 重试次数
- `concurrency`: 默认 Provider 并发数
- `log_level`: 运行时日志级别，支持标准 Python logging level
- `output_dir`: 输出目录
- `evaluators_package`: Evaluator 自动发现包路径

### `providers.yaml`

Provider 实例配置：

```yaml
mock-default:
  type: mock
  mode: mapping
  mapping_file: ./data/mock_responses.json

example-openai-compatible:
  type: openai_compatible
  base_url: ${MODEL_BASE_URL}
  model: example-model
  api_key_env: MODEL_API_KEY

example-plugin-provider:
  type: plugin
  plugin: simple_qa
  plugins_dir: ./plugins
  endpoint: http://localhost:8000/predict
```

说明：

- `mock`: 本地开发和无 API key 场景
- `openai_compatible`: 远程模型服务，默认通过 `httpx.AsyncClient` 调用
- `plugin`: 自定义可插拔 Provider

## 数据集格式

推荐使用 JSONL。

每条 case 至少包含：

- `case_id`
- `query`
- `expected_answer`
- `tags`
- `difficulty`
- `eval_type` 或 `eval_types`
- `metadata`

示例：

```json
{
  "case_id": "diag_001",
  "query": "车辆出现高压互锁告警时，优先检查哪些信号？",
  "expected_answer": "HVIL|连接器|DTC",
  "tags": ["diagnostics", "knowledge"],
  "difficulty": "medium",
  "eval_type": "contains",
  "metadata": {"locale": "zh-CN"}
}
```

项目里已提供示例数据集：

- [data/eval_cases.jsonl](/Users/tiashi/Desktop/mini_LLM_eval/data/eval_cases.jsonl)

## CLI 使用方式

### 1. 运行一次评测

```bash
mini-llm-eval run \
  --dataset data/eval_cases.jsonl \
  --provider mock-default \
  --run-id demo-run \
  --config config.yaml \
  --providers providers.yaml
```

可选参数：

- `--concurrency`
- `--timeout`
- `--db-path`

### 2. 恢复一次评测

```bash
mini-llm-eval resume demo-run \
  --config config.yaml \
  --providers providers.yaml
```

### 3. 查看状态

```bash
mini-llm-eval status demo-run \
  --config config.yaml
```

### 4. 帮助

```bash
mini-llm-eval --help
mini-llm-eval run --help
```

### 5. 列最近 runs

```bash
mini-llm-eval list --limit 10 --config config.yaml
```

### 6. 查看单次 run 详情

```bash
mini-llm-eval show demo-run --config config.yaml
mini-llm-eval show demo-run --cases --failed-only --config config.yaml
```

### 7. 取消 pending run

```bash
mini-llm-eval cancel demo-run --config config.yaml --providers providers.yaml
```

说明：

- 当前 v1 只可靠支持取消 `PENDING` run
- 已经进入 `RUNNING` 的 run 暂不支持主动中断

## 输出结果

默认输出到 `output_dir`。

## 日志

CLI 运行时会输出 JSON line 日志到标准错误，适合后续接到文件、采集器或日志平台。

当前已覆盖的关键事件包括：

- CLI 命令开始 / 完成 / 失败
- run 开始 / 完成 / 失败 / resume
- provider 重试、超时、错误
- artifact fallback 写入告警

一次 run 完成后会生成：

```text
outputs/
└── <run_id>/
    ├── case_results.jsonl
    └── meta.json
```

并且 SQLite 中会写入：

- `runs`
- `case_results`
- `state_logs`

默认数据库路径：

```text
<output_dir>/eval.db
```

## Provider 使用说明

### 1. Mock Provider

适合：

- 本地开发
- 无外部 API key
- 单元测试

示例：

```yaml
mock-default:
  type: mock
  mapping_file: ./data/mock_responses.json
  fallback:
    enabled: true
    success_rate: 0.8
    default_response: "default answer"
  latency:
    min_ms: 10
    max_ms: 30
```

### 2. OpenAI-Compatible Provider

适合：

- OpenAI API
- vLLM / LiteLLM / OpenAI-compatible 网关
- 自己部署但兼容 OpenAI 接口的模型服务

示例：

```yaml
my-vllm:
  type: openai_compatible
  base_url: ${MY_VLLM_BASE_URL}
  model: my-model
  api_key_env: MY_VLLM_API_KEY
```

### 3. Plugin Provider

适合：

- 请求 payload 与 OpenAI-compatible 不同
- 响应格式自定义
- 想要“放一个 Python 文件就能接入”

配置示例：

```yaml
my-custom-provider:
  type: plugin
  plugin: simple_qa
  plugins_dir: ./plugins
  endpoint: http://localhost:8000/predict
```

插件文件示例：

```python
# plugins/simple_qa.py
async def generate(query: str, config: dict, **kwargs) -> dict:
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.post(
            config["endpoint"],
            json={"question": query},
        )
        payload = response.json()
        return {
            "output": payload["answer"],
        }
```

插件约定：

- 文件位于 `plugins_dir`
- 模块中必须有 `async def generate(...)`
- 返回值必须至少包含 `output`

可选返回字段：

- `status`
- `error`
- `token_usage`
- `cost`
- `model_name`
- `request_id`
- `latency_ms`

## Evaluator 使用说明

每条 case 可以指定：

- `eval_type`
- 或 `eval_types`

例如：

```json
{
  "case_id": "tool_001",
  "query": "Should the system call sql_query or doc_search for a DB question?",
  "expected_answer": "sql_query",
  "eval_type": "exact_match"
}
```

或者：

```json
{
  "case_id": "case_multi",
  "query": "Return a JSON tool selection",
  "expected_answer": "sql_query",
  "eval_types": ["json_field", "contains"]
}
```

特殊值：

- `["all"]`: 使用所有已注册的 Evaluator

## 测试

运行当前测试集：

```bash
python -m pytest
```

当前实现已覆盖：

- config
- schemas
- evaluators
- dataset
- providers
- storage
- services
- CLI

## 当前限制

当前版本仍有这些边界：

- 不包含实验对比功能
- 不包含 HTTP API
- 不包含 Web UI
- 不包含 LLM Judge
- SQLite 仍是单机版本
- Provider 自定义目前是“plugin 文件”级别，不是完整插件市场

## AI 工具使用说明

本项目开发过程中使用了 AI 辅助工具：

- Codex
- Claude（用于 review）

AI 主要帮助了：

- 设计文档收敛
- 代码实现
- 测试补全
- review 反馈整理

关键设计决定由项目实现者主导确定，包括：

- v1 范围收敛
- run / case 状态语义统一
- Provider 配置驱动
- `plugin` provider 扩展方向
- `run queue + case concurrency + writer queue` 执行模型

验证方式：

- 单元测试
- 集成式 CLI 测试
- review 文档记录

## 参考文档

- [docs/7_v1_implementation_spec.md](docs/7_v1_implementation_spec.md)
- [docs/6_version1_dev_plan.md](docs/6_version1_dev_plan.md)
- [codex_progress.md](codex_progress.md)
