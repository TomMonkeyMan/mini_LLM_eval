provider 的加载逻辑目前框架性不够强，后续用户的模型应该是一个 服务？或者一个类似脚本的插件，或者是一个配置，比如用户直接训练完了8B的模型，然后部署到了某一个服务上，用户应该需要告诉我们的是，http 请求的endpoint，端口，还有payload？OpenAICompatibleProvider 假设所有模型都遵循 OpenAI Chat Completion API，但实际场景更复杂，应该让用户自定义provider插件，并在config里注册。

lua 那种 即插即拔的比较好。单文件、约定接口、放进去就能用。


provider 和 eval 是不同的部分，有些面向用户，有些不面向用户，所以是否要统一设计还有待商榷。
Evaluator: 产品内置 + 配置，用户 选择 eval_type + metadata。现在实现逻辑是否有过于复杂。


目前同步耦合的，provider 和 Evaluator 应该完全实现解藕。


代码的规范还是有待提高，__slot__，类型检查等。


logging部分可以最后AI 统一检查。
logging要求 标准库 logging 即可，json 比较好，后续兼容其他系统。日志字段统一。





状态机，running run的部分现在似乎 ctrl + C 就可以，一定要做 需要中断 executor + 等待 tasks + 清理资源。后续 真的拆开 provider 和 evaluator 以后可以再做，在队列里面实现，可以参考 prefect的编排。



logging部分有问题，ERROR 没有正确对应所有的错误。httpx 会把请求访问日志记成 INFO，但是业务逻辑没有 处理 ERROR。


结果展示 Created 和 Started，Started 遗漏，检查状态机，代码层面未打点 or 数据库层面遗漏。



限流 应该仅对于 provider，这部分是不打挂上游或者 谷歌api的 429。token-bucket即可，或者更简单。



评测报告输出为 Markdown / HTML。渲染层，在数据分析层之上。

后续为 provider层/eval层/analysis层/reporter层。




