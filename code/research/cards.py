# -*- coding: utf-8 -*-
"""Research 단계의 출처 카드 파이프라인.

수집 결과를 "잘라 붙인 텍스트" 가 아니라 출처 카드(SourceCard) 로 다룬다.

    검색 결과(본문·초록 포함) ──(LLM 1회/쿼리)──> 카드: 요지·종류·연도·관련도(0~5)·범위 판정
        → 중복 제거 → 관련도순 선별(장수·글자 예산) → 렌더링 → writer / reporter
        → 갭 분석(LLM 1회/라운드): 채널 기준별 covered/partial/missing, 빠진 주제, 후속 쿼리

채널: "web"(Tavily, Collector A·B) / "scholar"(Liner+보강 또는 arXiv, Collector C).
학술 카드는 학술지·인용 수·arXiv ID·DOI 와 요지의 근거가 초록인지 스니펫인지를 함께 가진다.

브리프(PROMPT_RESEARCH_BRIEF 의 고정 형식)는 parse_brief 로 항목별로 잘라 쿼리 생성·카드 판정·
갭 분석 프롬프트에 직접 넣는다. 카드 JSON 과 렌더링된 증거는 runtime/<실행>/research/ 에 남긴다.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from core.config import (
    EVIDENCE_CHAR_LIMIT,
    MIN_RELEVANCE,
)
from core.paths import research_dir
from core.llm_json import invoke_json
from core.prompts import PROMPTS

SCHOLAR_CHANNELS = ("scholar", "arxiv")


# ── 브리프 ──────────────────────────────────────────────────────────────────────

BRIEF_FIELDS = ("RESEARCH QUESTION", "PROBLEM", "SOLUTION", "ALIGNMENT", "IN SCOPE", "OUT OF SCOPE",
                "KEY CONCEPTS", "DATA CANDIDATES", "EVALUATION CANDIDATES", "EXISTING APPROACHES",
                "UNRESOLVED REASON", "USER CONSTRAINTS", "ASSUMPTIONS", "UNKNOWNS")
_BRIEF_RE = re.compile(r"^(" + "|".join(re.escape(f) for f in BRIEF_FIELDS) + r")\s*:\s*(.*)$", re.MULTILINE)
_EMPTY_VALUES = {"", "(없음)", "없음", "(none)", "none", "n/a"}


def parse_brief(brief: str) -> Dict[str, str]:
    """브리프의 고정 형식을 {필드: 값} 으로. 형식이 깨졌으면 전문을 RESEARCH QUESTION 에 둔다."""
    out = {k: "" for k in BRIEF_FIELDS}
    text = (brief or "").strip()
    if not text:
        return out
    matches = list(_BRIEF_RE.finditer(text))
    if not matches:
        out["RESEARCH QUESTION"] = text
        return out
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = m.group(2) + text[m.end():end]
        out[m.group(1)] = " ".join(value.split())
    return out


def brief_section(brief: str) -> str:
    """쿼리 생성·카드 판정·갭 분석 프롬프트에 넣는 브리프 블록."""
    f = parse_brief(brief)

    def has(key: str) -> bool:
        return f.get(key, "").strip().lower() not in _EMPTY_VALUES

    lines = [
        f"RESEARCH QUESTION: {f['RESEARCH QUESTION'] or '(not provided)'}",
        f"IN SCOPE: {f['IN SCOPE'] or '(not provided)'}",
        f"OUT OF SCOPE: {f['OUT OF SCOPE'] if has('OUT OF SCOPE') else '(none)'}",
        f"KEY CONCEPTS: {f['KEY CONCEPTS'] or '(not provided)'}",
    ]
    # 스코핑에서 연구자가 밝힌 데이터·평가·기존 접근·미해결 이유는 수집 방향의 직접 힌트가 된다
    for key in ("DATA CANDIDATES", "EVALUATION CANDIDATES", "EXISTING APPROACHES", "UNRESOLVED REASON"):
        if has(key):
            lines.append(f"{key}: {f[key]}")
    if has("USER CONSTRAINTS"):
        lines.append(f"USER CONSTRAINTS: {f['USER CONSTRAINTS']}")
    return "\n".join(lines)


# ── 카드 ────────────────────────────────────────────────────────────────────────

@dataclass
class SourceCard:
    id: str                 # "A-03" (collector 문자 + 순번)
    channel: str            # "web" | "scholar" | "arxiv"
    title: str
    url: str
    year: str = ""
    kind: str = ""          # 논문·기술문서·보고서·기사·블로그·공식문서·기타 (학술 채널은 "논문")
    authors: str = ""       # 학술
    arxiv_id: str = ""      # 학술 (버전 제거)
    doi: str = ""           # 학술
    journal: str = ""       # 학술: 학술지·학회명
    citation_count: Optional[int] = None   # 학술: 인용 수 (Liner/OpenAlex/S2)
    approach: str = ""      # 학술: 접근 계열 한 구절
    abstract_source: str = ""  # 학술: 요지의 근거 — arxiv | openalex | semanticscholar | snippet | none
    summary: str = ""       # 브리프 기준 요지 (한국어, 고유명사 원문 유지)
    relevance: int = 0      # 0~5
    in_scope: bool = True
    scope_note: str = ""
    query: str = ""         # 이 카드를 찾은 검색 쿼리
    round: int = 0
    excerpt: str = ""       # 원문 발췌 (파일 저장용, 프롬프트에는 넣지 않음)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SourceCard":
        defaults = asdict(cls("", "", "", ""))
        return cls(**{k: d.get(k, v) for k, v in defaults.items()})


def _clamp_int(value: Any, lo: int, hi: int, default: int = 0) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _year_of(*candidates: Any) -> str:
    for c in candidates:
        m = re.search(r"(19|20)\d{2}", str(c or ""))
        if m:
            return m.group(0)
    return ""


def _render_results_for_llm(results: List[Dict[str, Any]], channel: str) -> str:
    blocks = []
    for i, r in enumerate(results, start=1):
        if channel in SCHOLAR_CHANNELS:
            ids = " ".join(x for x in (
                f"arXiv:{r['arxiv_id']}" if r.get("arxiv_id") else "",
                f"DOI:{r['doi']}" if r.get("doi") else "",
            ) if x) or "-"
            cites = r.get("citation_count")
            src = r.get("abstract_source") or ("arxiv" if r.get("abstract") else "none")
            if src in ("snippet", "none"):
                text_line = f"    snippet only (no abstract available): {r.get('abstract') or r.get('snippet') or '(none)'}"
            else:
                text_line = f"    abstract (source: {src}): {r.get('abstract', '')}"
            blocks.append(
                f"[{i}] title: {r.get('title', '')}\n"
                f"    authors: {r.get('authors', '') or 'unknown'} | year: {r.get('year', '') or 'unknown'}"
                f" | venue: {r.get('journal', '') or 'unknown'}"
                f" | citations: {cites if cites is not None else 'unknown'}\n"
                f"    ids: {ids} | url: {r.get('url', '')}\n"
                + text_line
            )
        else:
            blocks.append(
                f"[{i}] title: {r.get('title', '')}\n"
                f"    url: {r.get('url', '')}\n"
                f"    date: {r.get('published_date', '') or 'unknown'}\n"
                f"    content: {r.get('content', '')}"
            )
    return "\n\n".join(blocks)


def _card_from_result(r: Dict[str, Any], *, card_id: str, channel: str, query: str, round_no: int,
                      summary: str, relevance: int, in_scope: bool, scope_note: str,
                      kind: str, year: str, approach: str) -> SourceCard:
    text = r.get("abstract") or r.get("content") or r.get("snippet") or ""
    scholar = channel in SCHOLAR_CHANNELS
    return SourceCard(
        id=card_id,
        channel=channel,
        title=" ".join(str(r.get("title") or r.get("url") or "").split()),
        url=r.get("url", ""),
        year=year,
        kind="논문" if scholar else kind,
        authors=r.get("authors", "") if scholar else "",
        arxiv_id=r.get("arxiv_id", "") if scholar else "",
        doi=r.get("doi", "") if scholar else "",
        journal=r.get("journal", "") if scholar else "",
        citation_count=_int_or_none(r.get("citation_count")) if scholar else None,
        approach=approach if scholar else "",
        abstract_source=(r.get("abstract_source") or ("arxiv" if r.get("abstract") else "")) if scholar else "",
        summary=summary,
        relevance=relevance,
        in_scope=in_scope,
        scope_note=scope_note,
        query=query,
        round=round_no,
        excerpt=" ".join(str(text).split())[:600],
    )


def _fallback_cards(results, *, channel, side, query, round_no, id_start, note) -> List[SourceCard]:
    """LLM 카드화가 실패했을 때 원문 발췌로 카드를 만들어 라운드를 살린다. 관련도는 최소 통과값."""
    cards = []
    for r in results:
        text = r.get("abstract") or r.get("content") or r.get("snippet") or ""
        if not text.strip():
            continue
        cards.append(_card_from_result(
            r, card_id=f"{side}-{id_start + len(cards):02d}", channel=channel, query=query, round_no=round_no,
            summary=" ".join(text.split())[:500], relevance=MIN_RELEVANCE, in_scope=True, scope_note=note,
            kind="기타", year=_year_of(r.get("year"), r.get("published_date")), approach="",
        ))
    return cards


def make_cards(
    results: List[Dict[str, Any]],
    *,
    channel: str,
    side: str,
    purpose: str,
    brief: str,
    query: str,
    round_no: int,
    id_start: int,
) -> List[SourceCard]:
    """검색 결과 묶음 → LLM 1회 → 카드 목록. LLM 이 버린 결과(내용 없음·무관)는 카드가 되지 않는다."""
    if not results:
        return []
    prompt_id = "PROMPT_CARDS_SCHOLAR" if channel in SCHOLAR_CHANNELS else "PROMPT_CARDS_WEB"
    prompt = PROMPTS[prompt_id].format(
        purpose=purpose,
        brief_section=brief_section(brief),
        query=query,
        results=_render_results_for_llm(results, channel),
    )
    try:
        data = invoke_json(prompt)
        items = data.get("cards")
        if not isinstance(items, list):
            raise ValueError("'cards' 배열이 없음")
    except Exception as exc:  # noqa: BLE001 - 한 쿼리의 LLM 실패로 라운드를 죽이지 않는다
        print(f"    [cards] LLM 카드화 실패 → 원문 발췌로 대체 ({type(exc).__name__}: {str(exc)[:80]})")
        return _fallback_cards(results, channel=channel, side=side, query=query, round_no=round_no,
                               id_start=id_start, note="LLM 카드화 실패, 원문 발췌")

    by_index: Dict[int, Dict[str, Any]] = {}
    for it in items:
        if isinstance(it, dict):
            idx = _clamp_int(it.get("index"), 1, len(results), default=0)
            if idx:
                by_index.setdefault(idx, it)

    cards: List[SourceCard] = []
    for i, r in enumerate(results, start=1):
        it = by_index.get(i)
        if it is None:
            continue
        summary = " ".join(str(it.get("summary") or "").split())
        if not summary:
            continue
        cards.append(_card_from_result(
            r, card_id=f"{side}-{id_start + len(cards):02d}", channel=channel, query=query, round_no=round_no,
            summary=summary,
            relevance=_clamp_int(it.get("relevance"), 0, 5),
            in_scope=bool(it.get("in_scope", True)),
            scope_note=" ".join(str(it.get("scope_note") or "").split()),
            kind=" ".join(str(it.get("kind") or "기타").split()),
            year=_year_of(it.get("year"), r.get("year"), r.get("published_date")),
            approach=" ".join(str(it.get("approach") or "").split()),
        ))
    return cards


# ── 중복 제거 · 선별 · 렌더링 ────────────────────────────────────────────────────

_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "ref=")


def _dedup_key(card: SourceCard) -> str:
    if card.arxiv_id:
        return f"arxiv:{card.arxiv_id.lower()}"
    if card.doi:
        return f"doi:{card.doi.lower()}"
    if card.url:
        try:
            parts = urlsplit(card.url.strip())
            query = "&".join(p for p in parts.query.split("&") if p and not p.startswith(_TRACKING_PARAMS))
            return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))
        except ValueError:
            return card.url.strip().lower()
    return "title:" + " ".join(sorted(t for t in re.findall(r"[a-z0-9]+", card.title.lower()) if len(t) > 2))


def dedup_cards(cards: List[SourceCard]) -> List[SourceCard]:
    """같은 출처(arXiv id, DOI, 정규화 URL)는 관련도가 높은 카드 하나만 남긴다. 순서는 유지."""
    best: Dict[str, SourceCard] = {}
    order: List[str] = []
    for c in cards:
        k = _dedup_key(c) or c.id
        if k not in best:
            best[k] = c
            order.append(k)
        elif c.relevance > best[k].relevance:
            best[k] = c
    return [best[k] for k in order]


def render_card(c: SourceCard) -> str:
    if c.channel in SCHOLAR_CHANNELS:
        who = ", ".join(x for x in (c.authors, c.year) if x)
        head = f"[{c.id}] {c.title}" + (f" ({who})" if who else "")
        tail = [c.journal or ("arXiv 프리프린트" if c.arxiv_id else "논문")]
        if c.citation_count is not None:
            tail.append(f"인용 {c.citation_count}")
        if c.arxiv_id:
            tail.append(f"arXiv:{c.arxiv_id}")
        elif c.doi:
            tail.append(f"DOI:{c.doi}")
        tail.append(f"관련도 {c.relevance}/5")
        if c.approach:
            tail.append(f"접근: {c.approach}")
        if c.abstract_source == "snippet":
            tail.append("근거: 검색 스니펫")
    else:
        head = f"[{c.id}] {c.title}" + (f" ({c.year})" if c.year else "")
        tail = [c.kind or "웹", f"관련도 {c.relevance}/5"]
    return f"{head}\n{' · '.join(tail)}\nURL: {c.url}\n요지: {c.summary}"


def select_cards(
    cards: List[SourceCard],
    *,
    top_n: int,
    char_limit: int = EVIDENCE_CHAR_LIMIT,
    min_relevance: int = MIN_RELEVANCE,
) -> List[SourceCard]:
    """범위 안이고 관련도가 기준 이상인 카드를 관련도 → 인용 수 → 최신순으로 골라 장수와 글자 예산 안에서 반환."""
    kept = [c for c in cards if c.in_scope and c.relevance >= min_relevance and c.summary]
    kept.sort(key=lambda c: (-c.relevance, -(c.citation_count or 0), -int(c.year or 0)))
    out: List[SourceCard] = []
    used = 0
    for c in kept:
        block_len = len(render_card(c)) + 2
        if len(out) >= top_n or used + block_len > char_limit:
            break
        out.append(c)
        used += block_len
    return out


def render_evidence(cards: List[SourceCard], label: str) -> str:
    """writer/reporter 프롬프트에 들어가는 채널별 증거 블록."""
    if not cards:
        return f"({label}: 선별된 출처 없음)"
    header = f"({label}: 출처 카드 {len(cards)}장, 관련도순)"
    return header + "\n\n" + "\n\n".join(render_card(c) for c in cards)


# ── 갭 분석 ─────────────────────────────────────────────────────────────────────

def _cards_digest(cards: List[SourceCard]) -> str:
    if not cards:
        return "(no cards yet)"
    lines = []
    for c in cards:
        tag = c.approach or c.kind or c.channel
        extra = ""
        if c.channel in SCHOLAR_CHANNELS:
            bits = [c.journal] if c.journal else []
            if c.citation_count is not None:
                bits.append(f"cites {c.citation_count}")
            if c.abstract_source == "snippet":
                bits.append("snippet only")
            extra = (" · " + " · ".join(bits)) if bits else ""
        lines.append(f"[{c.id}] {c.title} ({c.year or 'n.d.'}) · relevance {c.relevance} · {tag}{extra}\n"
                     f"    {c.summary[:240]}")
    return "\n".join(lines)


def gap_analysis(
    cards: List[SourceCard],
    *,
    eval_prompt_id: str,
    brief: str,
    abstract: str,
    round_no: int,
    max_rounds: int,
) -> Dict[str, Any]:
    """선별된 카드가 채널 기준을 얼마나 채우는지 LLM 이 판정. 실패하면 '불충분, 갭 미상' 으로 돌려준다."""
    prompt = PROMPTS[eval_prompt_id].format(
        abstract=abstract,
        brief_section=brief_section(brief),
        cards_digest=_cards_digest(cards),
        count=round_no,
        max_count=max_rounds,
    )
    try:
        data = invoke_json(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"    [gap] 갭 분석 LLM 실패 ({type(exc).__name__}: {str(exc)[:80]}) → 불충분으로 간주")
        return {"coverage": [], "missing_topics": [], "followup_queries": [],
                "sufficient": False, "error": str(exc)[:200]}

    coverage = [c for c in (data.get("coverage") or []) if isinstance(c, dict)]
    for c in coverage:
        c["status"] = str(c.get("status") or "").strip().lower()
        if c["status"] not in ("covered", "partial", "missing"):
            c["status"] = "partial"
    missing_topics = [" ".join(str(x).split()) for x in (data.get("missing_topics") or []) if str(x).strip()]
    followup = [" ".join(str(x).split()) for x in (data.get("followup_queries") or []) if str(x).strip()]
    sufficient = bool(data.get("sufficient", False))
    # 규칙 보정: missing 이 하나라도 있으면 불충분, partial 이 둘 이상이면 불충분
    statuses = [c["status"] for c in coverage]
    if statuses.count("missing") >= 1 or statuses.count("partial") >= 2:
        sufficient = False
    return {"coverage": coverage, "missing_topics": missing_topics,
            "followup_queries": followup[:4], "sufficient": sufficient}


def gap_section(gap: Optional[Dict[str, Any]]) -> str:
    """다음 라운드 쿼리 생성 프롬프트에 넣는 블록. 첫 라운드(gap 없음)는 빈 문자열."""
    if not gap:
        return ""
    lines = ["\n[Gap analysis of the previous round — generate queries that fill these first]"]
    for c in gap.get("coverage", []):
        if c.get("status") in ("missing", "partial"):
            note = f" — {c.get('note')}" if c.get("note") else ""
            lines.append(f"- {c.get('criterion')}: {c.get('status').upper()}{note}")
    if gap.get("missing_topics"):
        lines.append("Missing topics: " + "; ".join(gap["missing_topics"]))
    if gap.get("followup_queries"):
        lines.append("Suggested queries: " + " | ".join(gap["followup_queries"]))
    if gap.get("error"):
        lines.append("(previous gap analysis failed; cover the criteria broadly)")
    return "\n".join(lines) + "\n"


def coverage_summary(gap: Optional[Dict[str, Any]]) -> str:
    """프론트매터·Run Summary 용 한 줄."""
    if not gap:
        return ""
    statuses = [c.get("status", "") for c in gap.get("coverage", [])]
    if not statuses:
        return "gap analysis unavailable" if gap.get("error") else "no coverage data"
    parts = [f"covered {statuses.count('covered')} / partial {statuses.count('partial')} / missing {statuses.count('missing')}"]
    open_items = [f"{c.get('criterion')}({c.get('status')})" for c in gap.get("coverage", [])
                  if c.get("status") in ("partial", "missing")]
    if open_items:
        parts.append("미해결: " + ", ".join(open_items))
    return " — ".join(parts)


# ── 저장 ────────────────────────────────────────────────────────────────────────

def save_research_artifacts(
    side: str,
    *,
    all_cards: List[SourceCard],
    selected: List[SourceCard],
    gap: Optional[Dict[str, Any]],
    evidence: str,
    queries_by_round: Dict[int, List[str]],
) -> Dict[str, str]:
    """카드 전체(JSON)와 writer 에게 넘긴 증거(마크다운)를 이번 실행의 research/ 에 남긴다."""
    out_dir = research_dir()
    payload = {
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "collector": side,
        "queries_by_round": {str(k): v for k, v in queries_by_round.items()},
        "selected_ids": [c.id for c in selected],
        "gap": gap,
        "cards": [c.to_dict() for c in all_cards],
    }
    json_path = out_dir / f"cards_{side}.json"
    md_path = out_dir / f"evidence_{side}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(evidence + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}
