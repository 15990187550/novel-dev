import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from novel_dev.agents._llm_helpers import coerce_to_text
from novel_dev.schemas.outline import SynopsisData, SynopsisVolumeOutline


@dataclass
class ExecutableNarrativeConstraint:
    """A setting rule converted into promptable and partly checkable constraints."""

    constraint_type: str
    title: str
    priority: str = "hard"
    terms: list[str] = field(default_factory=list)
    source: str = ""
    instruction: str = ""

    def to_prompt_line(self) -> str:
        terms = " -> ".join(self.terms) if self.constraint_type == "sequence" else "；".join(self.terms)
        suffix = f"：{terms}" if terms else ""
        instruction = f"；{self.instruction}" if self.instruction else ""
        return f"[{self.priority}/{self.constraint_type}] {self.title}{suffix}{instruction}"


@dataclass
class ActiveConstraintContext:
    MAX_ITEMS_PER_SECTION = 8
    MAX_ITEM_CHARS = 240

    volume_number: int
    active_domains: list[str] = field(default_factory=list)
    current_scope: list[str] = field(default_factory=list)
    allowed_conflicts: list[str] = field(default_factory=list)
    foreshadow_only: list[str] = field(default_factory=list)
    forbidden_now: list[str] = field(default_factory=list)
    continuity_rules: list[str] = field(default_factory=list)
    power_ladder: list[str] = field(default_factory=list)
    knowledge_boundaries: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    source_snippets: list[str] = field(default_factory=list)
    executable_constraints: list[ExecutableNarrativeConstraint] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        def lines(values: Iterable[str]) -> str:
            cleaned = []
            for value in values:
                text = value.strip() if value else ""
                if not text:
                    continue
                cleaned.append(text[: self.MAX_ITEM_CHARS])
                if len(cleaned) >= self.MAX_ITEMS_PER_SECTION:
                    break
            return "\n".join(f"- {value}" for value in cleaned) if cleaned else "- 无明确记录"

        return (
            "### 当前卷叙事约束包 ActiveConstraintContext\n"
            f"当前卷: 第 {self.volume_number} 卷\n"
            "激活规则域/体系:\n"
            f"{lines(self.active_domains)}\n"
            "当前阶段边界:\n"
            f"{lines(self.current_scope)}\n"
            "本卷允许使用的冲突类型:\n"
            f"{lines(self.allowed_conflicts)}\n"
            "只能作为伏笔/传闻/残痕/远景影子的内容:\n"
            f"{lines(self.foreshadow_only)}\n"
            "当前阶段禁止正面展开的内容:\n"
            f"{lines(self.forbidden_now)}\n"
            "连续性规则:\n"
            f"{lines(self.continuity_rules)}\n"
            "允许使用的层级/境界/能力阶梯原文:\n"
            f"{lines(self.power_ladder)}\n"
            "知识边界/缺口:\n"
            f"{lines(self.knowledge_boundaries)}\n"
            "待确认问题:\n"
            f"{lines(self.open_questions)}\n"
            "动态检索到的相关设定片段:\n"
            f"{lines(self.source_snippets)}\n"
            "可执行设定约束(必须优先遵守):\n"
            f"{lines([item.to_prompt_line() for item in self.executable_constraints])}"
        )


class NarrativeConstraintBuilder:
    """Build generic stage constraints for synopsis and volume planning.

    The builder is deliberately domain-agnostic: it does not assume fan fiction.
    Source-work rules, original cultivation rules, urban business hierarchy, and
    sci-fi technology limits are all treated as active narrative domains.
    """

    _DOMAIN_TITLE_PATTERN = re.compile(r"^[#>\-\s]*([\w\u4e00-\u9fff·《》：:]{2,30})")

    def build_for_volume(
        self,
        *,
        synopsis: SynopsisData,
        volume_number: int,
        source_text: str = "",
        world_snapshot: dict[str, Any] | None = None,
    ) -> ActiveConstraintContext:
        previous_outline = self._find_outline(synopsis, volume_number - 1)
        current_outline = self._find_outline(synopsis, volume_number)
        next_outline = self._find_outline(synopsis, volume_number + 1)
        scope_text = self._join_outline_text(previous_outline, current_outline, next_outline)
        query_text = "\n".join([
            synopsis.title,
            synopsis.logline,
            synopsis.core_conflict,
            scope_text,
        ])

        context = ActiveConstraintContext(
            volume_number=volume_number,
            active_domains=self._extract_active_domains(source_text, query_text, synopsis),
            current_scope=self._build_scope(volume_number, previous_outline, current_outline, world_snapshot),
            allowed_conflicts=self._build_allowed_conflicts(current_outline, synopsis),
            foreshadow_only=self._build_foreshadow_only(current_outline, next_outline),
            forbidden_now=self._build_forbidden_now(current_outline, next_outline),
            continuity_rules=self._build_continuity_rules(previous_outline, current_outline),
            source_snippets=self._select_relevant_snippets(source_text, query_text),
        )
        context.power_ladder = self._extract_power_ladders(source_text)
        context.executable_constraints = self._build_executable_constraints(
            context=context,
            query_text=query_text,
            current_outline=current_outline,
        )
        return context

    def build_for_volume_batch(
        self,
        *,
        synopsis: SynopsisData,
        start: int,
        end: int,
        source_text: str,
    ) -> str:
        blocks = [
            self.build_for_volume(
                synopsis=synopsis,
                volume_number=number,
                source_text=source_text,
            ).to_prompt_block()
            for number in range(start, end + 1)
        ]
        return "\n\n".join(blocks)

    def _find_outline(self, synopsis: SynopsisData, volume_number: int) -> SynopsisVolumeOutline | None:
        if volume_number <= 0:
            return None
        return next((item for item in synopsis.volume_outlines or [] if item.volume_number == volume_number), None)

    def _join_outline_text(self, *outlines: SynopsisVolumeOutline | None) -> str:
        parts = []
        for outline in outlines:
            if not outline:
                continue
            parts.append(outline.model_dump_json())
        return "\n".join(parts)

    def _build_scope(
        self,
        volume_number: int,
        previous: SynopsisVolumeOutline | None,
        current: SynopsisVolumeOutline | None,
        world_snapshot: dict[str, Any] | None,
    ) -> list[str]:
        scope = [
            "以当前卷主角能力、认知范围、活动地图为上限，不得直接跳到终局层级。",
            "若外部规则域/原著体系信息不足，必须保守处理为局部现象或待确认线索。",
        ]
        if previous and previous.end_state:
            scope.append(f"上一卷结束状态: {previous.end_state}")
        if current:
            if current.start_state:
                scope.append(f"本卷起点: {current.start_state}")
            if current.end_state:
                scope.append(f"本卷终点: {current.end_state}")
            if current.main_goal:
                scope.append(f"本卷目标: {current.main_goal}")
        if world_snapshot:
            if world_snapshot.get("entities"):
                scope.append("必须承接前卷活跃人物状态，不得无解释重置人物关系。")
            if world_snapshot.get("foreshadowings"):
                scope.append("优先回收或推进前卷未回收伏笔，不得随意遗忘。")
        if not current:
            scope.append(f"第 {volume_number} 卷缺少明确卷契约，需从总纲保守推导。")
        return scope

    def _build_allowed_conflicts(
        self,
        current: SynopsisVolumeOutline | None,
        synopsis: SynopsisData,
    ) -> list[str]:
        conflicts = [
            "使用与本卷目标直接相关、主角当前阶段可触达的局部冲突。",
            "高阶势力只能通过代理人、残痕、传闻、制度压力或低阶投影间接影响当前卷。",
        ]
        if current and current.main_conflict:
            conflicts.insert(0, f"本卷核心冲突: {current.main_conflict}")
        elif synopsis.core_conflict:
            conflicts.insert(0, f"总纲核心冲突的阶段化版本: {synopsis.core_conflict}")
        if current and current.climax:
            conflicts.append(f"卷级高潮需围绕: {current.climax}")
        return conflicts

    def _build_foreshadow_only(
        self,
        current: SynopsisVolumeOutline | None,
        next_outline: SynopsisVolumeOutline | None,
    ) -> list[str]:
        values = [
            "下一卷或终局才展开的世界、势力、敌人、能力层级，只能作为伏笔出现。",
            "未在当前设定中明确可触达的高阶概念，只能写成线索、残痕、异常、梦兆、传闻或误判。",
        ]
        if current:
            values.extend(f"本卷伏笔: {item}" for item in current.foreshadowing_setup[:4])
            if current.hook_to_next:
                values.append(f"卷末钩子仅用于引出后续: {current.hook_to_next}")
        if next_outline:
            if next_outline.title:
                values.append(f"下一卷《{next_outline.title}》的核心内容不得提前正面解决。")
            if next_outline.main_goal:
                values.append(f"下一卷目标只能预告，不得在本卷完成: {next_outline.main_goal}")
        return values

    def _build_forbidden_now(
        self,
        current: SynopsisVolumeOutline | None,
        next_outline: SynopsisVolumeOutline | None,
    ) -> list[str]:
        forbidden = [
            "禁止让主角正面接触或击败当前阶段无法触达的终局敌人/最高权力/最高科技/最高境界。",
            "禁止用模型常识硬编未提供的关键设定；缺信息时必须标记为待确认或降级为伏笔。",
            "禁止把后续卷的核心目标、高潮、终局真相提前完成。",
        ]
        if next_outline and next_outline.climax:
            forbidden.append(f"下一卷高潮不得提前完成: {next_outline.climax}")
        if current and current.foreshadowing_payoff:
            forbidden.append("只回收本卷明确列出的伏笔；未列出的远景伏笔不要强行揭底。")
        return forbidden

    def _build_continuity_rules(
        self,
        previous: SynopsisVolumeOutline | None,
        current: SynopsisVolumeOutline | None,
    ) -> list[str]:
        rules = [
            "每一卷都必须承接上一卷 end_state，并把本卷 end_state 留给后续卷使用。",
            "主角能力、信息、资源、关系只能渐进变化；重大跃迁必须有明确代价与事件支撑。",
            "用户已删除或未批准的旧设定不得凭历史生成结果重新引入。",
        ]
        if previous and previous.hook_to_next:
            rules.append(f"需承接上一卷钩子: {previous.hook_to_next}")
        if current and current.relationship_shifts:
            rules.append("关系推进需落实: " + "；".join(current.relationship_shifts[:4]))
        return rules

    def _extract_active_domains(
        self,
        source_text: str,
        query_text: str,
        synopsis: SynopsisData,
    ) -> list[str]:
        candidates = [synopsis.title, "本书原创主线"]
        for key, values in (synopsis.entity_highlights or {}).items():
            if key in {"factions", "locations", "items", "characters", "systems", "worlds"}:
                candidates.extend(values[:8])
        for line in source_text.splitlines()[:120]:
            text = line.strip()
            if not text:
                continue
            match = self._DOMAIN_TITLE_PATTERN.match(text)
            if match:
                title = match.group(1).strip(" #>-：:")
                if 2 <= len(title) <= 24:
                    candidates.append(title)

        query = query_text + "\n" + source_text[:2000]
        active = []
        seen = set()
        for candidate in candidates:
            value = coerce_to_text(candidate).strip()
            if not value or value in seen:
                continue
            if value == "本书原创主线" or value in query:
                active.append(value)
                seen.add(value)
            if len(active) >= 8:
                break
        return active or ["本书原创主线"]

    def _select_relevant_snippets(self, source_text: str, query_text: str) -> list[str]:
        text = coerce_to_text(source_text)
        if not text.strip():
            return []

        tokens = self._keyword_tokens(query_text)
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        scored: list[tuple[int, str]] = []
        for paragraph in paragraphs:
            score = sum(1 for token in tokens if token and token in paragraph)
            if score:
                scored.append((score, paragraph[:280]))
        scored.sort(key=lambda item: item[0], reverse=True)
        if scored:
            return [snippet for _, snippet in scored[:5]]
        return [text[:500]]

    def _extract_power_ladders(self, source_text: str) -> list[str]:
        ladders: list[str] = []
        for raw_line in coerce_to_text(source_text).splitlines():
            line = raw_line.strip(" -\t")
            if "→" not in line and "->" not in line:
                continue
            if not any(marker in line for marker in ("体系", "境界", "阶梯", "等级", "层级", "修炼", "流程", "路线")):
                continue
            line = re.sub(r"^[#>*\-\s]+", "", line)
            if 8 <= len(line) <= 500 and line not in ladders:
                ladders.append(line)
            if len(ladders) >= 8:
                break
        return ladders

    def _build_executable_constraints(
        self,
        *,
        context: ActiveConstraintContext,
        query_text: str,
        current_outline: SynopsisVolumeOutline | None,
    ) -> list[ExecutableNarrativeConstraint]:
        constraints: list[ExecutableNarrativeConstraint] = []
        # Sequence constraints are executable for the current volume only.
        # Global synopsis text often contains terminal states (for example
        # "超脱") that should guide long-range direction but should not become
        # mandatory chapter nodes in volume one.
        scope_text = "\n".join([
            current_outline.model_dump_json() if current_outline else query_text,
            "\n".join(context.current_scope),
        ])

        for ladder in context.power_ladder:
            chain = self._parse_sequence_terms(ladder)
            if len(chain) < 3:
                continue
            required = self._derive_required_sequence_terms(chain, scope_text)
            if len(required) < 2:
                continue
            constraints.append(
                ExecutableNarrativeConstraint(
                    constraint_type="sequence",
                    title=self._constraint_title_from_source(ladder),
                    priority="hard",
                    terms=required,
                    source=ladder,
                    instruction="若本卷从前序节点推进到后序节点，必须按顺序覆盖中间节点，不得跳步或只用一句话带过。",
                )
            )

        for value in context.forbidden_now[:6]:
            terms = self._extract_named_terms(value)
            constraints.append(
                ExecutableNarrativeConstraint(
                    constraint_type="boundary",
                    title="当前阶段边界",
                    priority="hard",
                    terms=terms,
                    source=value,
                    instruction=value,
                )
            )

        for value in context.foreshadow_only[:6]:
            terms = self._extract_named_terms(value)
            constraints.append(
                ExecutableNarrativeConstraint(
                    constraint_type="boundary",
                    title="伏笔限定",
                    priority="hard",
                    terms=terms,
                    source=value,
                    instruction=value,
                )
            )

        for value in context.source_snippets[:6]:
            terms = self._extract_named_terms(value)
            constraints.append(
                ExecutableNarrativeConstraint(
                    constraint_type="fact",
                    title="已检索设定事实",
                    priority="hard",
                    terms=terms,
                    source=value,
                    instruction=f"不得与该设定事实冲突: {value[:180]}",
                )
            )

        return constraints[:16]

    def _parse_sequence_terms(self, text: str) -> list[str]:
        segment = coerce_to_text(text)
        if "：" in segment:
            segment = segment.split("：", 1)[1]
        elif ":" in segment:
            segment = segment.split(":", 1)[1]
        segment = segment.replace("->", "→")
        raw_terms = [part.strip() for part in segment.split("→")]
        terms: list[str] = []
        seen = set()
        for raw in raw_terms:
            term = re.sub(r"[。；;，,].*$", "", raw).strip()
            term = re.sub(r"^[\s\-*]+", "", term)
            term = re.sub(r"\s+", "", term)
            if not term:
                continue
            if len(term) > 36:
                term = term[:36]
            expanded = self._expand_sequence_term(term)
            for item in expanded:
                if item not in seen:
                    terms.append(item)
                    seen.add(item)
        return terms

    def _expand_sequence_term(self, term: str) -> list[str]:
        base = re.sub(r"[（(].*?[）)]", "", term).strip()
        inner_terms: list[str] = []
        for inner in re.findall(r"[（(](.*?)[）)]", term):
            inner_terms.extend(part.strip() for part in re.split(r"[+/、，,;；]", inner) if part.strip())
        expanded = []
        for item in [base or term, *inner_terms]:
            value = item.strip()
            if value and value not in expanded:
                expanded.append(value)
        return expanded or [term]

    def _derive_required_sequence_terms(self, chain: list[str], scope_text: str) -> list[str]:
        matched_indexes = [
            index
            for index, term in enumerate(chain)
            if self._term_has_independent_match(term, scope_text, chain)
        ]
        if len(matched_indexes) < 2:
            return []
        start = min(matched_indexes)
        end = max(matched_indexes)
        if end <= start:
            return []
        return chain[start : end + 1]

    def _term_has_independent_match(self, term: str, text: str, chain: list[str]) -> bool:
        candidates = [term, *self._term_aliases(term)]
        longer_terms = [item for item in chain if item != term and term in item and len(item) > len(term)]
        for candidate in candidates:
            if not candidate:
                continue
            start = 0
            while True:
                position = text.find(candidate, start)
                if position < 0:
                    break
                end = position + len(candidate)
                inside_longer = any(
                    self._position_inside_any_occurrence(text, longer, position)
                    for longer in longer_terms
                )
                if not inside_longer:
                    return True
                start = end
        return False

    def _position_inside_any_occurrence(self, text: str, needle: str, position: int) -> bool:
        if not needle:
            return False
        start = 0
        while True:
            found = text.find(needle, start)
            if found < 0:
                return False
            if found <= position < found + len(needle):
                return True
            start = found + len(needle)

    def _term_in_text(self, term: str, text: str) -> bool:
        if term in text:
            return True
        aliases = self._term_aliases(term)
        return any(alias and alias in text for alias in aliases)

    def _term_aliases(self, term: str) -> list[str]:
        aliases = []
        cleaned = re.sub(r"[（(].*?[）)]", "", term).strip()
        if cleaned and cleaned != term:
            aliases.append(cleaned)
        for inner in re.findall(r"[（(](.*?)[）)]", term):
            aliases.extend(part.strip() for part in re.split(r"[+/、，,;；]", inner) if part.strip())
        return aliases

    def _constraint_title_from_source(self, source: str) -> str:
        title = source.split("：", 1)[0].split(":", 1)[0].strip(" #>-")
        return title[:32] or "顺序设定"

    def _extract_named_terms(self, text: str) -> list[str]:
        terms = re.findall(r"《[^》]{2,30}》|[\u4e00-\u9fffA-Za-z0-9·]{2,20}", coerce_to_text(text))
        stopwords = {"当前阶段", "下一卷", "本卷", "只能", "作为", "伏笔", "不得", "禁止", "完成", "出现"}
        result = []
        for term in terms:
            value = term.strip("《》")
            if value in stopwords or value in result:
                continue
            result.append(value)
            if len(result) >= 8:
                break
        return result

    def _keyword_tokens(self, text: str) -> list[str]:
        raw = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_]{2,}", text)
        stopwords = {"当前", "本卷", "总纲", "核心", "冲突", "目标", "阶段", "主角", "关系"}
        tokens = []
        seen = set()
        for token in raw:
            if token in stopwords or token in seen:
                continue
            tokens.append(token)
            seen.add(token)
            if len(tokens) >= 40:
                break
        return tokens
