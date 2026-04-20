# 审核通过文档查看与编辑设计

> **目标：** 让用户在前端查看审核通过后生成的文档，并支持版本切换、编辑后保存为新版本，以及重新入库；同时保留上传/待审批流程的清晰入口。

> **推荐方案：** 采用双层结构——`设定资料`页展示上传、待审批和已生成文档摘要，新增独立 `文档库` 页承载全文查看、版本切换、编辑和重新入库。

---

## 1. 信息架构

### 1.1 设定资料页

保留现有两块内容：
- 上传设定文件
- 待审批

在同页新增 **已生成文档** 区域，用于展示审核通过并入库后的文档摘要。每条记录展示：
- 标题
- 类型（`doc_type`）
- 当前版本号
- 更新时间
- 字数
- `查看详情` 操作

该区域只展示摘要，不承载重型编辑操作。

### 1.2 文档库页

左侧导航新增 **文档库** 页面。该页面负责所有深入操作：
- 按类型筛选文档
- 查看文档全文
- 切换同类型文档的历史版本
- 编辑正文
- 保存为新版本
- 手动重新入库

这样可以兼顾“上传后立刻能看到结果”和“复杂操作不挤在一个页面”。

---

## 2. 后端设计

围绕已入库文档新增查询与版本写入 API，统一由 `DocumentRepository` / `ExtractionService` 提供能力。

### 2.1 文档列表

`GET /api/novels/{novel_id}/documents`

返回当前小说下所有已入库文档摘要。

返回字段：
- `id`
- `doc_type`
- `title`
- `version`
- `updated_at`
- `content_preview`
- `word_count`

支持可选查询参数：
- `doc_type`

用途：
- 设定资料页展示“已生成文档”
- 文档库左栏列表

### 2.2 单文档详情

`GET /api/novels/{novel_id}/documents/{document_id}`

返回单篇文档的全文与元数据。

校验要求：
- 文档存在，否则 `404`
- 文档属于当前小说，否则 `403`

### 2.3 某类型文档版本列表

`GET /api/novels/{novel_id}/documents/types/{doc_type}/versions`

返回该小说下某个 `doc_type` 的所有版本，按版本号或更新时间倒序排列。

返回字段建议：
- `id`
- `title`
- `version`
- `updated_at`

用途：
- 文档库版本切换器

### 2.4 保存新版本

`POST /api/novels/{novel_id}/documents/{document_id}/versions`

请求体：
- `title`
- `content`

行为：
- 基于当前文档保存一个新版本
- 不覆盖旧版本
- 生成新的版本号
- 同步重建该版本的 embedding

这样历史版本可追溯，且后续检索能使用最新内容。

### 2.5 手动重新入库

`POST /api/novels/{novel_id}/documents/{document_id}/reindex`

行为：
- 对当前文档内容重新生成 embedding / 同步检索状态
- 不创建新版本
- 用作补偿操作，处理保存后需要手动重建索引的场景

如果后端确认“保存新版本”已经必然自动完成入库，这个接口仍保留为显式修复入口，便于前端提供“重新入库”按钮。

### 2.6 错误处理

- 小说不存在：`404`
- 文档不存在：`404`
- 文档不属于该小说：`403`
- 标题为空或正文为空：`422`
- embedding / 重新入库失败：返回明确错误，不静默吞掉

---

## 3. 前端设计

沿用现有 Vue 3 + Pinia + Vue Router + Element Plus 模式。

### 3.1 设定资料页增强

文件：`src/novel_dev/web/src/views/Documents.vue`

新增 **已生成文档** 卡片区：
- 列表展示最近版本文档摘要
- 每行显示：标题、类型、版本、更新时间、字数
- 操作：`查看详情`

点击后跳转到 `文档库` 页，并默认选中该文档。

### 3.2 文档库页

新增文件：`src/novel_dev/web/src/views/DocumentLibrary.vue`

建议采用两栏布局：

**左栏：文档列表**
- 按 `doc_type` 筛选
- 显示标题、类型、版本、更新时间
- 点击切换当前文档

**右栏：文档详情**
- 顶部：标题、类型、版本切换器、`重新入库` 按钮
- 中部：正文编辑区（textarea / 输入组件）
- 底部：`保存为新版本`

### 3.3 交互规则

- 从设定资料页跳入文档库时，带上文档 ID，默认高亮并加载详情
- 切换版本时，加载对应版本正文作为当前编辑起点
- 保存时永远创建新版本，不覆盖原版本
- 保存成功后：
  - 刷新文档列表
  - 刷新当前详情
  - 刷新版本列表
  - 刷新设定资料页摘要数据
- `重新入库` 和 `保存为新版本` 都显示 loading，防止重复提交

### 3.4 状态管理

文件：`src/novel_dev/web/src/stores/novel.js`

新增状态：
- `documents`
- `documentDetail`
- `documentVersions`

新增 action：
- `fetchDocumentList`
- `fetchDocumentDetail`
- `fetchDocumentVersions`
- `saveDocumentVersion`
- `reindexDocument`

### 3.5 API 封装

文件：`src/novel_dev/web/src/api.js`

新增方法：
- `getDocuments(id, docType)`
- `getDocumentDetail(id, documentId)`
- `getDocumentVersions(id, docType)`
- `saveDocumentVersion(id, documentId, payload)`
- `reindexDocument(id, documentId)`

### 3.6 路由与导航

文件：
- `src/novel_dev/web/src/App.vue`
- `src/novel_dev/web/src/router.js`

变更：
- 左侧导航新增 `文档库`
- 路由新增 `/document-library`

---

## 4. 数据与服务职责

### 4.1 Repository 层

优先扩展现有文档仓储，避免新增一次性抽象。

建议在文档仓储中补齐：
- 按小说列出全部文档摘要
- 按 ID 获取单文档
- 按 `doc_type` 列出版本
- 获取最新版本
- 创建新版本

### 4.2 Service 层

由服务层负责：
- 输入校验
- 版本号递增
- embedding 重建
- 重新入库调用

这样路由层只保留参数解析和权限校验。

---

## 5. 安全与约束

- 文档内容属于用户可编辑输入，只按纯文本路径展示和编辑，不渲染未消毒 HTML
- 所有写接口都校验 `novel_id` 与 `document_id` 的归属关系，避免跨小说越权访问
- 列表接口只返回摘要，不在首页一次返回所有全文内容
- 保存失败时保留编辑内容，便于用户修改后重试

---

## 6. 测试设计

### 6.1 后端测试

新增 API 测试覆盖：
- 能列出审核通过后生成的文档
- 能读取指定文档全文
- 能按类型读取版本列表
- 保存编辑内容后新增版本，而不是覆盖旧版本
- 文档越权访问返回 `403`
- 空标题或空正文返回 `422`
- 手动重新入库接口成功触发 embedding 重建

### 6.2 前端测试

至少覆盖状态层或关键组件：
- 设定资料页能展示“已生成文档”
- 文档库页能加载列表、详情、版本
- 保存成功后刷新列表、详情、版本
- 接口失败时显示错误提示

---

## 7. 实施边界

本次只实现：
- 已生成文档可见
- 文档库查看
- 版本切换
- 编辑后保存新版本
- 手动重新入库

本次不做：
- 多版本可视化 diff
- 富文本编辑
- 协同编辑
- 文档权限分级

这样范围足够聚焦，适合在当前前端结构上增量完成。
