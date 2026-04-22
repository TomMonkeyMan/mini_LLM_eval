# LLM Eval 相关开源项目参考

## 顶级框架（高星项目）

| 项目 | Stars | 描述 |
|------|-------|------|
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | 20.4k | Prompt/Agent/RAG 测试，支持 CI/CD，OpenAI/Anthropic 在用 |
| [openai/evals](https://github.com/openai/evals) | 18.3k | OpenAI 官方评测框架 |
| [raga-ai-hub/RagaAI-Catalyst](https://github.com/raga-ai-hub/RagaAI-Catalyst) | 16.1k | Agent 可观测性与评测框架 |
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) | 14.9k | Python LLM 评测框架，多种评测指标 |
| [vibrantlabsai/ragas](https://github.com/vibrantlabsai/ragas) | 13.6k | RAG 系统评测专用框架 |
| [Marker-Inc-Korea/AutoRAG](https://github.com/Marker-Inc-Korea/AutoRAG) | 4.7k | RAG 评测与自动优化 |
| [ianarawjo/ChainForge](https://github.com/ianarawjo/ChainForge) | 3.0k | 可视化 Prompt 批量测试 |
| [modelscope/evalscope](https://github.com/modelscope/evalscope) | 2.7k | 阿里大模型评测框架 |

## 中型项目

| 项目 | Stars | 描述 |
|------|-------|------|
| [neptune-ai/neptune-client](https://github.com/neptune-ai/neptune-client) | 622 | 实验追踪器 |
| [BlazeUp-AI/Observal](https://github.com/BlazeUp-AI/Observal) | 572 | Agent 可观测性 + 评测 |
| [kolenaIO/autoarena](https://github.com/kolenaIO/autoarena) | 108 | LLM/RAG head-to-head 评估 |
| [litmux4ai/litmux](https://github.com/litmux4ai/litmux) | 100 | AI 单元测试，成本优化 |
| [IBM/vakra](https://github.com/IBM/vakra) | 59 | 多跳工具调用 Benchmark |

## 轻量级项目

| 项目 | Stars | 描述 |
|------|-------|------|
| [fastxyz/skill-optimizer](https://github.com/fastxyz/skill-optimizer) | 38 | 工具调用 Benchmark |
| [2501Pr0ject/RAGnarok-AI](https://github.com/2501Pr0ject/RAGnarok-AI) | 15 | 本地 RAG 评测，无需 API Key |
| [tomerhakak/agentprobe](https://github.com/tomerhakak/agentprobe) | 8 | pytest 风格 Agent 测试 |
| [aviralgarg05/agentunit](https://github.com/aviralgarg05/agentunit) | 7 | pytest 风格 RAG 评测 |

## MVP 重点参考

1. **[promptfoo](https://github.com/promptfoo/promptfoo)** - 最接近需求，CLI + 多 Provider + 多 Evaluator + 实验对比
2. **[deepeval](https://github.com/confident-ai/deepeval)** - Python 原生，Evaluator 抽象设计好
3. **[openai/evals](https://github.com/openai/evals)** - 评测数据集格式 + Runner 设计参考
4. **[ragas](https://github.com/vibrantlabsai/ragas)** - RAG 场景评测指标实现
5. **[agentprobe](https://github.com/tomerhakak/agentprobe)** - 轻量级实现参考
