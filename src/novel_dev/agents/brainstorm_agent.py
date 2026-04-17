import uuid
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.llm.models import ChatMessage
from novel_dev.schemas.outline import SynopsisData, CharacterArc, PlotMilestone
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase


class BrainstormAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.director = NovelDirector(session)

    async def brainstorm(self, novel_id: str) -> SynopsisData:
        docs = await self.doc_repo.get_by_type(novel_id, "worldview")
        docs += await self.doc_repo.get_by_type(novel_id, "setting")
        docs += await self.doc_repo.get_by_type(novel_id, "concept")

        if not docs:
            raise ValueError("No source documents found for brainstorming")

        combined = "\n\n".join(f"[{d.doc_type}]\n{d.content}" for d in docs)
        synopsis_data = await self._generate_synopsis(combined)
        synopsis_text = self._format_synopsis_text(synopsis_data, combined)

        doc = await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="synopsis",
            title=synopsis_data.title,
            content=synopsis_text,
        )

        checkpoint = {}
        state = await self.state_repo.get_state(novel_id)
        if state and state.checkpoint_data:
            checkpoint = dict(state.checkpoint_data)

        checkpoint["synopsis_data"] = synopsis_data.model_dump()
        checkpoint["synopsis_doc_id"] = doc.id

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data=checkpoint,
            volume_id=None,
            chapter_id=None,
        )

        return synopsis_data

    async def _generate_synopsis(self, combined_text: str) -> SynopsisData:
        from novel_dev.llm import llm_factory
        client = llm_factory.get("BrainstormAgent", task="generate_synopsis")
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "你是一位小说大纲生成专家。根据用户提供的设定文档，"
                    "生成一份包含标题、一句话梗概、核心冲突、主题、人物弧光和剧情里程碑的大纲。"
                    "返回严格符合指定 JSON Schema 的数据。"
                ),
            ),
            ChatMessage(role="user", content=combined_text),
        ]
        response = await client.acomplete(messages)
        return SynopsisData.model_validate_json(response.text)

    def _format_synopsis_text(self, data: SynopsisData, source_text: str = "") -> str:
        lines = [
            f"# {data.title}",
            "",
            "## 一句话梗概",
            data.logline,
            "",
            "## 核心冲突",
            data.core_conflict,
            "",
            "## 人物弧光",
        ]
        for arc in data.character_arcs:
            lines.append(f"### {arc.name}")
            lines.append(arc.arc_summary)
            for pt in arc.key_turning_points:
                lines.append(f"- {pt}")
        lines.append("")
        lines.append("## 剧情里程碑")
        for ms in data.milestones:
            lines.append(f"### {ms.act}")
            lines.append(ms.summary)
            if ms.climax_event:
                lines.append(f"高潮：{ms.climax_event}")
        if source_text:
            lines.append("")
            lines.append("## 参考资料")
            lines.append(source_text)
        return "\n".join(lines)
