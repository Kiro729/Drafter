# -*- coding: utf-8 -*-
"""Writer 노드: 브리프와 증거 카드로 초안을 쓰고(재작성이면 Editor 피드백 반영), 코드 양식 검사·수정 루프를 거친다."""
from __future__ import annotations

from langchain_core.messages import AIMessage

from core import clients
from core.prompts import PROMPTS
from core.state import ResearchPlanState
from write.lint_loop import lint_fix_loop


def writer(state: ResearchPlanState) -> ResearchPlanState:
    rewrite_count = state.get("rewrite_count", 0)
    review_round = state.get("review_round", 0)
    is_rewrite = rewrite_count > 0
    print(f"[Writer] 연구계획서 {'수정' if is_rewrite else '초안'} 작성 중..."
          f" (라운드 {review_round}, 재작성 {rewrite_count}회)")

    common = dict(
        abstract=state["abstract"],
        user_requests=state["user_requests"] or "없음",
        research_brief=state.get("research_brief") or "없음",
        background_data=state["background_data"],
        method_data=state["method_data"],
        arxiv_data=state["arxiv_data"],
    )
    if is_rewrite:
        prompt = PROMPTS["PROMPT_WRITER_REVIEW"].format(
            research_plan=state["research_plan"], editor_feedback=state["editor_feedback"], round=review_round, **common)
    else:
        prompt = PROMPTS["PROMPT_WRITER"].format(**common)
    response = clients.llm.invoke(prompt)

    # 양식 검사(코드) → 위반만 고치는 LLM 호출 → 재검사. 인용 실재 여부는 학술 카드와 대조한다.
    plan, lint_summary, _ = lint_fix_loop(response.content, state.get("arxiv_cards") or [], label="writer")

    print("  작성 완료")
    return {
        "research_plan": plan,
        "lint_writer": lint_summary,
        "messages": [AIMessage(content=plan, name="writer")],
    }
