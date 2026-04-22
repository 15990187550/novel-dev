# 设定导入即时进度与持久化记录设计

## 目标

当前设定导入存在两个明显问题：

1. 点击上传后，列表要等整批导入完成才出现记录，用户无法判断是否正在处理。
2. 切换 tab 或刷新页面后，正在导入的上下文不可见，体验上像“任务消失了”。

这次改造目标是：

- 上传一开始就把记录落到后端数据库。
- 列表立即出现对应记录，并显示“导入中”状态。
- 切换 tab 或刷新页面后，仍然能看到正在导入的记录。
- 导入完成后，记录自动转为可审核的待处理结果；失败则保留失败记录。

## 现状

- 前端 [Documents.vue](/Users/xuhuibin/Documents/popo/Modules/novel-dev/src/novel_dev/web/src/views/Documents.vue) 在调用 `uploadDocumentsBatch` 后，只有等整批请求返回，才执行 `store.fetchDocuments()`。
- 后端 `/documents/upload/batch` 当前会 `await asyncio.gather(...)` 等所有文件处理完成后再统一返回，因此前端无法在处理中获得任何可展示的持久化记录。
- `pending_extractions` 已经是持久化表，但现在只在提取完成后创建，状态主要是 `pending / approved`，没有“处理中”状态。

## 方案

### 1. 数据模型与状态

复用现有 `pending_extractions` 表，不新增新表。状态扩展为：

- `processing`: 记录已创建，导入任务正在后台执行
- `pending`: 提取完成，等待人工审核
- `failed`: 提取失败，保留错误信息
- `approved`: 已批准并写入正式数据

为支持失败展示，记录中需要持久化错误信息。最小做法是在 `resolution_result` 或新增 `error_message` 字段中保存错误。推荐新增明确字段，避免与批准结果结构混用。

### 2. 后端上传流程

批量上传接口改为“两阶段”：

1. 受理阶段
   - 为每个文件先创建一条 `pending_extractions` 记录
   - 初始状态为 `processing`
   - 写入 `source_filename`、`novel_id`、`extraction_type` 的占位值或可推断值
   - 立即提交事务

2. 后台处理阶段
   - 后端异步执行每个文件的提取流程
   - 成功时更新已有记录的 `raw_result / proposed_entities / diff_result`，并将状态改为 `pending`
   - 失败时将状态改为 `failed`，写入错误信息

接口返回不再表示“所有文件都已完成”，而是返回“已受理的任务记录”列表。前端以后续查询为准观察进度。

### 3. 前端展示与轮询

Documents 页面上传成功后立即刷新 `store.pendingDocs`，让新建的 `processing` 记录马上出现在列表中。

当列表中存在 `processing` 记录时，页面启动轮询：

- 定时调用 `store.fetchDocuments()`
- 直到不存在 `processing` 记录为止停止轮询
- 切换 tab 后重新进入 Documents 页面时，如果仍有 `processing` 记录，则继续轮询
- 刷新页面后，只要后端记录仍是 `processing`，页面加载后同样继续轮询

这意味着“状态保活”依赖数据库，而不是组件内存状态。

### 4. 列表行为

列表中的每条记录都要稳定存在，不因 tab 切换消失。

显示规则：

- `processing`: 显示“导入中”
- `pending`: 显示“待审核”
- `failed`: 显示“失败”
- `approved`: 显示“已批准”

`processing` 状态下禁用“查看详情/批准”中不成立的动作，或仅允许查看基础信息。

### 5. 实现边界

本次只解决“导入任务可见、状态可追踪、页面切换不丢”的问题，不引入：

- WebSocket / SSE 实时推送
- 独立任务队列表
- 复杂百分比进度

轮询粒度只做到“文件级状态变化”，不做 token 级或阶段级进度条。

## 数据流

1. 用户选择多个设定文件并点击上传
2. 前端调用批量上传接口
3. 后端为每个文件立即创建 `processing` 记录并返回记录 ID
4. 前端刷新 `pendingDocs`，列表立刻出现“导入中”
5. 后端后台继续提取
6. 前端轮询 `documents/pending`
7. 单条记录转为 `pending` 或 `failed`
8. 所有 `processing` 记录消失后停止轮询

## 测试

后端测试：

- 上传接口调用后，立刻能查到 `processing` 状态记录
- 后台成功处理后，状态变为 `pending`
- 后台失败后，状态变为 `failed` 且错误信息可读

前端测试：

- 点击上传后，列表立即显示新记录且状态为“导入中”
- 当 `store.pendingDocs` 含 `processing` 项时会启动轮询
- 切换 tab / 重新挂载页面后，只要后端仍返回 `processing`，列表与轮询都能恢复
- 全部完成后停止轮询

## 风险与取舍

- 由于采用轮询，状态更新存在秒级延迟，但实现简单、与现有架构兼容。
- 如果后台任务直接挂在应用进程内，服务重启会中断处理中任务。短期可接受，因为页面至少还能看到残留的 `processing` 记录；后续若需要更强可靠性，再引入独立任务执行器。
- 单文件的 `extraction_type` 在真正提取前可能未知；若前置分类成本不值得增加，可以先在 `processing` 阶段显示为 `处理中`，完成后再补齐真实类型。
