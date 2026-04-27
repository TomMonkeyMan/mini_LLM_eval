# Mini LLM Eval `RUNNING` Cancel 设计

> 状态：设计草案
>
> 更新日期：2026-04-27
>
> 目标：为当前 v1 架构补上“真实可用”的 `RUNNING` run cancel，而不是表面状态修改

---

## 1. 背景

当前项目已经支持：

- `PENDING -> CANCELLED`
- CLI `cancel` 命令

但当前 **不支持真正取消 `RUNNING` run**。

目前之所以拒绝 `RUNNING` cancel，是因为当前实现如果只在数据库里把状态改成 `CANCELLED`，会出现“假取消”：

- Provider 请求可能还在执行
- case task 可能还在继续跑
- writer queue 可能还在继续写结果
- run 最后甚至可能继续被写成 `SUCCEEDED` 或 `FAILED`

这种行为会破坏状态语义，比没有取消能力更糟。

因此，如果要支持 `RUNNING` cancel，必须满足：

1. 取消请求可以被正在执行的 run 感知
2. 执行器可以停止继续处理未完成任务
3. 已经在途的任务要有明确处理策略
4. 最终状态必须稳定落在 `CANCELLED`
5. 部分结果和元数据要可解释

---

## 2. 设计目标

### 2.1 核心目标

- 支持外部对 `RUNNING` run 发起取消
- 取消请求应跨进程可见
- 当前执行进程应在合理时间内停止
- 已完成的 case 结果保留
- 未完成 case 不再继续调度
- 最终 run 状态语义清晰

### 2.2 非目标

本设计当前不尝试解决：

- 分布式 worker cancel
- 多机 cancel 广播
- 强杀远端 Provider 服务上的实际推理任务
- v2 多 stage queue 架构下的最终取消方案

---

## 3. 关键语义

### 3.1 `cancel requested` 不等于 `cancelled`

这是整个设计里最重要的一点。

对于 `RUNNING` run：

- 用户执行 `cancel` 时，只能先表达“请求取消”
- 只有当执行进程真正停止后，run 才能变成 `CANCELLED`

因此：

- `PENDING -> CANCELLED` 可以立即完成
- `RUNNING -> CANCELLED` 必须经过“请求已记录，但执行尚未完全停下”的阶段

### 3.2 为什么不能直接改 `status = CANCELLED`

因为状态一旦改成 `CANCELLED`，系统就应当承诺：

- 不会继续产生新的 case 结果
- 不会继续推进 run
- 不会再落成 `SUCCEEDED/FAILED`

而当前执行器做不到这一点。

所以 `RUNNING cancel` 的第一步应是：

- **记录 cancel request**
- **而不是直接写 terminal status**

### 3.3 对外状态是否增加新枚举

当前不建议新增新的公开 `RunStatus`，例如：

- `CANCEL_REQUESTED`
- `STOPPING`

原因：

- 会扩大当前 v1 状态语义面
- 需要同步修改 CLI / DB / docs / tests /状态机
- 当前真正需要的是“请求取消”控制信号，不一定需要新生命周期状态

因此建议：

- `RunStatus` 仍保持：
  - `PENDING`
  - `RUNNING`
  - `SUCCEEDED`
  - `FAILED`
  - `CANCELLED`
- 另行增加 cancel request 字段

---

## 4. 推荐方案

### 4.1 总体思路

采用“两阶段取消”：

1. `cancel` 命令写入 **cancel request**
2. 正在执行的 run 通过后台检测感知该请求
3. 执行器停止继续调度，并取消可取消任务
4. RunService 做收尾，最终转为 `CANCELLED`

### 4.2 数据层设计

建议在 `runs` 表上增加以下字段：

- `cancel_requested_at TEXT NULL`
- `cancel_reason TEXT NULL`

这样做的优点：

- 结构简单
- 不需要单独加新表
- 状态和控制信号在同一行里
- CLI / status / show 很容易读取

对应数据库方法建议新增：

- `request_run_cancel(run_id: str, reason: str | None = None) -> None`
- `is_cancel_requested(run_id: str) -> bool`
- `get_cancel_requested_at(run_id: str) -> str | None`

语义：

- 对 `PENDING` run：可直接走 `cancel_run()`
- 对 `RUNNING` run：走 `request_run_cancel()`

### 4.3 状态日志设计

建议把 cancel request 也写入 `state_logs`，但它不是终态流转。

推荐事件：

- `run_cancel_requested`
  - `from_status = running`
  - `to_status = running`
  - `event = "run_cancel_requested"`
  - `message = "Cancellation requested for running run"`

最终真正停止后，再写：

- `run_cancelled`
  - `from_status = running`
  - `to_status = cancelled`

这样能清楚区分：

- 用户什么时候发起取消
- 系统什么时候真正停下

---

## 5. 执行器改造

当前执行器的难点是：

- `execute_batch()` 一开始就把所有 case 都 `create_task()`
- 虽然有 semaphore，但任务已经全量创建
- 这会让取消语义变得别扭

### 5.1 v1.1 最小可行改法

在不引入 v2 多 stage queue 的前提下，建议做如下改造：

#### A. 引入 `cancel_event`

由 `RunService` 创建一个 `asyncio.Event`，传给 `Executor`。

用途：

- 表示该 run 已收到取消请求
- executor 和 worker 都可以检查

#### B. 增加取消监控协程

`RunService.start_run()` 启动一个后台任务，定期轮询数据库：

- 每 `200ms` 或 `500ms` 查询一次 `is_cancel_requested(run_id)`
- 若为 `True`，则设置 `cancel_event`

这样 `cancel` 命令即使在另一个进程发起，当前执行进程也能感知。

#### C. Executor 支持取消

`Executor.execute_batch()` 需要支持：

- 在调度前检查 `cancel_event`
- 在任务执行中检查 `cancel_event`
- 在取消时对未完成 task 调 `task.cancel()`
- 停止继续处理新的 case

建议语义：

- 已完成并已入队的结果允许继续写入
- 未开始的 case 直接不再执行
- 正在等待 semaphore 的 task 被取消
- 正在 await provider 的 task 尝试取消

### 5.2 为什么这一步仍然可行

虽然当前不是 v2 queue 架构，但 Python `asyncio` 下：

- 等待 semaphore 的 task 是可取消的
- 等待 `httpx` 请求的 task 通常也是可取消的
- writer queue 可以在收尾阶段 flush 已入队结果

所以 v1.1 是可以做“真实 cancel”的，只是实现上需要比现在多一层控制逻辑。

---

## 6. RunService 收尾逻辑

### 6.1 新的异常类型

建议新增：

- `RunCancelledError`

用途：

- Executor 感知 cancel 后抛出
- RunService 单独捕获
- 避免把用户主动取消误归类成失败

### 6.2 `start_run()` / `resume_run()` 处理

RunService 在捕获取消后，应执行：

1. 停止 cancel monitor
2. 关闭 provider
3. 读取当前已落库结果
4. 构建部分 meta
5. 将 run 状态转为 `CANCELLED`
6. 写出 `meta.json`

不要把用户主动取消写成：

- `FAILED`
- `fatal_error`

因为取消不是系统失败。

### 6.3 部分结果的语义

被取消的 run 允许保留部分已完成 case 的结果。

因此：

- `case_results.jsonl` 可以是部分结果
- `meta.json` 需要能说明这是一次取消的 run
- summary 需要明确是 partial summary

建议 `meta.summary` 扩展字段：

- `completed_case_count`
- `remaining_case_count`
- `is_partial`

或者更直接地加：

- `termination_reason = "cancelled"`

---

## 7. CLI 语义设计

### 7.1 `cancel` 命令行为

推荐行为如下：

#### 如果 run 是 `PENDING`

- 立即取消
- 输出 `cancelled`

#### 如果 run 是 `RUNNING`

- 写入 cancel request
- 输出：
  - `cancellation requested`
  - 当前 status 仍可能暂时显示为 `running`

#### 如果 run 已终止

- 返回明确提示：
  - 已结束，无法取消
  - 或已是 cancelled

### 7.2 `status` / `show` 展示

建议补充以下字段：

- `Cancel Requested At`
- `Termination Reason`

这样用户能看出：

- cancel 是否已发起
- 是否已经真正停下

---

## 8. 状态机更新建议

当前已有轻量 `state_machine.py`。

支持 `RUNNING cancel` 后，状态机层应明确区分：

- **状态流转**
- **控制信号**

也就是说：

- `RUNNING -> CANCELLED` 仍是合法终态流转
- 但 `cancel_requested` 不属于 `RunStatus`

这能保持状态机简单，同时避免把控制信号误塞进生命周期状态。

建议在状态机文档中明确：

- `cancel request` 是 side signal
- `CANCELLED` 是 acknowledged terminal state

---

## 9. 推荐实现顺序

建议按以下顺序实现：

### 第一步：数据层

- 给 `runs` 表加 cancel request 字段
- 增加 DB 方法：
  - `request_run_cancel`
  - `is_cancel_requested`
- 增加对应测试

### 第二步：服务层

- 新增 `RunCancelledError`
- `RunService.cancel_run()` 改成：
  - `PENDING` 直接 cancel
  - `RUNNING` 记录 request
- 增加 cancel monitor

### 第三步：执行器

- 引入 `cancel_event`
- 允许 task cancel
- 在 writer queue 收尾阶段安全退出

### 第四步：产物与展示

- `meta.json` 增加 partial / cancellation 字段
- `status` / `show` 展示 cancel request / cancellation result

### 第五步：测试

至少补以下回归测试：

- `PENDING` run immediate cancel
- `RUNNING` run request cancel
- `RUNNING` run 最终进入 `CANCELLED`
- cancel 后不再新增未开始 case
- cancel 后保留已完成 case 结果
- cancel 与 writer queue 收尾不冲突

---

## 10. 不推荐的实现方式

以下方式不建议采用：

### 10.1 直接把 `RUNNING` 改成 `CANCELLED`

问题：

- 会产生假终态
- 破坏状态一致性

### 10.2 只在内存里放 cancel flag

问题：

- 另一个 CLI 进程发起的 cancel 看不见
- 不能跨进程协作

### 10.3 只有 DB request，没有执行器响应

问题：

- 仍然是假取消
- 用户体验会更差，因为系统看起来“支持”但实际上没停

---

## 11. 最终建议

最终建议如下：

- 当前方向应当是：**支持真正的 `RUNNING cancel`**
- 但实现方式必须是：
  - request cancel
  - executor acknowledge
  - final transition to `CANCELLED`

不建议在当前基础上直接开放“数据库写成 cancelled 就算完成”。

如果只做一步，最值得先做的是：

1. 在数据库里增加 `cancel_requested_at`
2. 把 `cancel` 命令对 `RUNNING` 的语义改成 `request cancel`
3. 再实现执行器对 cancel request 的响应

这样可以保证后续代码沿着正确方向演进，而不是先引入错误语义再返工。
