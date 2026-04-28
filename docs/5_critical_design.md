# Mini LLM Eval 关键设计决策

> 说明：本文件保留关键设计讨论结果，但 v1 实现落地请以 `docs/7_v1_implementation_spec.md` 为准。

> 本文档记录最终敲定的核心设计决策，作为实现的权威依据。
>
> 状态说明：✅ 已确定 | ⬜ 待讨论（有建议）
>
> 归属说明：🧑 tianyu 提出 | 🤖 Claude 建议 | 🤝 共同讨论

---

## 设计归属总览

| 决策 | 归属 | 说明 |
|------|------|------|
| Evaluator 装饰器 + 自动发现 | 🤝 | Claude 提供方案对比，tianyu 选定 |
| 不支持 CLI --evaluators 覆盖 | 🧑 | tianyu 提出：数据应落在 cases.jsonl |
| 多 Evaluator 独立执行不合并 | 🧑 | tianyu 提出：合并是报表层职责 |
| MVP 不需要 score | 🧑 | tianyu 指出原始需求没有 score |
| 大文本存储：索引 + 文件分离 | 🧑 | tianyu 提出：后续可迁移 ES/S3 |
| 断点恢复需要 run_id | 🧑 | tianyu 提出：类比对话 session id |
| 写入失败降级到 /tmp | 🧑 | tianyu 提出 |
| Provider 配置驱动（非插件注册） | 🧑 | tianyu 洞察：Provider 和 Evaluator 不是一个 level |
| Provider 单独配置文件 | 🧑 | tianyu 提出 |
| CLI + API 都支持 | 🧑 | tianyu 提出：核心写好封装就行 |
| 错误处理分类与降级策略 | 🤝 | 共同讨论确定 |
| Evaluator 配置层级 | 🤖 | Claude 建议，tianyu 确认 |

---

## 1. Evaluator 插件机制 ✅

### 1.1 决策总览

| 问题 | 决策 | 理由 |
|------|------|------|
| 注册方式 | 装饰器 + 自动发现 | 新增只需加装饰器，简洁 Pythonic |
| 配置引用 | 字符串名称 | 配置文件友好，支持运行时选择 |
| 加载时机 | 启动时自动发现 | 无需手动维护导入列表 |

### 1.2 注册机制实现

```python
# src/evaluators/registry.py
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
    """启动时自动发现并加载所有 Evaluator 模块

    package_name: 从配置读取，默认 None 时使用 config.evaluators_package
    """
    if package_name is None:
        from src.core.config import get_config
        package_name = get_config().evaluators_package  # 可配置

    package = importlib.import_module(package_name)
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        if module_name not in ("base", "registry"):
            importlib.import_module(f"{package_name}.{module_name}")
```

### 1.3 新增 Evaluator 流程

```
1. 创建文件 src/evaluators/my_new_eval.py
2. 继承 BaseEvaluator
3. 加上 @register("my_new_eval") 装饰器
4. 完成！无需修改其他代码
```

---

## 2. Evaluator 选择与配置 ✅

### 2.1 决策总览

| 问题 | 决策 | 理由 |
|------|------|------|
| 选择来源 | Case 的 `eval_types` 字段 | 数据与配置统一，可追溯 |
| 全局默认 | config.yaml 可配置 | case 未指定时的 fallback |
| CLI 覆盖 | **不支持** | 简化设计，避免结果不可复现 |

### 2.2 配置层级 (优先级从高到低)

```
1. Case 级别定义          eval_types: ["contains", "exact_match"]
2. 全局配置 (config.yaml) defaults.evaluators: ["contains"]
3. 系统默认               ["contains"]
```

### 2.3 CLI 使用示例

```bash
# evaluator 由 case 的 eval_types 决定
python -m src.cli.main run --dataset data/cases.jsonl --provider qwen
```

如需使用不同 evaluator，修改 `cases.jsonl` 或生成新数据集。

---

## 3. LLM Judge Evaluator ✅

### 3.1 决策

| 问题 | 决策 | 理由 |
|------|------|------|
| Provider 配置 | **单独配置** | 可用更便宜/更快的模型做评测 |
| 实现时机 | **MVP 后** | 先用规则类 evaluator |

### 3.2 MVP Evaluator 范围

| Evaluator | 描述 | MVP |
|-----------|------|-----|
| `exact_match` | 精确匹配 | ✅ |
| `contains` | 包含关键词 | ✅ |
| `regex` | 正则匹配 | ✅ |
| `json_field` | JSON 字段匹配 | ✅ |
| `numeric_tolerance` | 数值容差 | ✅ |
| `llm_judge` | LLM 评分 | ❌ MVP 后 |

---

## 4. 待讨论问题

### 4.1 多 Evaluator 执行 ✅

**决策**：
1. `eval_types` 支持数组：`["contains", "regex"]`
2. 支持 `"all"` 表示使用所有已注册的 evaluator
3. 每个 evaluator 独立执行，结果独立存储，**不做合并**
4. 聚合统计是报表层职责，用数据库查询实现

**结果结构示例**：
```python
{
  "case_id": "001",
  "eval_results": {
    "contains": {"passed": True, "reason": "found keyword '检查'"},
    "regex": {"passed": False, "reason": "pattern not matched"}
  }
}
```

---

### 4.2 错误处理架构 ✅

**核心原则**：单条 case 失败不影响整体运行（来自原始需求）

**错误分类与处理**：

| 错误类型 | 处理方式 | 备注 |
|---------|---------|------|
| **所有错误** | 先记录日志 | 基础要求 |
| **用户侧错误** | 高亮提示 | 输入格式错误、字段缺失等，后续可发邮件通知 |
| **provider 错误** | 重试（按 max_retries），失败记录 | 超时、rate limit、API 错误 |
| **evaluator 异常** | 标记 `evaluator_error`，记录 trace | 需要在结果中体现是 evaluator 的问题 |
| **单个 case 重试失败** | 结果里标明重试状态 | 不影响其他 case |
| **结果文件写入失败** | 降级到 `/tmp`，同时 stdout 告知用户 | 保证结果不丢失 |

**FATAL 错误**（中断整个 run）：
- 数据集文件不存在
- Provider 初始化失败（如 API key 无效）

**Run 状态**：
- 部分 case 失败 → run 状态为 `SUCCEEDED`，结果记录失败数

---

### 4.3 存储设计 ✅

**1. 大文本存储：索引 + 文件分离**
- 数据库是运行态和元数据的权威来源
- 文件产物用于导出和后续离线分析
- 后续可迁移到 ES/OpenSearch/S3

```
outputs/
  {run_id}/
    case_results.jsonl
    meta.json
```

**2. JSON 字段**：使用 SQLite JSON 列，灵活不用频繁改 schema

其中：
- `case_results.jsonl` 保存 case 级详细结果
- `meta.json` 是 run 完成后导出的便携快照
- 运行中若 DB 与 `meta.json` 不一致，以 DB 为准

**3. 断点恢复：run_id + status**

每次提交生成 `run_id`，case 结果实时写入并记录 `status`。

```bash
# 首次提交，系统生成 run_id
python run_eval.py --dataset data/cases.jsonl --provider qwen
# 输出：Run started: run_20240422_abc123

# 中断后恢复
python run_eval.py --resume run_20240422_abc123
# 查询已完成的 case，只跑剩下的

# 或用户指定 run_id
python run_eval.py --dataset ... --run-id my_experiment_v1
```

**Run 状态机（参考 raw requirement 方向 A）：**

```
提交 job → 队列 (PENDING) → Worker 取出 (RUNNING) → 完成 (SUCCEEDED/FAILED)
                                    ↓
                               取消 (CANCELLED)
```

| 状态 | 说明 |
|------|------|
| PENDING | 任务已创建，进入队列，等待执行 |
| RUNNING | Worker 取出，执行中 |
| SUCCEEDED | 成功完成（部分 case 失败也算 SUCCEEDED） |
| FAILED | FATAL 错误导致整体失败 |
| CANCELLED | 用户取消或中断 |

**参考系统：**

| 系统 | 状态设计 |
|------|---------|
| **Prefect** | pending → running → completed/failed/cancelled |
| **Temporal** | scheduled → running → completed/failed/terminated |
| **Celery** | pending → started → success/failure/revoked |

**MVP 实现思路：**

| 阶段 | 队列实现 | 说明 |
|------|---------|------|
| **MVP** | SQLite 表 + asyncio.Queue | 单进程，表即队列 |
| **后续** | Redis Queue / Celery | 分布式，多 Worker |

**SQLite 表作为队列：**
```sql
-- 取待执行任务
SELECT * FROM runs WHERE status = 'pending' ORDER BY created_at LIMIT 1;

-- 开始执行
UPDATE runs SET status = 'running', started_at = CURRENT_TIMESTAMP WHERE run_id = ?;

-- 完成
UPDATE runs SET status = 'succeeded', finished_at = CURRENT_TIMESTAMP WHERE run_id = ?;
```

**表结构示意：**
```sql
-- runs 表
run_id TEXT PRIMARY KEY,
dataset_path TEXT,
provider_name TEXT,
model_config JSON,
status TEXT,  -- 'pending', 'running', 'succeeded', 'failed', 'cancelled'
created_at TIMESTAMP,
updated_at TIMESTAMP

-- case_results 表
id INTEGER PRIMARY KEY,
run_id TEXT,
case_id TEXT,
status TEXT,  -- 'pending', 'completed', 'error'
output_path TEXT,  -- 指向本地文件
eval_results JSON,  -- 各 evaluator 的 passed/reason
latency_ms INTEGER,
error TEXT,
created_at TIMESTAMP,
FOREIGN KEY (run_id) REFERENCES runs(run_id)
```

---

### 4.4 配置管理 ✅

**配置分离：**

| 配置文件 | 内容 | 说明 |
|---------|------|------|
| `config.yaml` | 项目级配置 | timeout、retries、concurrency、输出目录 |
| `providers.yaml` | Provider 配置 | 各模型的 type、base_url、model 等 |

**决策：**
- 配置文件查找顺序：`--config` 指定 > `./config.yaml` > `~/.mini_llm_eval/config.yaml`
- 敏感配置（API key）：**只允许环境变量**，防止误提交
- 动态配置：**不支持**，MVP 简化

**配置示例：**

```yaml
# config.yaml - 项目级
timeout_ms: 30000
max_retries: 3
concurrency: 4
output_dir: "./outputs"
defaults:
  evaluators: ["contains"]
```

```yaml
# providers.yaml - Provider 定义
qwen:
  type: "openai_compatible"
  base_url: "${QWEN_BASE_URL}"
  model: "qwen-plus"
  # api_key 从 QWEN_API_KEY 环境变量读

mock:
  type: "mock"
  # 无需额外配置
```

**Evaluator 配置**：MVP 不需要，后续 LLM Judge 再加

---

### 4.5 缓存策略 ✅

**决策**：MVP 不实现缓存，后续按需添加。

原始需求未要求缓存功能。

---

---

## 5. Provider 设计 ✅

### 5.1 Provider vs Evaluator 设计差异

| 对比 | Evaluator | Provider |
|------|-----------|----------|
| **性质** | 规则/逻辑插件 | 模型服务客户端 |
| **变化频率** | 用户经常自定义 | 相对固定 |
| **实现** | 纯 Python 逻辑 | HTTP 请求封装 |
| **扩展方式** | 装饰器注册，随插随拔 | **配置驱动** |

### 5.2 决策：Provider 用配置驱动

Provider 不需要插件注册机制，通过配置文件定义，系统根据 `type` 加载对应实现。

```yaml
# providers.yaml
qwen:
  type: "openai_compatible"      # 内置类型
  base_url: "${QWEN_BASE_URL}"
  model: "qwen-plus"

gpt4:
  type: "openai_compatible"
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"

claude:
  type: "anthropic"
  model: "claude-3-opus"

mock:
  type: "mock"
```

### 5.3 内置 Provider 类型

| type | 说明 | MVP |
|------|------|-----|
| `mock` | 测试用，无需 API | ✅ |
| `openai_compatible` | OpenAI 兼容 API（覆盖 90% 场景） | ✅ |
| `anthropic` | Anthropic API | ❌ 后续 |

### 5.4 高级：自定义 Provider（后续）

```yaml
my_custom:
  type: "custom"
  class: "my_project.providers.MyProvider"  # 自定义类路径
```

---

## 6. CLI + API 架构 ✅

### 6.1 分层设计

```
┌─────────────┐  ┌─────────────┐
│     CLI     │  │   FastAPI   │
│   (typer)   │  │   (HTTP)    │
└──────┬──────┘  └──────┬──────┘
       │                │
       └───────┬────────┘
               ▼
       ┌──────────────┐
       │   Service    │  ← 核心逻辑，纯 Python
       │    Layer     │
       └──────────────┘
               │
       ┌───────┴───────┐
       ▼               ▼
┌──────────────┐ ┌──────────────┐
│   Provider   │ │  Evaluator   │
└──────────────┘ └──────────────┘
```

### 6.2 决策

- **Service Layer**：核心逻辑，不依赖 CLI 或 HTTP，纯 Python 函数/类
- **CLI**：本地开发用，调用 Service Layer
- **API**：HTTP 接口，同样调用 Service Layer

### 6.3 实现优先级

1. **Service Layer**（核心）- 先写
2. **CLI 封装**（typer + rich）- 本地开发
3. **API 封装**（FastAPI）- 后续或同时

---

## 讨论记录

### Session 1 - 2024-04-22

**参与者**：tianyu, Claude

**确定内容**：
1. Evaluator 注册：装饰器 + 自动发现
2. Evaluator 选择：Case > Config > 默认（不支持 CLI 覆盖）
3. LLM Judge：单独配置 Provider，MVP 后实现
4. 多 Evaluator 执行：独立执行，独立存储，不合并
5. 错误处理：单条失败不影响整体，写入失败降级到 /tmp
6. 存储设计：大文本存文件，DB 存索引，run_id + status 断点恢复
7. 配置管理：config.yaml + providers.yaml 分离，API key 只用环境变量
8. 缓存：MVP 不做

### Session 2 - 2024-04-22

**参与者**：tianyu, Claude

**确定内容**：
1. Provider 设计：配置驱动（不是插件注册），内置 mock + openai_compatible
2. CLI + API 架构：Service Layer 为核心，CLI/API 都是上层封装

**所有关键设计已确定，可以开始实现。**
