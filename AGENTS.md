# AGENTS.md

AI 开发者（Codex、Claude 等）入口指引。

---

## 开发前必读

1. **RULES.md** - 行为准则（Think Before Coding, Simplicity First, Surgical Changes）
2. **DEVELOPMENT.md** - 代码标准（`__slots__`、命名规范、TypedDict、docstring）

---

## 项目结构

```
src/mini_llm_eval/
├── core/           # 配置、异常、常量
├── models/         # Pydantic schemas
├── evaluators/     # 评估器（规则类）
├── providers/      # 模型调用（Mock、OpenAI、Plugin）
├── services/       # 业务逻辑（Executor、RunService）
├── db/             # 存储（SQLite、FileStorage）
└── cli/            # 命令行入口
```

---

## 关键设计决策

| 组件 | 谁写 | 说明 |
|------|------|------|
| **Provider** | 用户 | Plugin 即插即拔，用户实现 `async def generate()` |
| **Evaluator** | 产品工程师 | 内置规则，用户通过 `eval_types` 选择 |

---

## 文档索引

| 文档 | 内容 |
|------|------|
| `docs/7_v1_implementation_spec.md` | v1 实现规格 |
| `docs/8_v2_design.md` | v2 队列架构设计 |
| `reviews/` | 代码 review 记录 |
| `codex_progress.md` | 开发进度 |

---

## 快速检查清单

写代码前确认：
- [ ] 读了 `RULES.md`？
- [ ] 读了 `DEVELOPMENT.md`？
- [ ] 非 Pydantic 类有 `__slots__`？
- [ ] 返回 dict 用 TypedDict？
- [ ] 资源用 context manager 管理？
