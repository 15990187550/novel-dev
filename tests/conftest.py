import os
import re
import sys
from pathlib import Path

# Force tests to use a shared SQLite file DB so the global engine
# (used by MCP server and non-overridden API routes) can connect
# to the same database across connections.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_novel_dev.db"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock

from novel_dev.db.models import Base
from novel_dev.db.engine import engine, async_session_maker


@pytest.fixture(autouse=True)
def mock_llm_factory(monkeypatch):
    from novel_dev.llm import llm_factory
    from novel_dev.llm.models import LLMResponse
    from novel_dev.schemas.outline import SynopsisData, CharacterArc, PlotMilestone

    default_synopsis = SynopsisData(
        title="天玄纪元",
        logline="主角在修炼世界中崛起",
        core_conflict="个人复仇与天下大义",
        themes=["成长", "复仇"],
        character_arcs=[
            CharacterArc(
                name="主角",
                arc_summary="从废柴到巅峰",
                key_turning_points=["觉醒", "突破"],
            )
        ],
        milestones=[
            PlotMilestone(
                act="第一幕", summary="入门试炼", climax_event="外门大比"
            )
        ],
        estimated_volumes=3,
        estimated_total_chapters=90,
        estimated_total_words=270000,
    )

    def mock_get(agent, task=None):
        from novel_dev.llm.models import LLMResponse
        from novel_dev.agents.volume_planner import VolumePlanBlueprint, VolumePlanPatch
        from novel_dev.schemas.outline import VolumeScoreResult, VolumePlan, VolumeBeat
        from novel_dev.schemas.review import ScoreResult, DimensionScore
        from novel_dev.schemas.context import BeatPlan

        mock_client = AsyncMock()

        if agent == "BrainstormAgent" and task == "generate_synopsis":
            mock_client.acomplete.return_value = LLMResponse(text=default_synopsis.model_dump_json())
        elif agent == "BrainstormAgent" and task == "score_synopsis":
            from novel_dev.schemas.outline import SynopsisScoreResult
            mock_client.acomplete.return_value = LLMResponse(text=SynopsisScoreResult(
                overall=85, logline_specificity=85, conflict_concreteness=85,
                character_arc_depth=85, structural_turns=80, hook_strength=85,
                summary_feedback="good",
            ).model_dump_json())
        elif agent == "VolumePlannerAgent" and task == "score_volume_plan":
            mock_client.acomplete.return_value = LLMResponse(text=VolumeScoreResult(
                overall=88, outline_fidelity=88, character_plot_alignment=88,
                hook_distribution=88, foreshadowing_management=88,
                chapter_hooks=88, page_turning=88, summary_feedback="good",
            ).model_dump_json())
        elif agent == "VolumePlannerAgent" and task == "revise_volume_plan":
            mock_client.acomplete.return_value = LLMResponse(text=VolumePlanPatch(
                summary="卷总述",
                chapter_patches=[
                    {
                        "chapter_number": 1,
                        "summary": "章摘要",
                        "beats": [BeatPlan(summary="B1", target_mood="tense")],
                    }
                ],
            ).model_dump_json())
        elif agent == "VolumePlannerAgent" and task == "expand_volume_plan_batch":
            mock_client.acomplete.return_value = LLMResponse(
                text='[{"chapter_id":"ch_1","chapter_number":1,"title":"第一章","summary":"章摘要","target_word_count":3000,"target_mood":"tense","beats":[{"summary":"B1","target_mood":"tense"}]}]'
            )
        elif agent == "WriterAgent" and task == "generate_relay":
            mock_client.acomplete.return_value = LLMResponse(
                text='{"scene_state":"场景状态","emotional_tone":"紧张","new_info_revealed":"新信息","open_threads":"悬念","next_beat_hook":"钩子"}'
            )
        elif agent == "WriterAgent":
            mock_client.acomplete.return_value = LLMResponse(
                text="这是一个很长的节拍正文内容，字数足够多，情节跌宕起伏，引人入胜，余味悠长。"
            )
        elif agent == "CriticAgent" and task == "score_chapter":
            mock_client.acomplete.return_value = LLMResponse(text=ScoreResult(
                overall=88,
                dimensions=[
                    DimensionScore(name="plot_tension", score=85, comment=""),
                    DimensionScore(name="characterization", score=85, comment=""),
                    DimensionScore(name="readability", score=85, comment=""),
                    DimensionScore(name="consistency", score=85, comment=""),
                    DimensionScore(name="humanity", score=85, comment=""),
                ],
                summary_feedback="good",
            ).model_dump_json())
        elif agent == "CriticAgent" and task == "score_beats":
            mock_client.acomplete.return_value = LLMResponse(
                text='[{"beat_index": 0, "scores": {"plot_tension": 80, "humanity": 80}}]'
            )
        elif agent == "EditorAgent":
            mock_client.acomplete.return_value = LLMResponse(text="润色后的正文内容，情节更紧凑，人物更鲜明，场景更细腻，读感更顺畅有力自然。")
        elif agent == "FastReviewAgent":
            mock_client.acomplete.return_value = LLMResponse(
                text='{"consistency_fixed": true, "beat_cohesion_ok": true, "notes": []}'
            )
        elif agent == "ContextAgent" and task == "analyze_context_needs":
            mock_client.acomplete.return_value = LLMResponse(
                text='{"locations": [], "entities": [], "time_range": {"start_tick": -2, "end_tick": 2}, "foreshadowing_keywords": []}'
            )
        elif agent == "ContextAgent" and task == "build_scene_context":
            from novel_dev.schemas.context import LocationContext
            mock_client.acomplete.return_value = LLMResponse(
                text=LocationContext(current="默认地点", parent=None, narrative="场景描述").model_dump_json()
            )
        elif agent == "FileClassifier" and task == "classify_file":
            from novel_dev.agents.file_classifier import FileClassificationResult

            async def smart_classify(messages):
                prompt = messages[0].content if messages else ""
                # 根据文件名判断：文件名行以 "文件名：style" 开头则为 style_sample
                if "文件名：style" in prompt:
                    return LLMResponse(
                        text=FileClassificationResult(file_type="style_sample", confidence=0.9, reason="mock").model_dump_json()
                    )
                return LLMResponse(
                    text=FileClassificationResult(file_type="setting", confidence=0.9, reason="mock").model_dump_json()
                )

            mock_client.acomplete.side_effect = smart_classify
        elif agent == "StyleProfilerAgent" and task == "profile_style":
            from novel_dev.agents.style_profiler import StyleProfile, StyleConfig
            mock_client.acomplete.return_value = LLMResponse(
                text=StyleProfile(style_guide="Overall: mock style guide", style_config=StyleConfig()).model_dump_json()
            )
        elif agent == "SettingExtractorAgent" and task == "extract_setting":
            from novel_dev.agents.setting_extractor import ExtractedSetting, CharacterProfile, ImportantItem
            mock_client.acomplete.return_value = LLMResponse(
                text=ExtractedSetting(
                    worldview="mock worldview",
                    power_system="mock power",
                    factions=[],
                    character_profiles=[CharacterProfile(name="Mock", identity="mock", personality="mock", goal="mock")],
                    important_items=[ImportantItem(name="MockItem", description="mock", significance="mock")],
                    plot_synopsis="mock synopsis",
                ).model_dump_json()
            )
        elif agent == "EntityClassifierAgent" and task == "classify_entity":
            from novel_dev.agents.entity_classifier import EntityClassificationLLMResult

            async def smart_entity_classify(messages):
                prompt = messages[0].content if messages else ""
                type_match = re.search(r"实体类型：([^\n]+)", prompt)
                name_match = re.search(r"实体名称：([^\n]+)", prompt)
                entity_type = (type_match.group(1).strip() if type_match else "")
                entity_name = (name_match.group(1).strip() if name_match else "")

                if entity_type == "character":
                    group_name = "主角阵营" if any(keyword in prompt for keyword in ("陆照", "主角")) else "核心人物"
                    return LLMResponse(
                        text=EntityClassificationLLMResult(
                            category="人物",
                            group_name=group_name,
                            confidence=0.93,
                            reason="mock character classification",
                        ).model_dump_json()
                    )
                if entity_type == "faction" or any(keyword in entity_name for keyword in ("宗", "门", "教", "阁", "殿", "盟")):
                    return LLMResponse(
                        text=EntityClassificationLLMResult(
                            category="势力",
                            group_name="宗门势力",
                            confidence=0.9,
                            reason="mock faction classification",
                        ).model_dump_json()
                    )
                if any(keyword in entity_name for keyword in ("昆仑镜", "混沌剑", "荒剑", "佛骨舍利", "护身玉佩", "镜", "剑", "印")):
                    return LLMResponse(
                        text=EntityClassificationLLMResult(
                            category="法宝神兵",
                            group_name="特殊法宝",
                            confidence=0.9,
                            reason="mock treasure classification",
                        ).model_dump_json()
                    )
                if any(keyword in entity_name for keyword in ("经", "诀", "法", "术", "神通")):
                    return LLMResponse(
                        text=EntityClassificationLLMResult(
                            category="功法",
                            group_name="传承",
                            confidence=0.88,
                            reason="mock skill classification",
                        ).model_dump_json()
                    )
                return LLMResponse(
                    text=EntityClassificationLLMResult(
                        category="其他",
                        group_name="",
                        confidence=0.45,
                        reason="mock fallback classification",
                    ).model_dump_json()
                )

            mock_client.acomplete.side_effect = smart_entity_classify
        elif agent == "VolumePlannerAgent" and task == "generate_volume_plan":
            mock_client.acomplete.return_value = LLMResponse(text=VolumePlanBlueprint(
                volume_id="vol_1", volume_number=1, title="第一卷", summary="卷总述",
                total_chapters=1, estimated_total_words=3000,
                chapters=[{"chapter_number": 1, "title": "第一章", "summary": "章摘要"}],
            ).model_dump_json())
        else:
            mock_client.acomplete.return_value = LLMResponse(text="{}")

        return mock_client

    def mock_get_embedder():
        class MockEmbedder:
            async def aembed(self, texts: list[str]) -> list[list[float]]:
                vectors = []
                for text in texts:
                    dimensions = 1024 if "一级分类：" in text else 1536
                    vectors.append([0.0] * dimensions)
                return vectors
        return MockEmbedder()

    monkeypatch.setattr(llm_factory, "get", mock_get)
    monkeypatch.setattr(llm_factory, "get_embedder", mock_get_embedder)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(autouse=True)
async def cleanup_tables():
    yield
    await engine.dispose()
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session():
    async with async_session_maker() as session:
        yield session
        await session.rollback()
