# Artifact Store 与服务层架构设计

> 文档状态：架构设计草案
>
> 创建日期：2026-04-27
>
> 目标：定义 Execution Layer 与 Analysis Layer 的分离边界，为后续 Web 服务演进提供扩展路径

---

## 1. 问题背景

当前 v1 实现中，`compare` 命令依赖 `--config` 参数来定位 `outputs/` 目录。这种设计存在以下问题：

1. **概念耦合**：分析层不应依赖运行时配置
2. **扩展受限**：后续 Web 服务需要从 S3/DB 读取产物，而非本地文件
3. **职责混淆**：compare 是分析操作，不是执行操作

---

## 2. 层次分离原则

### 2.1 两层架构

```
┌─────────────────────────────────────────────────────────┐
│                    Execution Layer                       │
│  (run, resume, cancel)                                   │
│                                                          │
│  依赖：config.yaml, providers.yaml, dataset files        │
│  职责：执行评测、生成产物、持久化结果                      │
│  输出：artifacts (meta.json, case_results.jsonl)         │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼ artifacts
┌─────────────────────────────────────────────────────────┐
│                    Analysis Layer                        │
│  (compare, report, query)                                │
│                                                          │
│  依赖：artifacts (meta.json, case_results.jsonl)         │
│  职责：读取产物、对比分析、生成报告                        │
│  输出：comparison results, reports                       │
└─────────────────────────────────────────────────────────┘
```

### 2.2 依赖规则

| 层次 | 依赖 | 不依赖 |
|------|------|--------|
| Execution Layer | config.yaml, providers.yaml, dataset | - |
| Analysis Layer | artifacts (files/S3/DB) | config.yaml, providers.yaml |

关键原则：**Analysis Layer 只依赖产物，不依赖运行时配置**

---

## 3. ArtifactStore 抽象

### 3.1 接口定义

```python
from abc import ABC, abstractmethod
from typing import Protocol
from mini_llm_eval.core.types import RunMeta, CaseResultArtifact

class ArtifactStore(Protocol):
    """产物存储抽象接口"""

    async def get_meta(self, run_id: str) -> RunMeta:
        """读取 run 的 meta.json"""
        ...

    async def get_case_results(self, run_id: str) -> list[CaseResultArtifact]:
        """读取 run 的 case_results.jsonl"""
        ...

    async def list_runs(self, limit: int = 10) -> list[str]:
        """列出可用的 run_id"""
        ...

    async def run_exists(self, run_id: str) -> bool:
        """检查 run 是否存在"""
        ...
```

### 3.2 实现类型

```
ArtifactStore (Protocol)
    │
    ├── FileStore        # 本地文件系统 (outputs/{run_id}/)
    │
    ├── S3Store          # S3/MinIO 远程存储
    │
    └── DBStore          # 直接从 SQLite/PostgreSQL 读取
```

### 3.3 FileStore 实现示例

```python
class FileStore:
    """基于本地文件系统的产物存储"""

    def __init__(self, outputs_dir: str = "outputs") -> None:
        self.outputs_dir = Path(outputs_dir)

    async def get_meta(self, run_id: str) -> RunMeta:
        meta_path = self.outputs_dir / run_id / "meta.json"
        if not meta_path.exists():
            raise ArtifactNotFoundError(f"meta.json not found for {run_id}")
        return json.loads(meta_path.read_text())

    async def get_case_results(self, run_id: str) -> list[CaseResultArtifact]:
        results_path = self.outputs_dir / run_id / "case_results.jsonl"
        if not results_path.exists():
            raise ArtifactNotFoundError(f"case_results.jsonl not found for {run_id}")
        results = []
        for line in results_path.read_text().strip().split("\n"):
            if line:
                results.append(json.loads(line))
        return results

    async def list_runs(self, limit: int = 10) -> list[str]:
        runs = []
        for d in sorted(self.outputs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if d.is_dir() and (d / "meta.json").exists():
                runs.append(d.name)
                if len(runs) >= limit:
                    break
        return runs

    async def run_exists(self, run_id: str) -> bool:
        return (self.outputs_dir / run_id / "meta.json").exists()
```

---

## 4. CompareService 重构

### 4.1 当前实现 (v1)

```python
# 当前：compare 依赖 outputs_dir 配置
class Comparator:
    def __init__(self, outputs_dir: str) -> None:
        self.outputs_dir = Path(outputs_dir)

    async def compare(self, base_run_id: str, candidate_run_id: str) -> CompareResult:
        base_meta = self._load_meta(base_run_id)
        candidate_meta = self._load_meta(candidate_run_id)
        # ...
```

### 4.2 目标实现 (v1.1+)

```python
# 目标：compare 依赖 ArtifactStore 抽象
class CompareService:
    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    async def compare(self, base_run_id: str, candidate_run_id: str) -> CompareResult:
        base_meta = await self.store.get_meta(base_run_id)
        candidate_meta = await self.store.get_meta(candidate_run_id)
        base_cases = await self.store.get_case_results(base_run_id)
        candidate_cases = await self.store.get_case_results(candidate_run_id)
        # ...
```

### 4.3 CLI 适配

```python
# CLI 层负责构造具体的 Store 实现
@app.command()
def compare(
    base: str,
    candidate: str,
    outputs_dir: str = "outputs",  # 直接指定产物目录，而非 config
):
    store = FileStore(outputs_dir)
    service = CompareService(store)
    result = asyncio.run(service.compare(base, candidate))
    # ...
```

---

## 5. Web 服务演进路径

### 5.1 CLI 阶段 (当前 v1)

```
User -> CLI -> FileStore -> local outputs/
```

### 5.2 单机 Web 服务 (v2)

```
User -> FastAPI -> CompareService -> FileStore -> local outputs/
                -> RunService -> Database + FileStorage
```

### 5.3 分布式服务 (v3+)

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Web UI    │──────│  API Server │──────│  S3 Store   │
└─────────────┘      └─────────────┘      └─────────────┘
                            │
                     ┌──────┴──────┐
                     │             │
              ┌──────▼──────┐ ┌────▼────┐
              │ PostgreSQL  │ │ Workers │
              └─────────────┘ └─────────┘
```

Analysis Layer 通过 `S3Store` 读取产物：

```python
# API 服务中
@router.get("/api/compare")
async def compare_runs(base: str, candidate: str):
    store = S3Store(bucket="eval-artifacts", prefix="runs/")
    service = CompareService(store)
    return await service.compare(base, candidate)
```

---

## 6. 产物格式契约

### 6.1 meta.json

```json
{
  "run_id": "run_abc123",
  "dataset_path": "data/eval_cases.jsonl",
  "provider_name": "openai",
  "status": "succeeded",
  "summary": {
    "total": 100,
    "passed": 95,
    "failed": 5,
    "pass_rate": 0.95,
    "avg_latency_ms": 234.5
  },
  "created_at": "2026-04-27T10:00:00Z",
  "started_at": "2026-04-27T10:00:01Z",
  "finished_at": "2026-04-27T10:05:00Z"
}
```

### 6.2 case_results.jsonl

每行一个 JSON 对象：

```json
{"case_id": "case_001", "case_status": "completed", "passed": true, "eval_results": {...}, "latency_ms": 123.4}
{"case_id": "case_002", "case_status": "completed", "passed": false, "eval_results": {...}, "latency_ms": 456.7}
```

### 6.3 稳定性承诺

以下字段在 v1 中冻结，后续版本保持向后兼容：

| 文件 | 稳定字段 |
|------|----------|
| meta.json | run_id, status, summary.total, summary.passed, summary.failed, summary.pass_rate |
| case_results.jsonl | case_id, case_status, passed, eval_results, latency_ms |

---

## 7. 实现优先级

### 7.1 v1.1 (近期)

- [ ] 定义 `ArtifactStore` Protocol
- [ ] 实现 `FileStore`
- [ ] 重构 `Comparator` 为 `CompareService`
- [ ] CLI compare 改为直接接受 `--outputs-dir` 而非 `--config`

### 7.2 v2 (中期)

- [ ] 实现 `DBStore` (直接从 SQLite 读取)
- [ ] FastAPI 集成 `CompareService`
- [ ] 添加 `ReportService` 依赖同一 `ArtifactStore`

### 7.3 v3+ (远期)

- [ ] 实现 `S3Store`
- [ ] 支持跨区域产物读取
- [ ] 产物归档与清理策略

---

## 8. 设计决策记录

### 8.1 为什么不让 Analysis Layer 依赖 config？

1. **解耦**：分析操作与执行配置无关
2. **可移植**：产物可以从任何来源读取
3. **可测试**：可以用 mock store 测试分析逻辑
4. **可扩展**：后续支持 S3/DB 无需修改分析代码

### 8.2 为什么使用 Protocol 而非 ABC？

1. **结构化子类型**：不强制继承关系
2. **Duck typing**：任何实现接口的类都可用
3. **测试友好**：可以用简单的 mock 对象

### 8.3 为什么产物格式是 JSON/JSONL？

1. **人类可读**：便于调试和手动检查
2. **工具友好**：可用 jq 等工具处理
3. **流式写入**：JSONL 支持增量追加
4. **跨语言**：任何语言都能解析

---

## 9. 总结

本设计将系统分为 Execution Layer 和 Analysis Layer：

- **Execution Layer**：依赖配置，执行评测，生成产物
- **Analysis Layer**：依赖产物，提供分析服务

通过 `ArtifactStore` 抽象，Analysis Layer 可以从多种来源读取产物，为后续 Web 服务演进提供清晰的扩展路径。

当前 v1 可以先用 `FileStore` 实现，CLI compare 直接接受 `--outputs-dir` 参数，避免不必要的 config 依赖。
