
## Draft design by tianyu, input for AI

语言：python。api 和 server 部分看下如果 request 并发要求高可改go。

```
Provider 调用模型， provider 配置不能写死在业务逻辑中
Evaluator 评估，evaluator 失败不能导致整个程序直接 crash
```

* 模块Provider Evaluator 天然独立，无业务交集，可用队列进行通信，两侧并发不影响。处理速度不同，模型侧 响应慢，卡IO。
* provider 配置 yaml 或 config.py，参考一下开源的项目。
* 用户应更关注 Provider，Eval 的编排可以更大胆。
* Evaluator 插件，参考 prefect 装饰器。
* 可选：token_usage、cost。需要 embedding，cost计算部分为纯规则，找开源项目看。

```
mock Provider
second Provider
```
* 本地要个模型？还是规则，提到了 second provider 是 或基于规则的 provider emmmm
* second Provider 搞个本地 8B，或者 cc。

```
实现一个 runner，可以提交并执行一次评测任务
```

* 调度器，concurrency 有歧义，provider 和 evaluator 本质并发 无关系，不需要完全串型。concurrency 理解为Provider同时处理的 QA 数。Evaluator worker 数量可以更大，如果规则很复杂或加入AI eval，但mvp没必要，因为大概率卡模型网络请求，不过最好分开，不然后面不好拆。
* 要聚合结果，还得有个聚合的 aggregator。
* 平均 latency，p95 latency。 eval部分平响还是整体平响？理解为eval 部分平响，每个部分添加 装饰器进行计时。然后统一计算进行拼接。

```
建议支持命令行或 HTTP API 中的一种：                                                                                                                        
  python run_eval.py --dataset data/eval_cases.jsonl --provider mock-v1 --concurrency 4                                                                        
  或：                                                                                                                        
  curl -X POST http://localhost:8000/eval-runs    
```

* fastapi 封装服务，队列通信，考虑完全异步。考虑 cli 本地跑，server 简单封装，后续部署拓展。
* 可以从 API 设计开始，拆分功能。后续考虑mcp 为 agent 调用服务。

```
支持对比两次评测结果
```
* 输出json 进行对比，单纯数据分析报告，后续 AI 出指标逻辑，最后写。

```
鲁棒性
非法输入数据
provider 调用失败
provider 超时
evaluator 异常
单个 case 重试失败
并发执行中的部分失败
结果文件写入失败
程序不能因为单条 case 失败而整体不可用。
```

* Fastapi 原生 Pydantic，input使用做校验即可。错误数据应该存cache，后续再有错误不要去判断了。
* provider 失败，超时，报告用户失败信息。创建Error。后续可以接 sentry 分析 trace。
* evaluator 异常。创建Error。后续可以接 sentry 分析 trace。
* Error 处理重点看一下咋设计，参考try except 直接进 sentry，MVP本地应该咋搞。


```
额外实现：
任务状态机，断点续传等，保存状态即可。
插件式 Evaluator，看开源，或者看prefect。
工具调用评测，llama index 个 rag 框架测试一下，可以看切分文档是否正确，幻觉等。
```

* sqlite，设计一下 schema。
* 装饰器写好，直接装饰 eval？
* llamaindex 随便找点语料，bge embedding吧本地


```
有结构化日志或 trace
评测报告输出为 Markdown / HTML
```

* logging写好，json吧，后续splunk 或者 ES方便
* 有点奇怪，为啥不是json输出呢。Markdown/HTML 还是给人看，渲染一下吧。还是存好json。测评报告 index 存sqlite吧。写个前端查看也行。

