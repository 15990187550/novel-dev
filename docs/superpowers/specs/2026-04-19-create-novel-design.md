# 新建小说入口设计

## 背景
当前系统侧边栏仅支持选择已有小说（通过 `el-select-v2` 读取数据库中的 `NovelState` 列表），没有创建新小说的入口。后端缺少 `POST /api/novels` 端点。

## 目标
提供一个轻量级的新建小说入口，用户输入标题即可创建，创建后直接进入 `brainstorming` 阶段，可立即开始脑暴流程。

## 方案概述

### 前端
在侧边栏小说选择器下方新增一个 **"新建小说"** 按钮。点击后弹出 `el-dialog`，内含标题输入框，确认后调用 API 创建。成功后自动加载新小说到仪表盘。

### 后端
新增 `POST /api/novels` 端点：

- **请求体：** `{ "title": "小说标题" }`
- **novel_id 生成：** 标题 slug 化（小写、空格/标点替换为 `-`、去重） + 4 位随机十六进制后缀（如 `xuan-yu-mo-xin-a7f3`）
- **冲突处理：** 若生成的 `novel_id` 已存在，自动重试最多 5 次
- **NovelState 初始化：**
  - `novel_id`: 生成的 ID
  - `current_phase`: `"brainstorming"`
  - `current_volume_id`: `null`
  - `current_chapter_id`: `null`
  - `checkpoint_data`:
    ```json
    {
      "synopsis_data": {
        "title": "小说标题",
        "logline": "",
        "core_conflict": "",
        "themes": [],
        "character_arcs": [],
        "milestones": [],
        "estimated_volumes": 1,
        "estimated_total_chapters": 10,
        "estimated_total_words": 30000
      },
      "synopsis_doc_id": null
    }
    ```
- **响应：** 返回完整的 novel state（与 `GET /api/novels/{novel_id}/state` 格式一致）
- **错误处理：**
  - 标题为空/仅空白字符 → `422 Unprocessable Entity`
  - 连续 5 次 ID 冲突 → `500 Internal Server Error`

## 界面交互

1. 用户点击"新建小说"按钮
2. 弹出对话框，标题输入框自动聚焦
3. 输入标题，点击"创建"
4. 按钮进入 loading 状态
5. API 成功后：
   - 关闭对话框
   - 清空输入框
   - 刷新小说列表（`novelOptions`）
   - 自动选中新小说并加载仪表盘
   - 显示 `ElMessage.success('小说创建成功')`
6. API 失败时显示错误提示，对话框保持打开

## 技术细节

### 新增/修改文件
- `src/novel_dev/api/routes.py` — 新增 `POST /api/novels` 端点
- `src/novel_dev/web/index.html` — 新增按钮、对话框、创建逻辑

### novel_id 生成规则
```python
import re
import secrets

def generate_novel_id(title: str) -> str:
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[-\s]+', '-', slug).strip('-')
    suffix = secrets.token_hex(2)  # 4 hex chars
    return f"{slug}-{suffix}"
```

### 与现有代码的兼容
- 创建后 `current_phase="brainstorming"`，仪表盘上的"脑暴"按钮可直接使用
- `checkpoint_data` 结构与现有数据完全一致
- 无需修改 NovelState 表结构或其他已有逻辑
