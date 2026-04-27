# Compare Example

## Command

```bash
mini-llm-eval compare demo/sample_runs/run-baseline demo/sample_runs/run-candidate
```

如果想导出成报告：

```bash
mini-llm-eval report-compare demo/sample_runs/run-baseline demo/sample_runs/run-candidate --format markdown
mini-llm-eval report-compare demo/sample_runs/run-baseline demo/sample_runs/run-candidate --format html --output ./compare.html
```

## Expected Takeaways

- 总通过率保持 `75% -> 75%`
- `knowledge` tag pass rate 上升：`50% -> 100%`
- `tooling` tag pass rate 下降：`100% -> 0%`
- `json_001` 被修复
- `tool_001` 成为新增失败 case
- 候选版本平均 latency 略高

## Why This Demo Exists

这个例子说明：

- compare 不只是看总 pass rate
- 即使总指标不变，也能发现结构性回归
- `meta.json + case_results.jsonl` 足够支撑离线分析
