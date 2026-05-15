from __future__ import annotations

from novel_dev.genres.models import GenreCategory, GenreTemplate, NovelGenre


BUILTIN_CATEGORIES: tuple[GenreCategory, ...] = (
    GenreCategory(slug="general", name="通用", level=1, sort_order=0, description="通用正式创作模板"),
    GenreCategory(slug="uncategorized", name="未分类", level=2, parent_slug="general", sort_order=0, description="历史兼容分类"),
    GenreCategory(slug="xuanhuan", name="玄幻", level=1, sort_order=10, description="以超凡规则、力量体系和世界秩序为核心的长篇类型"),
    GenreCategory(slug="oriental_fantasy", name="东方玄幻", level=2, parent_slug="xuanhuan", sort_order=11),
    GenreCategory(slug="otherworld_continent", name="异世大陆", level=2, parent_slug="xuanhuan", sort_order=12),
    GenreCategory(slug="zhutian", name="诸天文", level=2, parent_slug="xuanhuan", sort_order=13),
    GenreCategory(slug="system_flow", name="系统流", level=2, parent_slug="xuanhuan", sort_order=14),
    GenreCategory(slug="xianxia", name="仙侠", level=1, sort_order=20),
    GenreCategory(slug="classical_xianxia", name="古典仙侠", level=2, parent_slug="xianxia", sort_order=21),
    GenreCategory(slug="cultivation_civilization", name="修真文明", level=2, parent_slug="xianxia", sort_order=22),
    GenreCategory(slug="mortal_flow", name="凡人流", level=2, parent_slug="xianxia", sort_order=23),
    GenreCategory(slug="prehistoric_myth", name="洪荒流", level=2, parent_slug="xianxia", sort_order=24),
    GenreCategory(slug="dushi", name="都市", level=1, sort_order=30),
    GenreCategory(slug="urban_life", name="都市生活", level=2, parent_slug="dushi", sort_order=31),
    GenreCategory(slug="urban_power", name="都市异能", level=2, parent_slug="dushi", sort_order=32),
    GenreCategory(slug="workplace_business", name="职场商战", level=2, parent_slug="dushi", sort_order=33),
    GenreCategory(slug="urban_cultivation", name="都市修真", level=2, parent_slug="dushi", sort_order=34),
    GenreCategory(slug="kehuan", name="科幻", level=1, sort_order=40),
    GenreCategory(slug="future_world", name="未来世界", level=2, parent_slug="kehuan", sort_order=41),
    GenreCategory(slug="interstellar", name="星际文明", level=2, parent_slug="kehuan", sort_order=42),
    GenreCategory(slug="apocalypse", name="末世危机", level=2, parent_slug="kehuan", sort_order=43),
    GenreCategory(slug="cyberpunk", name="赛博朋克", level=2, parent_slug="kehuan", sort_order=44),
    GenreCategory(slug="xuanyi", name="悬疑", level=1, sort_order=50),
    GenreCategory(slug="detective", name="推理探案", level=2, parent_slug="xuanyi", sort_order=51),
    GenreCategory(slug="folk_suspense", name="民俗悬疑", level=2, parent_slug="xuanyi", sort_order=52),
    GenreCategory(slug="infinite_flow", name="无限流", level=2, parent_slug="xuanyi", sort_order=53),
    GenreCategory(slug="psychological_suspense", name="心理悬疑", level=2, parent_slug="xuanyi", sort_order=54),
    GenreCategory(slug="lishi", name="历史", level=1, sort_order=60),
    GenreCategory(slug="alternate_history", name="架空历史", level=2, parent_slug="lishi", sort_order=61),
    GenreCategory(slug="time_travel_history", name="穿越历史", level=2, parent_slug="lishi", sort_order=62),
    GenreCategory(slug="political_war", name="权谋争霸", level=2, parent_slug="lishi", sort_order=63),
    GenreCategory(slug="historical_military", name="历史军事", level=2, parent_slug="lishi", sort_order=64),
    GenreCategory(slug="qihuan", name="奇幻", level=1, sort_order=70),
    GenreCategory(slug="western_fantasy", name="西方奇幻", level=2, parent_slug="qihuan", sort_order=71),
    GenreCategory(slug="epic_fantasy", name="史诗奇幻", level=2, parent_slug="qihuan", sort_order=72),
    GenreCategory(slug="magic_academy", name="魔法学院", level=2, parent_slug="qihuan", sort_order=73),
    GenreCategory(slug="otherworld_adventure", name="异界冒险", level=2, parent_slug="qihuan", sort_order=74),
)


BUILTIN_TEMPLATES: tuple[GenreTemplate, ...] = (
    GenreTemplate(
        scope="global",
        prompt_blocks={
            "source_rules": ["正式工作流必须以导入资料、用户设定和已确认工作台内容为事实来源；缺失信息标记为待确认，不编造具体事实。"],
            "quality_rules": ["生成前先检查类型约束、设定一致性、可读性、剧情连贯性和章节承诺是否同时成立。"],
            "forbidden_rules": ["不得把模板文字当成剧情正文；不得引入模板中没有授权的具体角色、地点、组织或事件。"],
        },
        quality_config={
            "modern_terms_policy": "contextual",
            "foreign_terms_policy": "contextual",
            "blocking_rules": {"source_conflict": True, "type_drift": True},
            "dimension_weights": {"setting_consistency": 1.0, "plot_cohesion": 1.0, "readability": 1.0},
        },
    ),
    GenreTemplate(
        scope="primary",
        category_slug="xuanhuan",
        prompt_blocks={
            "setting_rules": ["明确力量体系、世界秩序、资源稀缺性、势力边界和超凡规则的代价。"],
            "structure_rules": ["阶段推进应体现规则认知、能力代价、外部压迫和角色选择的递进。"],
            "forbidden_rules": ["未获资料授权时，不使用现代职场吐槽、互联网黑话或现实法律梗破坏类型沉浸。"],
        },
        quality_config={
            "modern_terms_policy": "block",
            "required_setting_dimensions": ["power_system", "social_order", "resource_rules"],
            "dimension_weights": {"setting_consistency": 1.2, "plot_cohesion": 1.1},
        },
    ),
    GenreTemplate(
        scope="secondary",
        category_slug="zhutian",
        parent_slug="xuanhuan",
        prompt_blocks={
            "setting_rules": ["跨世界内容必须区分来源规则、可接触边界、信息隔离和力量映射，不混淆不同规则域。"],
            "quality_rules": ["检查人物、势力、能力和道具是否绑定正确来源域；跨域调用必须有已铺垫入口。"],
        },
        quality_config={
            "required_setting_dimensions": ["domain_boundaries", "power_mapping"],
            "blocking_rules": {"source_domain_conflict": True},
        },
    ),
    GenreTemplate(
        scope="secondary",
        category_slug="workplace_business",
        parent_slug="dushi",
        prompt_blocks={
            "setting_rules": ["现实组织、合同、资金、法律、职位关系和商业因果应保持可信。"],
            "prose_rules": ["表达可使用现代生活和商业语汇，但人物行为仍需服务剧情推进和关系变化。"],
            "forbidden_rules": ["除非导入资料明确授权，不把宗门、境界突破、灵气复苏作为默认解决方案。"],
        },
        quality_config={
            "modern_terms_policy": "allow",
            "required_setting_dimensions": ["career_status", "business_stakes", "real_world_constraints"],
            "forbidden_drift_patterns": ["未授权宗门体系", "未授权境界突破"],
        },
    ),
    GenreTemplate(
        scope="secondary",
        category_slug="detective",
        parent_slug="xuanyi",
        prompt_blocks={
            "structure_rules": ["线索、疑点、误导和信息披露要公平递进，关键解答必须能回看前文找到依据。"],
            "quality_rules": ["检查案件线索链、嫌疑变化、动机可信度和解答边界。"],
        },
        quality_config={
            "required_setting_dimensions": ["clue_chain", "suspect_map", "disclosure_boundary"],
            "blocking_rules": {"unforeshadowed_solution": True},
        },
    ),
)


def default_genre() -> NovelGenre:
    return NovelGenre(
        primary_slug="general",
        primary_name="通用",
        secondary_slug="uncategorized",
        secondary_name="未分类",
    )
