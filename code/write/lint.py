# -*- coding: utf-8 -*-
"""연구개발계획서 양식 검사기 (결정론적).

PROMPT_WRITER 의 [작성양식]·[분량 규칙]·[문체]·[표기 규칙] 중 코드로 잴 수 있는 것을 잰다.
LLM 은 글자수를 세지 못하고 Reviewer 프롬프트는 분량을 심사하지 않도록 되어 있어, 과거 산출물은
한 건도 분량 규칙을 지키지 못했다. 여기서 측정한 값을 Writer 에게 수정 지시로 돌려준다
(lint_loop.lint_fix_loop). 순수 함수이므로 LLM·네트워크 없이 테스트할 수 있다.

양식의 숫자·라벨은 이 모듈이 아니라 write/spec.py 에 있다. Writer 프롬프트도 같은 곳에서 값을
받으므로 검사기와 프롬프트가 어긋난 규칙을 말하는 일이 없다 — 어긋나면 Writer 가 지킬 수 없는
지적이 수정 루프를 다 소진한다. 양식을 고칠 때는 write/spec.py 만 고친다.

검사 항목
  구조   제목(#), ## 섹션·### 항목의 존재·순서·명칭, 모듈 1~3 과 각 모듈의 하위 불릿 3개
         (입력과 출력의 정의 → 핵심 메커니즘 → 채택 근거), 양식 밖 소제목
  개수   항목별 상위 불릿 수 (양식 지정값). 지정 +LINT_BULLET_SLACK 까지 경고, 그 이상 오류. 부족은 경고
  분량   항목별 글자수(공백 제외). 목표 +LINT_LENGTH_WARN 까지 통과, ~+LINT_LENGTH_ERROR 경고, 초과 오류.
         부족은 -LINT_LENGTH_UNDER_WARN 아래만 경고. 전체 3,440자는 +LINT_TOTAL_ERROR 초과만 오류 (참고문헌 제외)
  문체   연구 요약은 산문 5문장(±1), 그 외 불릿의 "~다" 종결 금지, "첫째/둘째/셋째" 금지
  표기   금지 표현, 마크다운 강조, 인라인 수식, 그림 언급, 인용 위치(연구 필요성만), 인용 형식(연도),
         같은 출처 2회 초과
  인용   [Author et al., Year] 가 학술 카드(arxiv_cards)에 실재하는지 (제1저자 성 + 연도)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.config import (
    LINT_BULLET_SLACK,
    LINT_LENGTH_ERROR,
    LINT_LENGTH_UNDER_WARN,
    LINT_LENGTH_WARN,
    LINT_TOTAL_ERROR,
)
# 양식(섹션·글자수·불릿 수·라벨·금지 표현)은 write/spec.py 하나에만 있다. Writer 프롬프트도 같은
# 곳에서 값을 받으므로, 검사기와 프롬프트가 서로 다른 숫자를 말하는 일이 생기지 않는다.
# 아래는 이 모듈을 통해 임포트하는 곳(finalize/cleanup.py, finalize/references.py)을 위한 재수출이다.
from write.spec import (               # noqa: F401 - 재수출
    BODY_CHARS,
    CITATION_ALLOWED_IN,
    FORBIDDEN_VAGUE_PARTIAL,
    FORBIDDEN_WORDS,
    MAX_SAME_CITATION,
    MODULE_CHARS,
    MODULE_COUNT,
    MODULE_LABELS,
    OVERVIEW_BULLETS,
    OVERVIEW_CHARS,
    REFERENCE_KEYS,
    SECTION_SPEC,
    SUMMARY_SENTENCES,
    TITLE_CHARS,
    TITLE_MAX_CHARS,
    TITLE_MIN_CHARS,
    TITLE_PLACEHOLDERS,
    TOTAL_CHARS,
)

#: 문맥 제한이 필요한 금지 표현 — 뒤에 오는 말에 따라 정상 용법이 있어 전체 일치로 잡지 않는다
_PARTIAL_PATTERNS = {"여러": r"여러(?=\s|가지|개\b|번\b|명\b|편\b)"}
assert set(FORBIDDEN_VAGUE_PARTIAL) <= set(_PARTIAL_PATTERNS), \
    f"문맥 제한 금지 표현에 정규식이 없음: {sorted(set(FORBIDDEN_VAGUE_PARTIAL) - set(_PARTIAL_PATTERNS))}"
_FORBIDDEN_RES = ([re.compile(re.escape(w)) for w in FORBIDDEN_WORDS]
                  + [re.compile(_PARTIAL_PATTERNS[w]) for w in FORBIDDEN_VAGUE_PARTIAL])
_FORBIDDEN_NAMES = FORBIDDEN_WORDS + list(FORBIDDEN_VAGUE_PARTIAL)

CITE_RE = re.compile(r"\[([A-Z][A-Za-z\-']+)(?:\s+et\s+al\.)?,?\s*(\d{4})\]")
CITE_NOYEAR_RE = re.compile(r"\[([A-Z][A-Za-z\-']+)(?:\s+et\s+al\.)?\]")
_ORDINAL_RE = re.compile(r"(첫째|둘째|셋째|넷째)[,\s]")
_BOLD_RE = re.compile(r"\*\*[^*]+\*\*|(?<![\w*])\*[^*\s][^*\n]*?\*(?![\w*])")
_MATH_RE = re.compile(r"\$[^$\n]+\$")
_FIGURE_RE = re.compile(r"\[그림\s*\d+\]|!\[[^\]]*\]\(|(?<![가-힣])그림\s*\d+\s*[.:]")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*$")
_TOP_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_SUB_BULLET_RE = re.compile(r"^\s{1,}[-*]\s+(.*)$")
_MODULE_RE = re.compile(r"^모듈\s*(\d+)\s*[:：]\s*(.*)$")
# 경량 모델이 작성양식을 그대로 베낀 흔적. 검사기가 이름을 붙여 지목해야 수정 프롬프트가 고칠 수 있다.
_HEADING_NOTE_RE = re.compile(r"\s*[—–-]\s*[\d,]+\s*자.*$")          # "연구 배경 — 770자, 상위 불릿 3개"
_HEADING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")                   # "연구 주제(문제 정의)"
_TEMPLATE_MARK_RE = re.compile(r"^\s*([■●])")                          # 양식 기호로 시작하는 줄
_NUMBERED_MODULE_RE = re.compile(r"^\s*\d+\)\s*모듈\s*\d")            # "2) 모듈 1: …" (#### 소제목이어야 함)
_CARD_ID_RE = re.compile(r"\[(?:[ABC]-\d{2})(?:\s*,\s*[ABC]-\d{2})*\]")   # 카드 ID 인용 [A-06, A-07]


# ── 결과 자료구조 ────────────────────────────────────────────────────────────────

@dataclass
class Issue:
    code: str            # length_over, bullets_over, forbidden_word, citation_outside, citation_unknown, ...
    severity: str        # "error" | "warning"
    where: str           # "3. 연구 방법론 > 실험 및 평가"
    message: str         # 수정 지시 (한국어, 측정값 포함)
    quote: str = ""      # 문제 불릿 인용

    def render(self) -> str:
        q = f'  ← "{self.quote}"' if self.quote else ""
        return f"[{_CODE_LABEL.get(self.code, self.code)}] {self.where}: {self.message}{q}"


_CODE_LABEL = {
    "missing_title": "제목 없음", "title_long": "제목 길이", "title_placeholder": "제목 자리표시자",
    "title_stray": "제목 아래 본문",
    "missing_section": "섹션 누락", "extra_section": "양식 밖 소제목", "section_order": "섹션 순서",
    "missing_module": "모듈 누락", "module_structure": "모듈 구조",
    "bullets_over": "불릿 초과", "bullets_under": "불릿 부족",
    "length_over": "분량 초과", "length_under": "분량 부족", "length_total": "전체 분량",
    "summary_style": "연구 요약 문체", "summary_sentences": "연구 요약 문장 수",
    "ending": "종결어미", "ordinal": "첫째·둘째 나열",
    "forbidden_word": "금지 표현", "markdown_emphasis": "마크다운 강조", "inline_math": "인라인 수식",
    "figure_mention": "그림 언급",
    "heading_annotation": "제목 주석", "template_marker": "양식 기호", "card_id_citation": "카드 ID 인용",
    "citation_outside": "인용 위치", "citation_noyear": "인용 형식", "citation_repeat": "인용 반복",
    "citation_unknown": "실재하지 않는 인용", "citation_unverified": "인용 확인 불가",
}


@dataclass
class LintReport:
    issues: List[Issue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if not self.issues:
            return "위반 없음"
        by_code: Dict[str, int] = {}
        for i in self.errors:
            by_code[_CODE_LABEL.get(i.code, i.code)] = by_code.get(_CODE_LABEL.get(i.code, i.code), 0) + 1
        detail = ", ".join(f"{k} {v}" for k, v in by_code.items())
        return f"오류 {len(self.errors)}" + (f" ({detail})" if detail else "") + f" / 경고 {len(self.warnings)}"

    def to_instructions(self, max_items: int = 25) -> str:
        """Writer 수정 프롬프트에 넣는 지시문. 오류를 먼저, 경고는 '가능하면' 으로."""
        lines: List[str] = []
        errors, warnings = self.errors, self.warnings
        if errors:
            lines.append("반드시 고칠 것 (오류):")
            for n, i in enumerate(errors[:max_items], 1):
                lines.append(f"{n}. {i.render()}")
            if len(errors) > max_items:
                lines.append(f"... 외 {len(errors) - max_items}건")
        if warnings:
            lines.append("")
            lines.append("가능하면 고칠 것 (경고 — 근거 없는 내용을 추가하지는 말 것):")
            for i in warnings[:10]:
                lines.append(f"- {i.render()}")
        total = self.metrics.get("total_chars")
        if total is not None:
            lines.append("")
            lines.append(f"측정: 본문 {total}자 (목표 {BODY_CHARS} = 전체 {TOTAL_CHARS} − 연구명 {TITLE_CHARS}, "
                         "참고문헌·제목 제외, 공백 제외)")
        return "\n".join(lines) if lines else "위반 없음"


# ── 파싱 ────────────────────────────────────────────────────────────────────────

@dataclass
class Node:
    level: int
    title: str                # 원문 제목
    key: str                  # 번호·공백 정리한 키
    lines: List[str] = field(default_factory=list)      # 이 제목 바로 아래 본문 (하위 제목 제외)
    children: List["Node"] = field(default_factory=list)

    def own_text(self) -> str:
        return "\n".join(self.lines)

    def all_text(self) -> str:
        parts = [self.own_text()] + [c.all_text() for c in self.children]
        return "\n".join(p for p in parts if p)


def stray_lead(text: str) -> str:
    """'# 제목' 줄과 첫 '## 섹션' 사이에 남은 본문 줄. 양식상 비어 있어야 한다.

    파서는 이 구간의 줄을 어느 섹션에도 넣지 못해 버린다. 그래서 검사기가 원문에서 따로 찾아야
    "연구명을 제목 줄이 아니라 그 아래에 쓴" 경우를 잡을 수 있다.
    """
    m = re.search(r"^#\s+.*$", text or "", re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    lead = rest[: nxt.start()] if nxt else rest
    lines = [ln.strip() for ln in lead.splitlines() if ln.strip()]
    return lines[0] if lines else ""


def _norm_key(title: str) -> str:
    """제목을 양식 키로: 번호("1." "3.2"), 양식 주석("— 770자"), 끝 괄호("(문제 정의)"), 끝 콜론을 뗀다.
    그래야 "## 1. 연구 배경 — 770자" 도 연구 배경 섹션으로 인식하고, 주석은 별도 오류(heading_annotation)로 지목한다."""
    t = re.sub(r"^\d+(?:\.\d+)*\s*[.．)]?\s*", "", title.strip())
    t = _HEADING_NOTE_RE.sub("", t)
    t = _HEADING_PAREN_RE.sub("", t)
    return " ".join(t.rstrip(":：").split())


def parse_document(text: str) -> Tuple[Optional[str], List[Node]]:
    """마크다운을 (제목, [## 섹션 노드]) 로. 각 섹션은 ### 자식, ### 는 #### 자식을 가진다."""
    title: Optional[str] = None
    roots: List[Node] = []
    stack: List[Node] = []
    for raw in text.splitlines():
        m = _HEADING_RE.match(raw)
        if m:
            level, heading = len(m.group(1)), m.group(2).strip()
            if level == 1:
                if title is None:
                    title = heading
                stack = []
                continue
            node = Node(level=level, title=heading, key=_norm_key(heading))
            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            elif level == 2:
                roots.append(node)
            else:
                roots.append(node)          # ## 없이 나온 ###/#### — 구조 오류로 뒤에서 잡힘
            stack.append(node)
        elif stack:
            stack[-1].lines.append(raw.rstrip())
    return title, roots


def count_chars(text: str) -> int:
    """공백 제외 글자수. 불릿 마커와 제목 표식은 세지 않는다."""
    cleaned = re.sub(r"^\s*[-*]\s+", "", text, flags=re.M)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.M)
    return len(re.sub(r"\s+", "", cleaned))


def top_bullets(text: str) -> List[str]:
    return [m.group(1).strip() for ln in text.splitlines() for m in [_TOP_BULLET_RE.match(ln)] if m]


def all_bullets(text: str) -> List[Tuple[bool, str]]:
    """(상위 여부, 텍스트) 목록."""
    out = []
    for ln in text.splitlines():
        m = _TOP_BULLET_RE.match(ln)
        if m:
            out.append((True, m.group(1).strip()))
            continue
        m = _SUB_BULLET_RE.match(ln)
        if m:
            out.append((False, m.group(1).strip()))
    return out


def _find(children: List[Node], key: str) -> Optional[Node]:
    return next((c for c in children if c.key == key), None)


def _is_reference(node: Node) -> bool:
    return node.key in REFERENCE_KEYS


def _short(s: str, n: int = 70) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


# ── 인용 ↔ 카드 대조 ─────────────────────────────────────────────────────────────

def first_author_tokens(card: Dict[str, Any]) -> List[str]:
    """카드의 제1저자 이름 토큰(소문자). 'Reza Jafari Ziarani, Reza Ravanmehr 외' → ['reza','jafari','ziarani']"""
    authors = str(card.get("authors") or "")
    first = re.split(r",|;| and ", authors)[0]
    first = re.sub(r"\s+외$", "", first).strip()
    tokens = re.split(r"[\s\-]+", first)
    return [t.lower().strip(".") for t in tokens if t.strip(".")]


def card_matches(surname: str, year: str, card: Dict[str, Any]) -> bool:
    if str(card.get("year") or "") != str(year):
        return False
    s = surname.lower()
    return s in first_author_tokens(card)


def find_card(surname: str, year: str, cards: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for c in cards:
        if card_matches(surname, year, c):
            return c
    # 제1저자가 아닌 저자를 인용했을 가능성 — 어느 저자든 성이 맞고 연도가 같으면 허용
    for c in cards:
        if str(c.get("year") or "") == str(year) and surname.lower() in str(c.get("authors") or "").lower():
            return c
    return None


# ── 검사 본체 ───────────────────────────────────────────────────────────────────

def lint(text: str, cards: Optional[List[Dict[str, Any]]] = None) -> LintReport:
    """계획서 마크다운을 검사해 LintReport 를 돌려준다. cards 는 학술 카드(dict) 목록 (인용 실재 확인용)."""
    report = LintReport()
    issues = report.issues
    cards = cards or []
    title, roots = parse_document(text)

    # 제목
    lead = stray_lead(text)
    if not title:
        issues.append(Issue("missing_title", "error", "연구명",
                            "첫 줄에 '# ' 로 시작하는 연구명 줄이 없음. 실제 연구 제목을 쓴다"))
    else:
        bare = title.strip().strip("()[]（）").strip()
        n_title = count_chars(title)
        if bare in TITLE_PLACEHOLDERS or n_title < TITLE_MIN_CHARS:
            # 양식의 자리표시자를 그대로 두었거나 제목이 비어 있다시피 하다. 표지 제목이 "연구명" 으로 찍힌다.
            recover = (f' 바로 아래 줄 "{_short(lead)}" 이 실제 연구명이면 그 줄을 "# " 뒤로 올리고 아래 줄은 지운다.'
                       if lead else "")
            issues.append(Issue("title_placeholder", "error", "연구명",
                                f"제목이 양식의 이름이거나 너무 짧음({n_title}자, 최소 {TITLE_MIN_CHARS}자). "
                                f"'# ' 뒤에 실제 연구명을 {TITLE_CHARS}자 내외 명사구로 쓴다.{recover}", _short(title)))
        elif n_title > TITLE_MAX_CHARS:
            issues.append(Issue("title_long", "warning", "연구명",
                                f"{n_title}자 ({TITLE_CHARS}자 내외 권장, 상한 {TITLE_MAX_CHARS}자)", _short(title)))
    if lead:
        issues.append(Issue("title_stray", "error", "연구명",
                            "제목 줄과 '## 연구 요약' 사이에 본문이 있음. 연구명이면 제목 줄로 올리고, 아니면 해당 항목으로 옮긴다",
                            _short(lead)))

    # 섹션 존재·순서·양식 밖 섹션
    expected_keys = [k for k, _, _ in SECTION_SPEC]
    found_sections = [r for r in roots if r.level == 2]
    for r in roots:
        if r.level != 2:
            issues.append(Issue("extra_section", "error", r.title, f"'{'#' * r.level} {r.title}' 이 ## 섹션 밖에 있음. 양식의 섹션 안으로 옮기거나 삭제"))
    present = [s.key for s in found_sections if s.key in expected_keys]
    if present != [k for k in expected_keys if k in present]:
        issues.append(Issue("section_order", "error", "문서", f"섹션 순서가 양식과 다름: {present}. 양식 순서로 재배열: {expected_keys}"))
    for s in found_sections:
        if s.key not in expected_keys and not _is_reference(s):
            issues.append(Issue("extra_section", "error", s.title, "양식에 없는 섹션. 삭제하거나 내용을 양식 항목에 합침"))

    # 양식을 베낀 표기: 제목 주석("— 770자"), ■/● 기호 줄, 번호 매긴 모듈 줄, 카드 ID 인용
    def _walk(nodes):
        for n in nodes:
            yield n
            yield from _walk(n.children)
    for node in _walk(roots):
        if _HEADING_NOTE_RE.search(node.title):
            issues.append(Issue("heading_annotation", "error", node.title,
                                f"제목 뒤의 양식 주석(글자수·불릿 수)을 삭제. '{'#' * node.level} {node.key}' 만 남긴다 (번호는 두어도 됨)"))
    marks: Dict[str, int] = {}
    numbered_modules = 0
    for raw in text.splitlines():
        m = _TEMPLATE_MARK_RE.match(raw)
        if m:
            marks[m.group(1)] = marks.get(m.group(1), 0) + 1
        if _NUMBERED_MODULE_RE.match(raw):
            numbered_modules += 1
        for m in _CARD_ID_RE.finditer(raw):
            issues.append(Issue("card_id_citation", "error", "본문",
                                f"카드 ID {m.group(0)} 를 본문에 쓰지 않는다. 표기만 삭제(문장은 유지). "
                                "학술 카드만 [Author et al., Year] 로 연구 필요성에 인용", _short(raw)))
    for mark, n in marks.items():
        level = "##" if mark == "■" else "###"
        issues.append(Issue("template_marker", "error", "문서",
                            f"'{mark}' 로 시작하는 줄 {n}개: 작성양식의 기호를 베낀 것. '{mark} 이름 — N자' 를 '{level} 이름' 소제목으로 바꾸고 "
                            "그 아래 불릿은 그대로 둔다"))
    if numbered_modules:
        issues.append(Issue("module_structure", "error", "제안 방법",
                            f"'N) 모듈 N: 이름' 줄 {numbered_modules}개. 모듈은 '#### 모듈 N: (모듈명)' 소제목으로 쓴다"))

    total_chars = 0
    citation_hits: List[Tuple[str, str, str, str]] = []      # (surname, year, where, quote)
    noyear_hits: List[Tuple[str, str]] = []
    body_bullets: List[Tuple[str, bool, str]] = []             # (where, is_top, text)  — 연구 요약 제외

    for sec_key, sec_chars, sub_spec in SECTION_SPEC:
        sec = _find(found_sections, sec_key)
        where_sec = sec.title if sec else sec_key
        if sec is None:
            issues.append(Issue("missing_section", "error", sec_key, f"'## {sec_key}' 섹션이 없음"))
            continue
        sec_text = sec.all_text()
        n_sec = count_chars(sec_text)
        total_chars += n_sec
        report.metrics[sec_key] = {"chars": n_sec, "target": sec_chars}

        if sec_key == "연구 요약":
            _check_summary(sec, issues)
            _check_length(where_sec, n_sec, sec_chars, issues)
            continue

        # 섹션 안의 ### 항목
        sub_keys = [k for k, _, _ in sub_spec]
        present_sub = [c.key for c in sec.children if c.key in sub_keys]
        if present_sub != [k for k in sub_keys if k in present_sub]:
            issues.append(Issue("section_order", "error", where_sec, f"항목 순서가 양식과 다름: {present_sub} → {sub_keys}"))
        for c in sec.children:
            if c.level == 3 and c.key not in sub_keys:
                issues.append(Issue("extra_section", "error", f"{where_sec} > {c.title}", "양식에 없는 소제목. 삭제하거나 지정 항목에 합침"))
            if c.level == 4:
                issues.append(Issue("extra_section", "error", f"{where_sec} > {c.title}", "#### 소제목은 '제안 방법' 의 모듈에만 쓴다"))
        if sec.lines and any(_TOP_BULLET_RE.match(ln) or _SUB_BULLET_RE.match(ln) for ln in sec.lines):
            issues.append(Issue("extra_section", "error", where_sec, "### 항목 밖(섹션 바로 아래)에 불릿이 있음. 해당 항목 안으로 옮김"))

        for sub_key, sub_chars, n_bullets in sub_spec:
            sub = _find(sec.children, sub_key)
            where = f"{where_sec} > {sub_key}"
            if sub is None:
                issues.append(Issue("missing_section", "error", where, f"'### {sub_key}' 항목이 없음"))
                continue
            sub_text = sub.all_text()
            n_sub = count_chars(sub_text)
            report.metrics[f"{sec_key} > {sub_key}"] = {"chars": n_sub, "target": sub_chars,
                                                          "bullets": len(top_bullets(sub.own_text()))}
            _check_length(where, n_sub, sub_chars, issues)
            if sub_key == "제안 방법":
                _check_proposal(sub, where, issues, report)
            else:
                if sub.children:
                    for c in sub.children:
                        issues.append(Issue("extra_section", "error", f"{where} > {c.title}", "이 항목에는 하위 소제목을 두지 않는다"))
                _check_bullet_count(where, len(top_bullets(sub.own_text())), n_bullets, issues)
            for is_top, b in all_bullets(sub_text):
                body_bullets.append((where, is_top, b))
                for m in CITE_RE.finditer(b):
                    citation_hits.append((m.group(1), m.group(2), sub_key, _short(b)))
                for m in CITE_NOYEAR_RE.finditer(b):
                    noyear_hits.append((where, _short(b)))

        _check_length(where_sec, n_sec, sec_chars, issues, section_level=True)

    # 합계는 섹션 본문만 센다 (# 연구명 줄은 어느 섹션에도 속하지 않는다) → 기준은 BODY_CHARS
    report.metrics["total_chars"] = total_chars
    total_err = int(BODY_CHARS * (1 + LINT_TOTAL_ERROR))
    total_warn = int(BODY_CHARS * (1 + LINT_LENGTH_WARN))
    if total_chars > total_err:
        issues.append(Issue("length_total", "error", "전체",
                            f"본문 {total_chars}자 (목표 {BODY_CHARS}, 상한 {total_err}). 초과가 큰 항목부터 압축"))
    elif total_chars > total_warn:
        issues.append(Issue("length_total", "warning", "전체",
                            f"본문 {total_chars}자 (목표 {BODY_CHARS}, 허용 {total_warn}). 가능하면 압축"))

    # 문체·표기 (연구 요약·참고문헌 제외 본문)
    for where, is_top, b in body_bullets:
        core = CITE_RE.sub("", b).strip().rstrip(".。 ")
        if core.endswith("다"):
            issues.append(Issue("ending", "error", where, "'~다' 종결. '~함/~임/~해야 함' 으로", _short(b)))
        if _ORDINAL_RE.search(b):
            issues.append(Issue("ordinal", "error", where, "'첫째/둘째/셋째' 나열 금지. 불릿을 나눔", _short(b)))
        for name, rx in zip(_FORBIDDEN_NAMES, _FORBIDDEN_RES):
            if rx.search(b):
                issues.append(Issue("forbidden_word", "error", where, f"금지 표현 '{name}'. 수량·조건을 명시하거나 표현을 뺌", _short(b)))
        if _BOLD_RE.search(b):
            issues.append(Issue("markdown_emphasis", "error", where, "마크다운 강조(** 또는 *) 금지", _short(b)))
        if _MATH_RE.search(b):
            issues.append(Issue("inline_math", "error", where, "인라인 수식 금지. 서술로 대체", _short(b)))
        if _FIGURE_RE.search(b):
            issues.append(Issue("figure_mention", "error", where, "그림을 본문에서 언급하지 않음 (조판 단계가 삽입)", _short(b)))

    # 인용
    for where, q in noyear_hits:
        issues.append(Issue("citation_noyear", "error", where, "인용에 연도가 없음. [Author et al., Year] 형식", q))
    counts: Dict[Tuple[str, str], int] = {}
    for surname, year, sub_key, q in citation_hits:
        counts[(surname.lower(), year)] = counts.get((surname.lower(), year), 0) + 1
        if sub_key not in CITATION_ALLOWED_IN:
            issues.append(Issue("citation_outside", "error", sub_key,
                                f"[{surname} et al., {year}] 인용은 {' · '.join(CITATION_ALLOWED_IN)}에만 허용. "
                                "인용 표기만 삭제(문장은 유지)", q))
    for (surname, year), n in counts.items():
        if n > MAX_SAME_CITATION:
            issues.append(Issue("citation_repeat", "error", CITATION_ALLOWED_IN[0],
                                f"[{surname.title()} et al., {year}] {n}회 (최대 {MAX_SAME_CITATION}회). 초과분의 인용 표기만 삭제"))
    if citation_hits:
        if not cards:
            issues.append(Issue("citation_unverified", "warning", "인용",
                                f"학술 카드가 없어 인용 {len(counts)}건의 실재 여부를 확인할 수 없음"))
        else:
            for (surname, year) in counts:
                if find_card(surname, year, cards) is None:
                    issues.append(Issue("citation_unknown", "error", CITATION_ALLOWED_IN[0],
                                        f"[{surname.title()} et al., {year}] 는 학술 카드에 없음. 카드에 있는 논문(저자·연도)으로 바꾸거나 인용을 삭제하고 주장 범위를 좁힘"))
    report.metrics["citations"] = len(citation_hits)
    report.metrics["unique_citations"] = len(counts)
    return report


def _check_length(where: str, n: int, target: int, issues: List[Issue], section_level: bool = False) -> None:
    """목표 대비 +WARN 까지 통과, ~+ERROR 는 경고, 초과는 오류. 부족은 -UNDER_WARN 아래만 경고."""
    if section_level:
        return                           # 섹션 합계는 항목별 판정으로 충분하다 (중복 지시 방지)
    warn_hi = int(target * (1 + LINT_LENGTH_WARN))
    err_hi = int(target * (1 + LINT_LENGTH_ERROR))
    lo = int(target * (1 - LINT_LENGTH_UNDER_WARN))
    if n > err_hi:
        issues.append(Issue("length_over", "error", where,
                            f"{n}자 (목표 {target}, 허용 {warn_hi}, 상한 {err_hi}). "
                            f"불릿을 삭제하지 말고 각 불릿을 압축해 {target}자 안팎으로"))
    elif n > warn_hi:
        issues.append(Issue("length_over", "warning", where,
                            f"{n}자 (목표 {target}, 허용 {warn_hi}). 가능하면 {target}자 안팎으로 압축"))
    elif n < lo:
        issues.append(Issue("length_under", "warning", where,
                            f"{n}자 (목표 {target}, 하한 {lo}). 증거에 있는 내용으로만 보강하거나 그대로 둠"))


def _check_bullet_count(where: str, n: int, expected: Optional[int], issues: List[Issue]) -> None:
    """지정보다 SLACK 개까지 많은 것은 경고, 그 이상은 오류. 적은 것은 경고."""
    if expected is None:
        return
    if n > expected + LINT_BULLET_SLACK:
        issues.append(Issue("bullets_over", "error", where,
                            f"상위 불릿 {n}개 (지정 {expected}개, 허용 {expected + LINT_BULLET_SLACK}개). 합쳐서 {expected}개로"))
    elif n > expected:
        issues.append(Issue("bullets_over", "warning", where,
                            f"상위 불릿 {n}개 (지정 {expected}개). 가능하면 합쳐서 {expected}개로"))
    elif n < expected:
        issues.append(Issue("bullets_under", "warning", where,
                            f"상위 불릿 {n}개 (지정 {expected}개). 있는 근거 안에서 나누거나 그대로 둠"))


def _check_summary(sec: Node, issues: List[Issue]) -> None:
    text = sec.all_text()
    bullets = all_bullets(text)
    if bullets:
        issues.append(Issue("summary_style", "error", sec.title, "연구 요약은 불릿 없이 산문 1문단. 불릿을 문장으로 풀어 한 문단으로"))
        return
    if sec.children:
        issues.append(Issue("extra_section", "error", sec.title, "연구 요약에는 소제목을 두지 않음"))
    sentences = [s for s in re.split(r"(?<=다\.)\s+|(?<=다\.)$", text.strip()) if s.strip()]
    n = len(re.findall(r"다\.", text))
    if abs(n - SUMMARY_SENTENCES) > 1:
        issues.append(Issue("summary_sentences", "warning", sec.title,
                            f"'~다.' 문장 {n}개 (지정 {SUMMARY_SENTENCES}문장: "
                            "문제 정의 → 기존 한계 → 제안 → 검증 → 기대 결과)"))
    if re.search(r"(함|임|음)\.?\s*$", text.strip(), flags=re.M) and n == 0:
        issues.append(Issue("summary_style", "error", sec.title, "연구 요약이 개조식 종결. '~한다/~이다' 평서문으로"))
    del sentences


def _check_proposal(sub: Node, where: str, issues: List[Issue], report: LintReport) -> None:
    """제안 방법: 개요 불릿 2개 + 모듈 1~3, 각 모듈은 하위 불릿 3개(고정 라벨·순서)."""
    overview_bullets = top_bullets(sub.own_text())
    n_over = count_chars(sub.own_text())
    report.metrics[f"{where} > 개요"] = {"chars": n_over, "target": OVERVIEW_CHARS, "bullets": len(overview_bullets)}
    _check_bullet_count(f"{where} > 개요", len(overview_bullets), OVERVIEW_BULLETS, issues)
    _check_length(f"{where} > 개요", n_over, OVERVIEW_CHARS, issues)

    modules = [c for c in sub.children if c.level == 4]
    for c in sub.children:
        if c.level != 4:
            issues.append(Issue("extra_section", "error", f"{where} > {c.title}", "제안 방법 아래에는 '#### 모듈 N: 이름' 만 둔다"))
    numbers = []
    for m in modules:
        mm = _MODULE_RE.match(m.title)
        if not mm:
            issues.append(Issue("module_structure", "error", f"{where} > {m.title}", "모듈 소제목은 '모듈 N: (모듈명)' 형태"))
            continue
        numbers.append(int(mm.group(1)))
    expected_numbers = list(range(1, MODULE_COUNT + 1))
    if len(modules) != MODULE_COUNT:
        issues.append(Issue("missing_module", "error", where,
                            f"모듈 {len(modules)}개 (지정 {MODULE_COUNT}개: "
                            f"모듈 {' · '.join(map(str, expected_numbers))})"))
    elif numbers != expected_numbers:
        issues.append(Issue("module_structure", "error", where,
                            f"모듈 번호가 {numbers}. {', '.join(map(str, expected_numbers))} 순서로"))

    for m in modules:
        mwhere = f"{where} > {m.title}"
        n_mod = count_chars(m.all_text())
        report.metrics[mwhere] = {"chars": n_mod, "target": MODULE_CHARS}
        _check_length(mwhere, n_mod, MODULE_CHARS, issues)
        leads = [re.sub(r"[:：\s]+$", "", b) for b in top_bullets(m.own_text())]
        if len(leads) != len(MODULE_LABELS) or any(not lead.startswith(lbl) for lead, lbl in zip(leads, MODULE_LABELS)):
            n_labels = len(MODULE_LABELS)
            issues.append(Issue("module_structure", "error", mwhere,
                                f"상위 불릿이 {leads} — 정확히 {n_labels}개 "
                                f"'{' → '.join(MODULE_LABELS)}' 순서여야 함. "
                                f"그 밖의 항목은 삭제하거나 {n_labels}개 항목에 합침"))
        if m.children:
            for c in m.children:
                issues.append(Issue("extra_section", "error", f"{mwhere} > {c.title}", "모듈 아래에 소제목을 두지 않음"))
