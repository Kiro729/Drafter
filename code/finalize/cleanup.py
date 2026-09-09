# -*- coding: utf-8 -*-
"""심사 통과본의 표기 정리 (결정론적, LLM 없음).

Reporter 가 LLM 으로 문서 전체를 다시 쓰며 하던 일 중 규칙이 명확한 것만 코드가 처리한다.
문장은 건드리지 않고 표기만 뗀다. 애매한 경우(문장 속 그림 언급, 연도 없는 인용 등)는 그대로 두어
양식 검사기(write.lint)가 지목하고 LLM 이 그 자리만 고치게 한다.

  · 그림      독립 '[그림 N]' 불릿, '그림 N.' 캡션 줄, 이미지 삽입 문법(![..](..)) 줄을 삭제
  · 인용      연구 필요성 밖의 [Author et al., Year] 표기 삭제, 같은 출처 3회째부터 삭제,
              학술 카드에 없는 인용 삭제 (카드가 있을 때만 판단)
  · 강조      마크다운 강조(**굵게**, *기울임*) 표식 제거
  · 카드 ID   [A-06], [C-03] 같은 수집 카드 ID 표기 삭제 (Writer 가 인용 대신 써 버린 경우)
  · 참고문헌  '## 참고문헌' 섹션 삭제 (finalize.references.attach_references 가 카드에서 다시 만든다)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from finalize.references import strip_references_section
from write.lint import (
    CITATION_ALLOWED_IN,
    CITE_NOYEAR_RE,
    CITE_RE,
    MAX_SAME_CITATION,
    _BOLD_RE,
    _HEADING_RE,
    _norm_key,
    find_card,
)
from write.lint_loop import count_changed_lines

# 줄 머리의 그림 표기. 뒤에 남는 텍스트가 문장(~함/~임/~음/~다)이면 캡션이 아니므로 지우지 않는다.
_FIGURE_HEAD_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:\[그림\s*\d+\]|그림\s*\d+\s*[.:])\s*")
_IMAGE_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?!\[[^\]]*\]\([^)]*\)\s*$")
_SENTENCE_END_RE = re.compile(r"(함|임|음|다)\.?\s*$")
# 인용 표기와 그 앞 공백을 함께 지워 "함 [Ali et al., 2023]." → "함." 이 되게 한다.
_CITE_WS_RE = re.compile(r"\s*" + CITE_RE.pattern)
_CITE_NOYEAR_WS_RE = re.compile(r"\s*" + CITE_NOYEAR_RE.pattern)
_CARD_ID_RE = re.compile(r"\s*\[(?:[ABC]-\d{2})(?:\s*,\s*[ABC]-\d{2})*\]")


@dataclass
class CleanupReport:
    figure_lines: int = 0
    citations_outside: int = 0
    citations_repeat: int = 0
    citations_unknown: int = 0
    card_ids: int = 0
    emphasis: int = 0
    references_section: bool = False
    changed_lines: int = 0          # 참고문헌 섹션을 뺀 본문 기준
    total_lines: int = 0

    def summary(self) -> str:
        parts = []
        if self.figure_lines:
            parts.append(f"그림 줄 {self.figure_lines}")
        if self.citations_outside:
            parts.append(f"허용 위치 밖 인용 {self.citations_outside}")
        if self.citations_repeat:
            parts.append(f"반복 인용 {self.citations_repeat}")
        if self.citations_unknown:
            parts.append(f"카드에 없는 인용 {self.citations_unknown}")
        if self.card_ids:
            parts.append(f"카드 ID 인용 {self.card_ids}")
        if self.emphasis:
            parts.append(f"강조 표식 {self.emphasis}")
        if self.references_section:
            parts.append("참고문헌 섹션 제거")
        body = ", ".join(parts) if parts else "정리할 표기 없음"
        return f"{body} (변경 {self.changed_lines}/{self.total_lines}줄)"


def _is_figure_line(line: str) -> bool:
    if _IMAGE_LINE_RE.match(line):
        return True
    m = _FIGURE_HEAD_RE.match(line)
    if not m:
        return False
    rest = line[m.end():].strip()
    return not _SENTENCE_END_RE.search(rest)          # 캡션(명사구)이면 삭제, 문장이면 검사기에 맡긴다


def mechanical_cleanup(text: str, cards: List[Dict[str, Any]]) -> Tuple[str, CleanupReport]:
    """(정리된 본문, 보고). 본문 끝 참고문헌 섹션은 제거된 상태로 돌려준다."""
    rep = CleanupReport()
    body = strip_references_section(text)
    rep.references_section = body.strip() != text.strip()

    counts: Dict[Tuple[str, str], int] = {}
    sub_key = None
    out: List[str] = []

    def drop_citation(m: "re.Match[str]", allowed: bool) -> str:
        surname, year = m.group(1), m.group(2)
        if not allowed:
            rep.citations_outside += 1
            return ""
        if cards and find_card(surname, year, cards) is None:
            rep.citations_unknown += 1
            return ""
        key = (surname.lower(), year)
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > MAX_SAME_CITATION:
            rep.citations_repeat += 1
            return ""
        return m.group(0)

    for line in body.splitlines():
        h = _HEADING_RE.match(line)
        if h:
            level = len(h.group(1))
            if level == 2:
                sub_key = None
            elif level == 3:
                sub_key = _norm_key(h.group(2))
            out.append(line)
            continue
        if _is_figure_line(line):
            rep.figure_lines += 1
            continue
        allowed = sub_key in CITATION_ALLOWED_IN
        new = _CITE_WS_RE.sub(lambda m: drop_citation(m, allowed), line)
        if not allowed:
            new, n = _CITE_NOYEAR_WS_RE.subn("", new)
            rep.citations_outside += n
        new, n = _CARD_ID_RE.subn("", new)
        rep.card_ids += n
        new, n = _BOLD_RE.subn(lambda m: m.group(0).strip("*"), new)
        rep.emphasis += n
        out.append(new.rstrip() if new != line else line)

    cleaned = "\n".join(out).rstrip() + "\n"
    rep.changed_lines, rep.total_lines = count_changed_lines(body, cleaned)
    return cleaned, rep
