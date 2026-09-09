# -*- coding: utf-8 -*-
"""LangGraph 공유 상태 스키마 정의."""
from __future__ import annotations

import operator
from typing import Annotated, List, Optional, TypedDict

from langchain_core.messages import BaseMessage


class ResearchPlanState(TypedDict):
    # 입력
    abstract: str
    user_requests: str

    # 스코핑 단계
    scope_problem: str              # 초록을 재서술한 Problem
    scope_solution: str             # 초록을 재서술한 Solution
    scope_missing: List[str]        # 재서술에서 비어 있던 요소 (질문 후보)
    clarify_round: int              # 지금까지 던진 질문 수 (≤ MAX_CLARIFY_QUESTIONS)
    current_question: Optional[dict]  # 현재 질문 {"question", "examples"[≤3], "diagnosis", "selected_gap", "rationale", "dimension"}
    current_answer: str             # 인터럽트 재개 시 주입되는 사용자 답변
    clarify_qna: str                # 누적 Q&A 텍스트
    revised_abstract_proposal: str  # revise_abstract 노드가 제안한 수정 초록 (인터럽트 전달용)
    research_brief_data: dict       # 구조화 브리프 (scope.nodes.normalize_brief 의 키). 사용자에게 보이지 않는 내부용
    research_brief: str             # 브리프 렌더링 텍스트 ("FIELD: value" 줄) — collector·writer 입력

    # 수집 단계
    collector_a_prompt: str
    collector_b_prompt: str
    collector_c_prompt: str
    background_data: str            # 선별된 출처 카드를 렌더링한 증거 텍스트 (writer/reporter 입력)
    method_data: str
    arxiv_data: str
    background_cards: List[dict]    # 선별된 SourceCard 목록 (dict). 원본 전체는 runtime/<실행>/research/cards_*.json
    method_cards: List[dict]
    arxiv_cards: List[dict]
    is_a_sufficient: bool           # 갭 분석이 '충분' 으로 끝났는지
    is_b_sufficient: bool
    is_c_sufficient: bool
    collector_a_coverage: str       # 갭 분석 요약 한 줄 (covered/partial/missing, 미해결 항목)
    collector_b_coverage: str
    collector_c_coverage: str
    collector_a_search_count: int
    collector_b_search_count: int
    collector_c_search_count: int

    # 작성 단계
    research_plan: str
    lint_writer: str                # 양식 검사 요약 (초안/재작성 뒤). 예: "errors 9 → 2 → 0, warnings 3 (clean)"
    lint_reporter: str              # 양식 검사 요약 (Reporter, 심사 통과본 표기 정리 뒤)
    references_count: int           # 카드에서 생성된 참고문헌 수
    reporter_changes: str           # 심사 통과본 대비 최종본 변경 줄. 예: "2/138 lines (cleanup 2, lint-fix 0, llm calls 0, guard rejects 0)"
    cover_subtitle: str             # PDF 표지 부제 (cover 노드가 연구 요약을 읽고 생성). main.PDF_SUBTITLE 이 비어 있을 때 쓴다
    cover_keywords: List[str]       # PDF 표지 키워드 (브리프 keywords_ko). main.PDF_KEYWORDS 가 비어 있을 때 쓴다

    # 도해 (심사 통과 뒤 1회, finalize/diagram.py)
    framework_figure_path: str
    framework_caption: str          # 조판 단계에서 쓰는 그림 캡션 (한국어 1줄)
    framework_svg_path: str         # Archify 가 추출한 SVG (PNG 와 같은 도해, 보관용)
    diagram_checks: str             # Archify 검증 통과 수 예: "9/9"
    diagram_repair_rounds: int      # Archify 검증 실패 후 LLM 수리 횟수

    # 최종 출력
    research_paper: str

    # 심사 단계
    review_round: int
    review_a_history: Annotated[List[str], operator.add]
    review_b_history: Annotated[List[str], operator.add]
    review_a_passed: bool           # 이번 라운드 Reviewer A(내용) VERDICT — 코드가 파싱
    review_b_passed: bool           # 이번 라운드 Reviewer B(가독성) VERDICT — 코드가 파싱
    editor_feedback: str
    review_passed: bool             # 코드 결정: review_a_passed and review_b_passed
    rewrite_count: int

    # 메시지 누적
    messages: Annotated[List[BaseMessage], operator.add]
