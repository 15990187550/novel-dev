# WriterAgent 上下文优化设计

> **Goal:** 将 WriterAgent 的 prompt 从不可控的单条大 message（可能 20000+ 字）重构为结构化的多层 prompt（稳定 ~6000 字），通过 per-beat 检索 + 叙事接力棒 + 多 message 分层，提高上下文精准度和写作质量。

> **Architecture:** 三层 prompt（system / context / task）+ 每 beat 动态语义检索 + beat 间叙事接力棒替代原文传递。

---

## 1. 现状问题

当前 `WriterAgent._build_beat_prompt()` 把整个 `ChapterContext` 通过 `context.model_dump_json()` 塞入单条 user message。问题：

- **不可控膨胀**：worldview_summary（可能上万字）+ 所有 entity 状态 + 伏笔 + style_profile，没有总长度限制
- **信息噪音**：每个 beat 看到相同的完整 context，大部分与当前 beat 无关
- **注意力稀释**：写作规则和风格约束淹没在巨大的 JSON 中
- **线性增长**：滑窗只管 beat 原文，context 每 beat 重复传
- **单 message 结构**：LLM 无法区分"必须遵守的规则"和"参考信息"的优先级

## 2. 目标架构

### 2.1 三层 prompt 结构

利用 ChatMessage 的 `system`/`user` role 分层。所有 LLM driver（Anthropic / OpenAI / MiniMax）均已支持多 message。

| 层 | role | 内容 | 长度预算 | 更新频率 |
|---|---|---|---|---|
| **Layer 1: Rules** | `system` | 风格约束 + 写作硬规则 + 禁用词表 | ~1500字 | 章节内不变 |
| **Layer 2: Context** | `user` | 前情接力棒 + 章节计划概览 + beat 计划 + 最近 1 beat 原文 | ~2500字 | 每 beat 更新 |
| **Layer 3: Retrieval** | `user` | 用 beat.summary 检索到的 top-3 实体/设定/伏笔 | ~1500字 | 每 beat 检索 |

**总 prompt ≈ 5500 字（~2800 tokens），稳定可控。**

### 2.2 叙事接力棒（Narrative Relay Baton）

每个 beat 写完后，用 LLM 生成一份 ~200 字的叙事状态快照：

```
{
  "scene_state": "秦风站在悬崖边，手中握着断剑，身后是追兵的火把",
  "emotional_tone": "绝望中透着决绝",
  "new_info_revealed": "师兄是叛徒的真相被揭开",
  "open_threads": "悬崖下的深渊是否有出路；师妹的下落未明",
  "next_beat_hook": "秦风纵身跳下"
}
```

- 替代当前的 `inner_beats` 全文传递
- 最近 1 个 beat 保留原文（保持文风衔接）
- 更早的 beat 只传接力棒（~200 字 vs 原文 ~1000 字）
- 接力棒存入 checkpoint，支持断点续写

### 2.3 Per-beat 语义检索

每个 beat 写之前，用 `beat.summary + beat.key_entities` 做一次 embedding 检索：

- **实体**：`EmbeddingService.search_similar_entities(query, limit=3)` → top-3 相关实体状态
- **设定文档**：`EmbeddingService.search_similar(query, limit=2)` → top-2 相关设定段落
- **伏笔**：从 `pending_foreshadowings` 中筛选与本 beat key_entities 重叠的条目

替代现在的"一次性全部注入"策略。

---

## 3. 详细设计

### 3.1 新增 Schema: NarrativeRelay

在 `src/novel_dev/schemas/context.py` 中新增：

```python
class NarrativeRelay(BaseModel):
    """每个 beat 写完后生成的叙事状态快照，用于传递给后续 beat。"""
    scene_state: str        # 当前场景状态（谁在哪里、在做什么）
    emotional_tone: str     # 情绪基调
    new_info_revealed: str  # 本 beat 揭示了什么新信息
    open_threads: str       # 未解决的悬念/线索
    next_beat_hook: str     # 传递给下一个 beat 的钩子
```

### 3.2 修改 WriterAgent

#### 3.2.1 `_build_system_prompt(context)` — 新增方法

只包含风格和规则，章节内所有 beat 复用同一份。

```python
def _build_system_prompt(self, context: ChapterContext, is_last: bool) -> str:
    """Layer 1: 固定规则层。放在 system message 中，LLM 给予最高优先级。"""
    parts = []
    parts.append("你是一位追求沉浸感与可读性的中文小说家。按以下约束生成正文。只返回正文，不添加解释。")
    parts.append(self._build_style_guide_block(context))
    parts.append(self._build_writing_rules_block(is_last))
    return "\n\n".join(p for p in parts if p)
```

#### 3.2.2 `_build_context_message(beat, context, relay_history, last_beat_text, idx, total)` — 新增方法

动态组装上下文层。

```python
def _build_context_message(
    self, beat: BeatPlan, context: ChapterContext,
    relay_history: list[NarrativeRelay], last_beat_text: str,
    idx: int, total: int, is_last: bool,
) -> str:
    """Layer 2: 叙事上下文层。包含章节计划 + 接力棒 + 最近 beat 原文。"""
    parts = []

    # 前情摘要（如有）
    if context.previous_chapter_summary:
        parts.append(f"### 前情回顾\n{context.previous_chapter_summary}")

    # 章节计划概览（精简版，只有 title + beat summaries）
    plan_lines = [f"本章：{context.chapter_plan.title}（共{total}个节拍）"]
    for i, b in enumerate(context.chapter_plan.beats):
        marker = "→ " if i == idx else "  "
        plan_lines.append(f"{marker}节拍{i+1}: {b.summary}")
    parts.append("### 章节计划\n" + "\n".join(plan_lines))

    # 叙事接力棒（更早的 beat 状态压缩）
    if relay_history:
        relay_text = "\n".join(
            f"[节拍{i+1}] {r.scene_state} | {r.emotional_tone} | 钩子: {r.next_beat_hook}"
            for i, r in enumerate(relay_history)
        )
        parts.append(f"### 已完成节拍状态\n{relay_text}")

    # 最近 1 个 beat 原文（保持文风衔接）
    if last_beat_text:
        parts.append(f"### 紧邻上文（承接风格与情感）\n{last_beat_text}")

    # 当前节拍计划
    position = f"（第{idx+1}/{total}个节拍{'|章末节拍' if is_last else ''}）"
    parts.append(f"### 当前节拍{position}\n{beat.model_dump_json()}")

    return "\n\n".join(parts)
```

#### 3.2.3 `_build_retrieval_message(beat, context, novel_id)` — 新增方法

Per-beat 语义检索层。

```python
async def _build_retrieval_message(
    self, beat: BeatPlan, context: ChapterContext, novel_id: str,
) -> str:
    """Layer 3: 检索层。用本 beat 的 summary 做语义检索，注入最相关的设定/实体/伏笔。"""
    if not self.embedding_service:
        return self._fallback_retrieval(beat, context)

    query = f"{beat.summary} {' '.join(beat.key_entities)}"
    parts = []

    # 检索相关实体状态
    try:
        entities = await self.embedding_service.search_similar_entities(
            novel_id=novel_id, query_text=query, limit=3
        )
        if entities:
            entity_text = "\n".join(f"- [{e.doc_type}] {e.title}: {e.content_preview}" for e in entities)
            parts.append(f"### 相关角色/物品\n{entity_text}")
    except Exception:
        pass

    # 检索相关设定文档
    try:
        docs = await self.embedding_service.search_similar(
            novel_id=novel_id, query_text=query, limit=2
        )
        if docs:
            doc_text = "\n".join(f"- [{d.doc_type}] {d.title}: {d.content_preview}" for d in docs)
            parts.append(f"### 相关设定\n{doc_text}")
    except Exception:
        pass

    # 筛选与本 beat 相关的伏笔
    beat_entities = set(beat.key_entities)
    relevant_fs = []
    for fs in context.pending_foreshadowings:
        fs_related = set(fs.get("related_entity_names", []))
        if beat_entities & fs_related or any(kw in beat.summary for kw in fs.get("keywords", [])):
            relevant_fs.append(fs)
    if relevant_fs:
        fs_text = "\n".join(f"- {fs['content']}（需自然嵌入，不要点破）" for fs in relevant_fs[:3])
        parts.append(f"### 待嵌入伏笔\n{fs_text}")

    return "\n\n".join(parts) if parts else ""

def _fallback_retrieval(self, beat: BeatPlan, context: ChapterContext) -> str:
    """无 EmbeddingService 时的降级：用 key_entities 名字匹配。"""
    parts = []
    beat_entities = set(beat.key_entities)
    matched = [e for e in context.active_entities if e.name in beat_entities]
    if matched:
        text = "\n".join(f"- [{e.type}] {e.name}: {e.current_state[:300]}" for e in matched)
        parts.append(f"### 相关角色\n{text}")
    return "\n\n".join(parts) if parts else ""
```

#### 3.2.4 `_generate_relay(beat_text, beat)` — 新增方法

Beat 写完后生成叙事接力棒。

```python
async def _generate_relay(self, beat_text: str, beat: BeatPlan) -> NarrativeRelay:
    """用轻量模型生成叙事状态快照。"""
    prompt = (
        "你是一位叙事分析师。请阅读以下小说节拍正文，提取当前叙事状态。"
        "返回严格 JSON（NarrativeRelay schema）。\n\n"
        f"节拍计划: {beat.summary}\n\n"
        f"正文:\n{beat_text}\n\n"
        "JSON:"
    )
    from novel_dev.agents._llm_helpers import call_and_parse
    return await call_and_parse(
        "WriterAgent", "generate_relay", prompt,
        NarrativeRelay.model_validate_json, max_retries=2,
    )
```

#### 3.2.5 `_generate_beat` — 重构

从单条 message 改为三条 message。

```python
async def _generate_beat(
    self, beat: BeatPlan, context: ChapterContext,
    relay_history: list[NarrativeRelay], last_beat_text: str,
    idx: int, total: int, is_last: bool, novel_id: str,
) -> str:
    system_prompt = self._build_system_prompt(context, is_last)
    context_msg = self._build_context_message(
        beat, context, relay_history, last_beat_text, idx, total, is_last
    )
    retrieval_msg = await self._build_retrieval_message(beat, context, novel_id)

    task_instruction = "请直接输出本节拍正文："
    user_content = context_msg
    if retrieval_msg:
        user_content += "\n\n" + retrieval_msg
    user_content += "\n\n" + task_instruction

    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_content),
    ]

    from novel_dev.llm import llm_factory
    client = llm_factory.get("WriterAgent", task="generate_beat")
    config = llm_factory._resolve_config("WriterAgent", "generate_beat")
    response = await client.acomplete(messages, config)
    inner = _strip_anchors(response.text)
    return f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"
```

#### 3.2.6 `write()` 主循环 — 重构

```python
async def write(self, novel_id: str, context: ChapterContext, chapter_id: str) -> DraftMetadata:
    # ... existing state checks ...

    relay_history: list[NarrativeRelay] = []
    inner_beats: list[str] = []
    raw_draft = ""
    beat_coverage = []
    embedded_foreshadowings = []
    total_beats = len(context.chapter_plan.beats)

    for idx, beat in enumerate(context.chapter_plan.beats):
        is_last = (idx == total_beats - 1)
        last_beat_text = inner_beats[-1] if inner_beats else ""

        beat_text = await self._generate_beat(
            beat, context, relay_history, last_beat_text,
            idx, total_beats, is_last, novel_id,
        )
        inner = _strip_anchors(beat_text)

        if len(inner) < 50:
            inner = await self._rewrite_angle(beat, inner, context)
            beat_text = f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

        inner_beats.append(inner)
        raw_draft += beat_text + "\n\n"
        beat_coverage.append({"beat_index": idx, "word_count": len(inner)})

        # 生成叙事接力棒
        try:
            relay = await self._generate_relay(inner, beat)
            relay_history.append(relay)
        except Exception:
            # 降级：用 beat summary 作为简易接力棒
            relay_history.append(NarrativeRelay(
                scene_state=beat.summary,
                emotional_tone=beat.target_mood,
                new_info_revealed="",
                open_threads="",
                next_beat_hook="",
            ))

        # ... checkpoint save, foreshadowing tracking (same as before) ...

    # ... rest unchanged (metadata, chapter save, phase transition) ...
```

### 3.3 ContextAgent 精简

`ChapterContext` 不再需要塞入所有原始数据，只保留章节级骨架：

- `chapter_plan`: 保留（精简，不包含原始 JSON）
- `style_profile`: 保留（WriterAgent 在 system prompt 中使用）
- `worldview_summary`: **截断到 2000 字**
- `active_entities`: **只保留 name + type + 单行摘要**，不传完整 state JSON
- `previous_chapter_summary`: 保留（已有良好的结构化摘要）
- `pending_foreshadowings`: 保留（WriterAgent 按 beat 筛选）
- `relevant_documents`: **移除** — 改为 per-beat 检索
- `related_entities`: **移除** — 改为 per-beat 检索
- `similar_chapters`: **移除** — 改为 per-beat 检索
- `location_context`: 保留
- `timeline_events`: 保留

### 3.4 `content_preview` 长度提升

`document_repo.py` 和 `chapter_repo.py` 的 `similarity_search` 中 `content_preview` 从 200 字符提升到 600 字符。这样检索结果包含更多有用信息。

### 3.5 LLM Config 新增

`llm_config.yaml` 新增 `generate_relay` task：

```yaml
writer_agent:
  # ... existing config ...
  tasks:
    generate_beat:
      temperature: 0.95
    rewrite_beat:
      temperature: 0.8
    generate_relay:
      temperature: 0.2     # 低温，精确提取
      provider: anthropic
      model: claude-haiku-4-5-20251001   # 轻量模型，快速
      timeout: 15
```

---

## 4. 文件变更清单

### 修改的文件

| 文件 | 变更 |
|------|------|
| `src/novel_dev/schemas/context.py` | 新增 `NarrativeRelay` schema |
| `src/novel_dev/agents/writer_agent.py` | 重构 prompt 构建为三层；新增 `_generate_relay`、`_build_system_prompt`、`_build_context_message`、`_build_retrieval_message`；修改 `_generate_beat` 签名和实现；修改 `write()` 主循环 |
| `src/novel_dev/agents/context_agent.py` | `worldview_summary` 截断到 2000 字；`active_entities.current_state` 截断到 300 字 |
| `src/novel_dev/repositories/document_repo.py` | `content_preview` 从 `[:200]` 改为 `[:600]` |
| `src/novel_dev/repositories/chapter_repo.py` | `content_preview` 从 `[:200]` 改为 `[:600]` |
| `llm_config.yaml` | 新增 `generate_relay` task 配置 |

### 不变的文件

| 文件 | 原因 |
|------|------|
| `src/novel_dev/llm/drivers/*.py` | 已支持多 message，无需修改 |
| `src/novel_dev/llm/models.py` | `ChatMessage` 已支持 system/user/assistant |
| `src/novel_dev/services/embedding_service.py` | 检索接口不变，只是调用方从 ContextAgent 移到 WriterAgent |

---

## 5. Prompt 大小对比

**假设场景**：世界观 5000 字，10 个实体，5 条伏笔，8 个 beat 的章节。

| 指标 | 改前 | 改后 |
|---|---|---|
| 单 beat prompt 大小 | 15000-25000 字 | ~5500 字 |
| 第 8 个 beat prompt | 25000+ 字（含 7 beat 滑窗） | ~6000 字（接力棒 + 1 beat 原文） |
| 信息相关度 | 低（全量 dump） | 高（per-beat 检索） |
| message 结构 | 单条 user | system + user（结构化） |
| LLM 规则遵守度 | 规则淹没在 JSON 中 | system prompt 最高优先级 |

---

## 6. 额外收益

- **叙事接力棒存入 checkpoint**：断点续写时，不需要重新解析已写 beat 的全文，直接用接力棒恢复上下文
- **检索结果可观测**：每个 beat 检索到了什么，可以记入 `draft_metadata`，便于调试
- **独立可测试**：`_build_system_prompt`、`_build_context_message`、`_build_retrieval_message` 都是纯函数，可以单元测试
- **模型切换友好**：prompt 大小稳定在 ~6000 字，可以用更小/更快的模型而不担心超窗

---

## 7. 测试策略

### 单元测试

- `_build_system_prompt` 输出包含风格约束和写作规则，不包含世界观或实体
- `_build_context_message` 输出包含接力棒和最近 beat 原文，不包含完整 entity state
- `_build_retrieval_message` 无 embedding_service 时降级为 key_entities 名字匹配
- `NarrativeRelay` schema 验证
- `_generate_relay` mock LLM 返回合法 JSON

### 集成测试

- 完整 `write()` 流程：验证 prompt 中有 system message + user message
- 验证 relay_history 逐 beat 增长
- 验证检索结果被注入到 prompt 中
- 验证 checkpoint 中存储了 relay_history
