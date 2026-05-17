import re


class HygieneIssue(str):
    def __new__(cls, value: str, code: str):
        obj = str.__new__(cls, value)
        obj.code = code
        return obj


class ProseHygieneService:
    """Detect planning/meta language that should not appear in finished prose."""

    PLAN_LANGUAGE_PATTERNS = (
        "这一拍",
        "本节拍",
        "当前节拍",
        "后续节拍",
        "节拍目标",
        "节拍计划",
        "章节计划",
        "写作卡",
        "读者应获得",
        "读者读完应获得",
        "停点参考",
        "停点策略",
        "读感合同",
        "事实准线",
        "边界卡",
        "当前 beat",
        "后续 beat",
        "beat ",
        "Beat ",
        "chapter_plan",
        "阻力不需要另起一条线",
        "他的选择也只落在眼前",
        "停点收在既有风险上",
        "只作为这一拍的动作余波",
        "这一拍的结果先落稳",
        "把当场目标压到纸面",
    )
    MODERN_AUTHORIZATION_MARKERS = (
        "现代",
        "当代",
        "都市",
        "校园",
        "职场",
        "互联网",
        "科幻",
        "赛博",
        "未来",
        "医院",
        "公司",
        "系统流",
        "游戏",
        "AI",
    )
    _LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")

    @classmethod
    def find_plan_language_issues(cls, text: str) -> list[str]:
        if not text:
            return []
        issues = []
        for pattern in cls.PLAN_LANGUAGE_PATTERNS:
            if pattern in text:
                issues.append(HygieneIssue(f"正文出现规划/元叙述术语: {pattern}", "plan_language"))
        return issues

    @classmethod
    def find_modern_drift_issues(cls, text: str, context: object | None = None) -> list[str]:
        if not text:
            return []
        if cls._modern_terms_authorized(context):
            return []
        issues = [
            HygieneIssue(f"正文出现未授权现代术语: {pattern}", "modern_drift")
            for pattern in cls._modern_drift_patterns(context)
            if pattern in text
        ]
        latin_words = []
        seen = set()
        for match in cls._LATIN_WORD_RE.finditer(text):
            word = match.group(0)
            key = word.lower()
            if len(set(key)) == 1 or key in seen:
                continue
            seen.add(key)
            latin_words.append(word)
        if latin_words:
            preview = "、".join(latin_words[:8])
            suffix = " 等" if len(latin_words) > 8 else ""
            issues.append(HygieneIssue(f"发现英文/外文词: {preview}{suffix}", "modern_drift"))
        return issues

    @classmethod
    def find_issues(cls, text: str, context: object | None = None) -> list[str]:
        return cls.find_plan_language_issues(text) + cls.find_modern_drift_issues(text, context=context)

    @classmethod
    def prompt_rules(cls, context: object | None = None) -> str:
        forbidden = "、".join(cls.PLAN_LANGUAGE_PATTERNS[:18])
        modern_authorized = cls._modern_terms_authorized(context)
        modern_line = (
            "- 当前设定/风格允许现代或科技语汇时，现代词必须符合角色时代、职业和场景语境；不得把工程字段或规划术语混入正文。\n"
            if modern_authorized
            else f"- 禁止未授权现代/外文漂移: {cls._modern_drift_rule_text(context)}；如必须表达前世记忆，转成贴合角色处境的中文短念头。\n"
        )
        return (
            "### 正文卫生硬约束\n"
            "- 只写小说正文，不复述章节计划、写作卡、节拍边界或质量要求。\n"
            f"- 正文禁用规划/元叙述词: {forbidden}。\n"
            "- 遇到目标、阻力、选择、代价、停点，只能把它们改写成角色可见的动作、对话、身体反应和场景后果。\n"
            f"{modern_line}"
            "- 不得出现 beat、chapter_plan、UI、系统字段、质量门禁、读感合同等工程或规划痕迹。\n"
        )

    @classmethod
    def issue_prompt_block(cls, text: str, context: object | None = None) -> str:
        issues = cls.find_issues(text, context=context)
        if not issues:
            return ""
        lines = "\n".join(f"- {issue}" for issue in issues[:10])
        return (
            "### 正文卫生问题(必须删除，不可换一种规划话术保留)\n"
            f"{lines}\n"
            "修复方式: 把这些句子改成当前场景里的动作、对白、身体反应、物件变化或直接后果。\n"
        )

    @classmethod
    def _genre_quality_config(cls, context: object | None = None) -> dict:
        if isinstance(context, dict):
            value = context.get("genre_quality_config") or {}
            return value if isinstance(value, dict) else {}
        value = getattr(context, "genre_quality_config", None)
        return value if isinstance(value, dict) else {}

    @classmethod
    def _modern_drift_patterns(cls, context: object | None = None) -> tuple[str, ...]:
        value = cls._genre_quality_config(context).get("modern_drift_patterns") or ()
        if not isinstance(value, (list, tuple, set)):
            return ()
        return tuple(str(item) for item in value if str(item).strip())

    @classmethod
    def _modern_drift_rule_text(cls, context: object | None = None) -> str:
        patterns = cls._modern_drift_patterns(context)
        if patterns:
            return "、".join(patterns[:12])
        return "与当前设定时代、职业、技术水平或文风不匹配的现代/外文词"

    @classmethod
    def _modern_terms_authorized(cls, context: object | None) -> bool:
        policy = cls._genre_quality_config(context).get("modern_terms_policy")
        if policy == "allow":
            return True
        if policy == "block":
            return False
        if context is None:
            return False
        text = cls._context_text(context)
        if not text:
            return False
        if any(marker in text for marker in cls.MODERN_AUTHORIZATION_MARKERS):
            return True
        return False

    @classmethod
    def _context_text(cls, context: object) -> str:
        if isinstance(context, dict):
            parts = []
            for key in (
                "genre",
                "era",
                "setting",
                "style_guide",
                "worldview_summary",
                "story_contract",
                "style_config",
            ):
                value = context.get(key)
                if value is not None:
                    parts.append(str(value))
            return "\n".join(parts)
        attrs = []
        for attr in ("style_profile", "worldview_summary", "story_contract"):
            if hasattr(context, attr):
                attrs.append(str(getattr(context, attr)))
        return "\n".join(attrs)
