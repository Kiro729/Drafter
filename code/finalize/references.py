# -*- coding: utf-8 -*-
"""참고문헌을 학술 카드에서 결정론적으로 생성한다.

본문의 [Author et al., Year] 를 뽑아 arxiv_cards(research.SourceCard dict) 와 제1저자 성·연도로 대조하고,
등장 순서대로 참고문헌 항목을 조립한다. LLM 이 서지 정보를 쓰지 않으므로 실재하지 않는 논문이나
틀린 연도·제목이 참고문헌에 들어갈 수 없고, 본문 인용과 목록이 정확히 일대일이 된다.

항목 형식 (조판기 build.py 의 인용 배지 링크 규칙에 맞춘다: 첫 토큰 = 제1저자 성, "(YYYY)" 포함):
    - Vaswani A, Shazeer N, Parmar N 외 (2017). Attention Is All You Need. NeurIPS 2017. arXiv:1706.03762. https://arxiv.org/abs/1706.03762v7
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from write.lint import CITE_RE, REFERENCE_KEYS, find_card

_REF_HEADING_RE = re.compile(r"^##\s+(?:\d+\.\s*)?(?:%s)\s*$" % "|".join(REFERENCE_KEYS), re.M)
_NEXT_H2_RE = re.compile(r"^##\s", re.M)


def strip_references_section(text: str) -> str:
    """'## 참고문헌' 섹션(다음 ## 또는 문서 끝까지)을 제거한다."""
    m = _REF_HEADING_RE.search(text)
    if not m:
        return text.rstrip() + "\n"
    nxt = _NEXT_H2_RE.search(text, m.end())
    end = nxt.start() if nxt else len(text)
    return (text[:m.start()].rstrip() + "\n" + text[end:]).rstrip() + "\n"


def extract_citations(text: str) -> List[Tuple[str, str]]:
    """본문(참고문헌 제외)의 인용 키 (성, 연도) 를 등장 순서대로, 중복 없이."""
    body = strip_references_section(text)
    seen: List[Tuple[str, str]] = []
    for m in CITE_RE.finditer(body):
        key = (m.group(1), m.group(2))
        if all(k[0].lower() != key[0].lower() or k[1] != key[1] for k in seen):
            seen.append(key)
    return seen


def _format_person(name: str) -> str:
    """'Ashish Vaswani' → 'Vaswani A', 'Reza Jafari Ziarani' → 'Ziarani RJ', 'Kim' → 'Kim'."""
    parts = [p for p in re.split(r"\s+", name.strip().strip(",")) if p]
    if len(parts) <= 1:
        return name.strip()
    surname = parts[-1]
    initials = "".join(p[0].upper() for p in parts[:-1] if p[0].isalpha())
    return f"{surname} {initials}".strip()


def format_authors(authors: str, cite_surname: Optional[str] = None) -> str:
    """카드의 저자 문자열을 '성 이니셜, 성 이니셜 외' 로. 인용된 성이 있으면 그 저자를 맨 앞에 둔다."""
    raw = (authors or "").strip()
    has_more = bool(re.search(r"\s외$", raw))
    raw = re.sub(r"\s외$", "", raw)
    names = [n.strip() for n in re.split(r",|;| and ", raw) if n.strip()]
    if not names:
        return "저자 미상"
    if cite_surname:
        for i, n in enumerate(names):
            if cite_surname.lower() in [t.lower() for t in re.split(r"[\s\-]+", n)]:
                names.insert(0, names.pop(i))
                break
    formatted = ", ".join(_format_person(n) for n in names[:3])
    if has_more or len(names) > 3:
        formatted += " 외"
    return formatted


def format_reference(card: Dict[str, Any], cite_surname: Optional[str] = None) -> str:
    authors = format_authors(str(card.get("authors") or ""), cite_surname)
    year = str(card.get("year") or "n.d.")
    title = " ".join(str(card.get("title") or "").split()).rstrip(".")
    parts = [f"{authors} ({year}). {title}."]
    venue = str(card.get("journal") or "").strip()
    if venue:
        parts.append(f"{venue}.")
    elif card.get("arxiv_id"):
        parts.append("arXiv preprint.")
    if card.get("arxiv_id"):
        parts.append(f"arXiv:{card['arxiv_id']}.")
    elif card.get("doi"):
        parts.append(f"DOI:{card['doi']}.")
    if card.get("url"):
        parts.append(str(card["url"]))
    return "- " + " ".join(parts)


def build_references(
    text: str,
    cards: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]], List[Tuple[str, str]]]:
    """(참고문헌 마크다운 섹션, 매칭된 카드 목록(등장 순), 매칭 실패 인용 키) 를 돌려준다."""
    matched: List[Dict[str, Any]] = []
    unmatched: List[Tuple[str, str]] = []
    lines: List[str] = []
    seen_ids: set = set()
    for surname, year in extract_citations(text):
        card = find_card(surname, year, cards)
        if card is None:
            unmatched.append((surname, year))
            continue
        cid = card.get("id") or card.get("url") or card.get("title")
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        matched.append(card)
        lines.append(format_reference(card, surname))
    if lines:
        section = "## 참고문헌\n\n" + "\n".join(lines) + "\n"
    else:
        section = "## 참고문헌\n\n- (본문에 인용된 학술 논문 없음)\n"
    return section, matched, unmatched


def remove_citations(text: str, keys: List[Tuple[str, str]]) -> str:
    """지정한 (성, 연도) 인용 표기만 제거한다. 문장은 그대로 둔다."""
    for surname, year in keys:
        pat = re.compile(r"\s*\[" + re.escape(surname) + r"(?:\s+et\s+al\.)?,?\s*" + re.escape(year) + r"\]")
        text = pat.sub("", text)
    return text


def attach_references(text: str, cards: List[Dict[str, Any]], *, drop_unmatched: bool = True) -> Tuple[str, Dict[str, Any]]:
    """본문 끝의 참고문헌을 카드 기반으로 교체한다. 카드에 없는 인용은(옵션) 표기만 떼어 목록과 1:1 을 맞춘다."""
    section, matched, unmatched = build_references(text, cards)
    body = strip_references_section(text)
    if unmatched and drop_unmatched:
        body = remove_citations(body, unmatched)
    final = body.rstrip() + "\n\n" + section
    info = {
        "references": len(matched),
        "unmatched_citations": [f"{s} et al., {y}" for s, y in unmatched],
        "dropped": bool(unmatched and drop_unmatched),
    }
    return final, info
