# Demo

这个目录统一承载项目示例，不再分散到 `examples/`。

它包含两类内容：

- `quickstart/`
  - 一个可直接运行的最小示例工程
  - 包含配置、Provider 配置、示例数据、plugin 和样例输出
- `sample_runs/`
  - 两份固定 artifact
  - 用来直接演示 compare 能力

## 目录说明

```text
demo/
├── README.md
├── compare_example.md
├── demo_cases.jsonl
├── quickstart/
│   ├── README.md
│   ├── config.yaml
│   ├── providers.yaml
│   ├── data/
│   ├── plugins/
│   └── outputs/
└── sample_runs/
    ├── run-baseline/
    │   ├── case_results.jsonl
    │   └── meta.json
    └── run-candidate/
        ├── case_results.jsonl
        └── meta.json
```

## 1. Quickstart

如果你想快速跑通一遍项目，先看：

- [quickstart/README.md](/Users/tiashi/Desktop/mini_LLM_eval/demo/quickstart/README.md)

这是一个完整的最小示例工程，适合：

- 验证安装是否正常
- 看 `config.yaml` / `providers.yaml` 怎么写
- 看 plugin provider 怎么接

## 2. Compare 样例

如果你想直接理解 artifact 和 compare，先看：

- [demo_cases.jsonl](/Users/tiashi/Desktop/mini_LLM_eval/demo/demo_cases.jsonl)
- [sample_runs/run-baseline/meta.json](/Users/tiashi/Desktop/mini_LLM_eval/demo/sample_runs/run-baseline/meta.json)
- [sample_runs/run-candidate/meta.json](/Users/tiashi/Desktop/mini_LLM_eval/demo/sample_runs/run-candidate/meta.json)
- [compare_example.md](/Users/tiashi/Desktop/mini_LLM_eval/demo/compare_example.md)

这两份 run 的设计是：

- `run-baseline`
  - `json_001` 失败
  - `tool_001` 通过
- `run-candidate`
  - `json_001` 修复成功
  - `tool_001` 新增失败

因此它能同时展示：

- 总 pass rate 不变时，compare 仍然能识别 case-level 变化
- tag 维度 pass rate 变化
- latency 变化

直接运行：

```bash
mini-llm-eval compare demo/sample_runs/run-baseline demo/sample_runs/run-candidate
```

或者：

```bash
mini-llm-eval compare run-baseline run-candidate --output-dir demo/sample_runs
```
