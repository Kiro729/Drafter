# -*- coding: utf-8 -*-
"""Review 단계: Reviewer A(내용) · Reviewer B(가독성) · Editor 노드. 통과 여부는 코드가 두 VERDICT 로 결정한다."""
from __future__ import annotations

import re

from core import clients
from core.config import REVIEWER_B_SEARCH
from core.paths import review_dir
from core.prompts import PROMPTS
from research.search import (
    _arxiv_search_block,
    _generate_queries,
    _tavily_search_block,
    build_prev_feedback_section,
)
from core.state import ResearchPlanState

from langchain_core.messages import AIMessage

# 심사 역할 분담 (2026-09-09):
#   Reviewer A — 내용: 근거(검증 검색 포함)·섹션 간 정합성·데이터 구체성·논거
#   Reviewer B — 가독성: 이해 가능성·논리 흐름·불릿 계층·중복·모듈 균질성·설득력·연구 요약·AI 티 나는 표현 (검색 없음)
#   Editor     — 두 피드백을 문서 순서로 정리해 Writer 에게 전달. 통과 여부는 코드가 두 VERDICT 로 결정한다.
#   형식·분량·표기·인용 형식은 lint(proposal_lint) 가 맡으므로 심사 대상이 아니다.

_VERDICT_RE = re.compile(r"^\s*VERDICT:\s*(PASS|REVISE)\b", re.MULTILINE | re.IGNORECASE)


def parse_verdict(text: str) -> bool:
    """리뷰어 답변의 'VERDICT: PASS|REVISE' 줄을 읽는다. FINAL_VERDICT 줄은 해당하지 않는다. 없거나 REVISE 면 False."""
    m = _VERDICT_RE.search(text or "")
    return bool(m) and m.group(1).upper() == "PASS"


def _verification_search_section(side: str, research_plan: str) -> str:
    """계획서에서 검증할 주장을 뽑아 Tavily·arXiv 를 검색하고 프롬프트에 덧붙일 블록을 만든다 (Reviewer A)."""
    queries = _generate_queries(PROMPTS["PROMPT_EXTRACT_CLAIMS"], research_plan=research_plan)
    print(f"\n  [Reviewer {side}] 검증 쿼리:")
    for i, q in enumerate(queries):
        print(f"    {i + 1}. {q}")

    tavily_blocks, arxiv_blocks = [], []
    for q in queries:
        try:
            tavily_blocks.append(_tavily_search_block(q))
        except Exception as exc:  # noqa: BLE001 - 검색 실패는 블록에 남기고 계속
            tavily_blocks.append(f"쿼리: {q}\n검색 실패: {type(exc).__name__}: {str(exc)[:100]}")
        arxiv_blocks.append(_arxiv_search_block(q))          # 내부에서 실패를 문자열로 돌려준다
    tavily_ctx = "\n---\n".join(tavily_blocks) if tavily_blocks else "검색 결과 없음"
    arxiv_ctx = "\n---\n".join(arxiv_blocks) if arxiv_blocks else "검색 결과 없음"
    print(f"\n  [Reviewer {side}] 검색 완료 (Tavily {len(tavily_blocks)}, arXiv {len(arxiv_blocks)})")
    return f"\n\n[Tavily 웹검색 결과]\n{tavily_ctx}\n\n[arXiv 학술 검색 결과]\n{arxiv_ctx}"


def _run_reviewer(
    state: ResearchPlanState,
    *,
    side: str,
    role: str,
    history_key: str,
    passed_key: str,
    review_prompt_id: str,
    msg_name: str,
    increment_round: bool,
    reviewer_label: str,
    with_search: bool,
) -> ResearchPlanState:
    """Reviewer 공통 실행 로직 (A/B 모두 이 함수를 호출). VERDICT 는 코드가 파싱해 state 에 남긴다."""
    round_num = state.get("review_round", 0) + (1 if increment_round else 0)
    print(f"[Reviewer {side}] {role} 심사 시작... (라운드 {round_num}"
          f"{', 검증 검색 포함' if with_search else ', 검색 없음'})")

    search_section = _verification_search_section(side, state["research_plan"]) if with_search else ""
    prev_section = build_prev_feedback_section(state.get(history_key, []), reviewer_label)

    final_prompt = PROMPTS[review_prompt_id].format(
        abstract=state["abstract"],
        research_plan=state["research_plan"],
        round=round_num,
        prev_feedback_section=prev_section,
    ) + search_section

    feedback = clients.llm.invoke(final_prompt).content
    passed = parse_verdict(feedback)
    print(f"  [Reviewer {side}] 판정: {'PASS' if passed else 'REVISE'}")

    update: dict = {
        history_key: [feedback],
        passed_key: passed,
        "messages": [AIMessage(content=feedback, name=msg_name)],
    }
    if increment_round:
        update["review_round"] = round_num
    return update


def reviewer_a(state: ResearchPlanState) -> ResearchPlanState:
    return _run_reviewer(
        state,
        side="A",
        role="내용",
        history_key="review_a_history",
        passed_key="review_a_passed",
        review_prompt_id="PROMPT_REVIEWER_A",
        msg_name="reviewer_a",
        increment_round=True,
        reviewer_label="Reviewer A",
        with_search=True,
    )


def reviewer_b(state: ResearchPlanState) -> ResearchPlanState:
    return _run_reviewer(
        state,
        side="B",
        role="가독성",
        history_key="review_b_history",
        passed_key="review_b_passed",
        review_prompt_id="PROMPT_REVIEWER_B",
        msg_name="reviewer_b",
        increment_round=False,
        reviewer_label="Reviewer B",
        with_search=REVIEWER_B_SEARCH,
    )


def _verdict(ok: bool) -> str:
    return "PASS" if ok else "REVISE"


def save_review_round(
    round_num: int,
    *,
    plan: str,
    review_a: str,
    review_b: str,
    editor_raw: str,
    a_passed: bool,
    b_passed: bool,
    passed: bool,
) -> str:
    """라운드별 심사 기록을 이번 실행 폴더에 남긴다. 저장 실패는 파이프라인을 세우지 않는다.

    두 파일을 쓴다. round_N.md 는 판정과 세 피드백 원문, plan_round_N.md 는 그 라운드가 심사한 본문이다.
    본문을 따로 두는 이유는 라운드 사이의 재작성을 파일 비교로 볼 수 있게 하기 위해서다.
    초안은 최종본에 덮이므로 이 파일이 없으면 실행 뒤에 남지 않는다.
    """
    try:
        out = review_dir()
        record = (
            f"# 심사 라운드 {round_num}\n\n"
            f"- Reviewer A (내용): {_verdict(a_passed)}\n"
            f"- Reviewer B (가독성): {_verdict(b_passed)}\n"
            f"- 코드 판정: {_verdict(passed)} (두 리뷰어가 모두 PASS 여야 통과)\n"
            f"- 심사한 본문: plan_round_{round_num}.md ({len(plan)}자)\n\n"
            f"## Reviewer A — 내용 (검증 검색 포함)\n\n{review_a}\n\n"
            f"## Reviewer B — 가독성 (검색 없음)\n\n{review_b}\n\n"
            f"## Editor — 통합 피드백 (원문. INTEGRATED_FEEDBACK 아래가 Writer 에게 전달된다)\n\n{editor_raw}\n"
        )
        path = out / f"round_{round_num}.md"
        path.write_text(record, encoding="utf-8")
        (out / f"plan_round_{round_num}.md").write_text(plan, encoding="utf-8")
        return str(path)
    except OSError as exc:  # noqa: BLE001 - 기록 실패로 심사를 멈추지 않는다
        print(f"  [Editor] 심사 기록 저장 실패 ({type(exc).__name__})")
        return ""


def editor(state: ResearchPlanState) -> ResearchPlanState:
    """두 피드백을 Writer 용 수정 지시로 정리한다. 통과 여부는 두 리뷰어의 VERDICT 로 코드가 결정한다."""
    round_num = state.get("review_round", 0)
    a_passed = bool(state.get("review_a_passed"))
    b_passed = bool(state.get("review_b_passed"))
    passed = a_passed and b_passed
    print(f"[Editor] 피드백 정리 중... (라운드 {round_num}) — "
          f"A(내용) {'PASS' if a_passed else 'REVISE'}, B(가독성) {'PASS' if b_passed else 'REVISE'} "
          f"→ 코드 판정 {'PASS' if passed else 'REVISE'}")

    a_history = state.get("review_a_history", [])
    b_history = state.get("review_b_history", [])
    current_a = a_history[-1] if a_history else "피드백 없음"
    current_b = b_history[-1] if b_history else "피드백 없음"

    response = clients.llm.invoke(PROMPTS["PROMPT_EDITOR"].format(
        abstract=state["abstract"],
        research_plan=state["research_plan"],
        review_a=current_a,
        review_b=current_b,
    ))
    content = response.content
    llm_says_pass = "FINAL_VERDICT: PASS" in content
    if llm_says_pass != passed:
        print(f"  [Editor] LLM 판정({'PASS' if llm_says_pass else 'REVISE'})이 코드 판정과 다름 → 코드 판정을 적용")

    editor_feedback = ""
    if "INTEGRATED_FEEDBACK:" in content:
        editor_feedback = content.split("INTEGRATED_FEEDBACK:")[1].strip()

    print(f"  [Editor] 최종 판정: {'PASS' if passed else 'REVISE'}")
    if not passed:
        print("\n  [Editor] 통합 피드백 미리보기:")
        print(f"  {editor_feedback[:300]}...")

    saved = save_review_round(
        round_num, plan=state.get("research_plan", ""), review_a=current_a, review_b=current_b,
        editor_raw=content, a_passed=a_passed, b_passed=b_passed, passed=passed,
    )
    if saved:
        print(f"  [Editor] 심사 기록 저장: {saved}")

    return {
        "editor_feedback": editor_feedback,
        "review_passed": passed,
        "rewrite_count": state.get("rewrite_count", 0) + (0 if passed else 1),
        "messages": [AIMessage(content=content, name="editor")],
    }
