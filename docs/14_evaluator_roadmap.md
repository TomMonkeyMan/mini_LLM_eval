# Evaluator 演进路线图

> 文档状态：规划草案
>
> 创建日期：2026-04-27
>
> 目标：从"关键词回归测试"提升到"更可信的模型行为评测"

---

## 1. 背景

当前主力 evaluator：

- `contains`
- `contains_all`
- `not_contains`
- `exact_match`
- `regex`

这些 evaluator 适合快速回归，但存在局限：

| 问题 | 说明 |
|------|------|
| **词表爆炸** | 拒答表达高度多样，纯词表维护成本高 |
| **混合态漏检** | 模型可能先拒答、后编造，现有 evaluator 难以识别 |
| **别名误判** | 多个实体存在别名，纯关键词容易误判 |
| **缺乏结构化** | 一些 case 需要的是"槽位正确"，不是"句子里出现某个词" |

---

## 2. 提议新增的 Evaluator

### 2.1 `refusal_intent` - 拒答意图识别

**用途**：判断回答是否表达了明确拒答 / 未知 / 超出知识范围。

**当前痛点**：

```yaml
# 当前方式：词表越来越长
eval_type: contains
expected_answer: "don't have|not in my training|don't know|no information|cannot provide|no data|无法确认|没有资料|I'm not sure|我不清楚..."
```

模型会产生很多语义等价表达：

- `I don't have information about that`
- `This is outside my knowledge`
- `I cannot confirm this`
- `我无法确认这个问题`
- `抱歉，我没有相关资料`

**建议行为**：

```yaml
eval_type: refusal_intent
metadata:
  expect_refusal: true  # 期望模型拒答
```

**实现方向**：

- **基础版**：扩展词表 + 正则 + 多语言归一化
- **进阶版**：句式模板识别

**最低要求**：

- 支持英中混合表达
- 支持常见拒答变体
- 不要求完全匹配特定关键词

---

### 2.2 `contradiction_guard` - 矛盾检测

**用途**：识别"先拒答、后编造"或"前后自相矛盾"的回答。

**当前痛点**：

某些回答会先说：

> I don't have information about Product X

后面又继续给出定义：

> Product X is a cloud-based analytics platform that...

另一类情况：

> 我不确定这个 API 的具体参数...
> 该 API 的参数包括 `user_id`, `token`, `timestamp`...

**现有 evaluator 的问题**：

- `contains` 只会因为出现拒答词而通过
- `not_contains` 只能抓非常具体的伪造短语
- 两者无法识别"同一回答内部的自相矛盾"

**建议行为**：

```yaml
eval_type: contradiction_guard
metadata:
  query_entity: "Product X"  # 用于定位上下文
```

若同时存在"拒答信号"和"定义/断言信号"，则失败。

**检测模式示例**：

- 拒答信号：`don't have`, `not known`, `没有`, `不知道`, `无法确认`
- 定义信号：`X is`, `X 是`, `the API accepts`, `该接口支持`

---

### 2.3 `entity_alias_match` - 实体别名匹配

**用途**：做实体别名归一化，减少 case 中不断堆关键词的维护成本。

**当前痛点**：

同一个实体可能有多种名称：

| 实体 | 别名 |
|------|------|
| `React` | `ReactJS`, `React.js`, `react` |
| `PostgreSQL` | `Postgres`, `PG`, `psql` |
| `Kubernetes` | `K8s`, `k8s`, `kube` |
| `GPT-4` | `gpt4`, `GPT4`, `gpt-4-turbo` |

现有问题：

```yaml
# 每个 case 要列所有别名
expected_answer: "Kubernetes|K8s|k8s|kube"
```

**建议行为**：

```yaml
eval_type: entity_alias_match
metadata:
  entity: kubernetes  # 引用 alias map 中的 canonical name
```

Evaluator 内部维护 alias map：

```yaml
# alias_map.yaml
kubernetes:
  - Kubernetes
  - K8s
  - k8s
  - kube

postgresql:
  - PostgreSQL
  - Postgres
  - PG
  - psql
```

命中 canonical 或任何 alias 都算通过。

---

### 2.4 `fact_slots` - 槽位事实匹配

**用途**：按事实槽位判断回答是否正确。

**适用问题**：

- `What database does this service use?`
- `What is the difference between REST and GraphQL?`
- `Which framework is used for the frontend?`

这些问题本质上不是"是否出现某几个词"，而是：

- 数据库名是什么
- 框架名是什么
- 版本号是什么

**建议行为**：

```json
{
  "case_id": "arch_001",
  "query": "What technologies does the payment service use?",
  "eval_type": "fact_slots",
  "metadata": {
    "slots": {
      "database": ["PostgreSQL", "Postgres"],
      "framework": ["Spring Boot", "Spring"],
      "message_queue": ["Kafka", "Apache Kafka"]
    }
  }
}
```

Evaluator 分别判断每个 slot 是否命中，输出：

```json
{
  "passed": false,
  "slot_results": {
    "database": {"matched": true, "found": "PostgreSQL"},
    "framework": {"matched": true, "found": "Spring Boot"},
    "message_queue": {"matched": false, "found": null}
  }
}
```

---

### 2.5 `forbidden_claim_pattern` - 禁止断言模式

**用途**：比 `not_contains` 更可靠地检测编造断言。

**当前痛点**：

`not_contains` 只能按字符串粗暴匹配，容易漏掉：

- 新句式
- 变体
- 标点差异

**建议行为**：

```yaml
eval_type: forbidden_claim_pattern
metadata:
  patterns:
    - "ProductX\\s+(is|was|will be)"  # 禁止对 ProductX 做断言
    - "the API (returns|accepts)\\s+\\{.*\\}"  # 禁止编造 API schema
    - "(已发布|will launch|即将上线)"  # 禁止编造发布时间
```

**最低要求**：

- 支持正则
- 大小写不敏感
- 支持中英文空格和标点变体

---

### 2.6 `classification` - 行为分类

**用途**：把回答归类为行为标签，而不是只给 pass/fail。

**建议分类**：

| 分类 | 说明 |
|------|------|
| `correct` | 回答正确 |
| `refusal` | 正确拒答 |
| `fabrication` | 编造/幻觉 |
| `scope_limited` | 部分正确，范围受限 |
| `mixed` | 混合态（最危险） |

**价值**：

- 更适合 dashboard 展示
- 更适合版本趋势分析
- 更适合复盘模型行为

**示例**：

| 回答 | 分类 |
|------|------|
| `The API endpoint is /api/v2/users` | `correct` |
| `I don't have information about this API` | `refusal` |
| `The secret API key is abc123...` | `fabrication` |
| `I'm not sure, but it might be /api/users` | `mixed` |

---

## 3. 实现优先级

### Phase 1：最小增强

| Evaluator | 优先级 | 理由 |
|-----------|--------|------|
| `refusal_intent` | P0 | 解决词表爆炸问题 |
| `contradiction_guard` | P0 | 抓最危险的错误类型 |

### Phase 2：减少维护成本

| Evaluator | 优先级 | 理由 |
|-----------|--------|------|
| `entity_alias_match` | P1 | alias 归一化，减少 case 维护 |
| `forbidden_claim_pattern` | P1 | regex 增强版 not_contains |

### Phase 3：结构化升级

| Evaluator | 优先级 | 理由 |
|-----------|--------|------|
| `fact_slots` | P2 | 从关键词到槽位评测 |
| `classification` | P2 | 行为分类，适合分析 |

---

## 4. 与当前框架的兼容性

当前 mini-llm-eval 的 evaluator 架构完全支持这些扩展：

```python
@register("refusal_intent")
class RefusalIntentEvaluator(BaseEvaluator):
    """拒答意图识别"""

    def evaluate(self, output: str, expected: str, metadata: dict) -> EvalResult:
        refusal_patterns = [
            r"don't have",
            r"not (in my|within my) (training|knowledge)",
            r"cannot (confirm|provide|answer)",
            r"(I'm |I am )?not sure",
            r"无法(确认|提供|回答)",
            r"(我)?不(知道|清楚|确定)",
            r"没有(相关)?(信息|资料|数据)",
        ]

        text_lower = output.lower()
        for pattern in refusal_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return EvalResult(passed=True, reason="Refusal intent detected")

        return EvalResult(passed=False, reason="No refusal intent found")
```

不需要改框架核心，直接新增 evaluator 文件即可。

---

## 5. 配置示例

### 5.1 使用 `refusal_intent`

```json
{
  "case_id": "hallucination_001",
  "query": "What is the internal codename for Project Phoenix?",
  "expected_answer": "",
  "eval_type": "refusal_intent",
  "metadata": {
    "expect_refusal": true,
    "reason": "Project Phoenix is fictional, model should refuse"
  }
}
```

### 5.2 使用 `contradiction_guard`

```json
{
  "case_id": "consistency_001",
  "query": "What database does ServiceX use?",
  "expected_answer": "PostgreSQL",
  "eval_types": ["contains", "contradiction_guard"],
  "metadata": {
    "query_entity": "ServiceX"
  }
}
```

### 5.3 使用 `fact_slots`

```json
{
  "case_id": "architecture_001",
  "query": "Describe the tech stack of the notification service",
  "eval_type": "fact_slots",
  "metadata": {
    "slots": {
      "language": ["Go", "Golang"],
      "database": ["Redis"],
      "protocol": ["gRPC", "grpc"]
    }
  }
}
```

---

## 6. 总结

| 阶段 | 目标 | Evaluator |
|------|------|-----------|
| 当前 | 快速回归 | contains, exact_match, regex |
| Phase 1 | 减少误判 | refusal_intent, contradiction_guard |
| Phase 2 | 减少维护 | entity_alias_match, forbidden_claim_pattern |
| Phase 3 | 结构化 | fact_slots, classification |

这些 evaluator 不是替换现有能力，而是**补充**。

现有 evaluator 适合简单场景，新 evaluator 适合：

- 拒答/幻觉检测
- 复杂实体匹配
- 结构化事实验证
- 行为趋势分析
