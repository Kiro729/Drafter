# -*- coding: utf-8 -*-
"""표지 메타 노드: 최종본의 연구 요약을 읽고 부제 한 문장을 만들고(LLM 1회), 브리프의 표지 키워드를 붙인다.

reporter 뒤에 실행된다. 본문은 건드리지 않는다. 결과는 state 의 cover_subtitle · cover_keywords 로 올라가
마크다운 프론트매터에 subtitle · keywords 로 저장되고, 조판(finalize/export_pdf.py)이 main.py 의
PDF_SUBTITLE · PDF_KEYWORDS 가 비어 있을 때 이 값을 쓴다. LLM 이 실패하면 연구 요약 첫 문장을 부제로 쓴다.
키워드는 Scope 단계 브리프의 keywords_ko (LLM 이 브리프를 만들 때 함께 낸 한국어 핵심어) 에서 가져오므로 추가 호출이 없다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from langchain_core.messages import AIMessage

from core.llm_json import invoke_json
from core.prompts import PROMPTS
from core.state import ResearchPlanState

_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_SUMMARY_RE = re.compile(r"^##\s*(?:연구\s*요약|요약|초록)\s*$\n+(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)
MAX_KEYWORDS = 6


def extract_title(paper: str) -> str:
    m = _TITLE_RE.search(paper or "")
    return m.group(1).strip() if m else ""


def extract_summary(paper: str) -> str:
    """'## 연구 요약' 절 본문 (다음 ## 앞까지) 을 한 줄로."""
    m = _SUMMARY_RE.search(paper or "")
    return " ".join(m.group(1).split()) if m else ""


def first_sentence(text: str) -> str:
    text = " ".join((text or "").split())
    return re.split(r"(?<=다\.)\s", text, maxsplit=1)[0].strip() if text else ""


def generate_subtitle(paper: str) -> str:
    """연구 요약을 읽고 부제 한 문장. 요약이 없으면 빈 문자열, LLM 실패면 요약 첫 문장."""
    summary = extract_summary(paper)
    if not summary:
        return ""
    try:
        data = invoke_json(PROMPTS["PROMPT_COVER_SUBTITLE"].format(title=extract_title(paper) or "(없음)", summary=summary))
        subtitle = " ".join(str(data.get("subtitle") or "").split())
    except Exception as exc:  # noqa: BLE001 - 부제는 표지 장식이므로 실패해도 파이프라인을 세우지 않는다
        print(f"  [Cover] 부제 생성 실패 ({type(exc).__name__}) → 연구 요약 첫 문장으로 대체")
        subtitle = ""
    return subtitle or first_sentence(summary)


def brief_keywords(brief_data: Dict[str, Any]) -> List[str]:
    keywords = [" ".join(str(k).split()) for k in (brief_data or {}).get("keywords_ko") or []]
    return [k for k in keywords if k][:MAX_KEYWORDS]


def cover(state: ResearchPlanState) -> ResearchPlanState:
    print("[Cover] 표지 부제·키워드 준비 중...")
    paper = state.get("research_paper") or state.get("research_plan") or ""
    subtitle = generate_subtitle(paper)
    keywords = brief_keywords(state.get("research_brief_data") or {})
    if not keywords:
        print("  [Cover] 브리프에 표지 키워드가 없음 — PDF 표지의 키워드 줄은 비워 둠")
    print(f"  [Cover] 부제: {subtitle or '(없음)'}")
    print(f"  [Cover] 키워드: {', '.join(keywords) or '(없음)'}")
    return {
        "cover_subtitle": subtitle,
        "cover_keywords": keywords,
        "messages": [AIMessage(content=subtitle, name="cover")],
    }
