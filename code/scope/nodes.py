# -*- coding: utf-8 -*-
"""Scope 단계: 재서술 → 진단형 질문(최대 3) → 초록 수정·확인 → 구조화 브리프(내부용) → Supervisor.

    scope                    초록을 Problem / Solution 으로 재서술 (LLM 1회)
      → clarify              1회차 Problem → 2회차 Solution → 3회차 정합성. 열린 질문 하나 + 참고 예시 2~3개 (LLM 1회/질문)
      ⇄ human_feedback       인터럽트. 자유 답변 / 예시 번호 / Enter(건너뜀) 를 문답에 기록
      → revise_abstract      문답을 반영한 초록 수정안 (LLM 1회)
      → human_abstract_feedback  인터럽트. Enter=수정안 확정, 텍스트 입력=그 텍스트를 초록으로 확정
      → write_brief          구조화 브리프 JSON (LLM 1회). 사용자에게 보이지 않고 시스템만 쓴다 —
                             연구 질문·범위·검색 핵심어·데이터 후보·평가 후보·기존 접근·미해결 이유·가정
      → supervisor           (research/supervisor.py) 수집기 A/B/C 지시문 (LLM 1회, JSON)

Test_folder/ScopeAgent/scope_agent.py 의 재서술·진단·정합성 프롬프트를 LangGraph 노드로 옮기고,
질문에 참고 예시를 붙이는 방식(사용자 결정)으로 조정했다. 브리프 텍스트는 research.parse_brief 가 읽는
"FIELD: value" 형식으로 렌더링되어 collector 프롬프트와 Writer 에 그대로 들어가고, 점검용으로
runtime/<실행>/research/brief.md 에 저장된다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core import clients
from core.config import MAX_CLARIFY_QUESTIONS
from core.paths import research_dir
from core.llm_json import invoke_json
from core.prompts import PROMPTS
from core.state import ResearchPlanState

from langchain_core.messages import AIMessage

# ── 질문 단계 ───────────────────────────────────────────────────────────────────

STAGES = [
    ("Problem", "problem",
     "Problem 서술(현상·원인·귀속)을 진단합니다. Solution 은 참고만 하고 이번 질문의 대상이 아닙니다."),
    ("Solution", "solution",
     "1차 문답으로 Problem 이 구체화되었습니다. 그것을 반영해 Solution 서술(대상·기제·개입 지점)을 진단합니다."),
    ("정합성", "alignment",
     "앞의 두 질문은 각각 한쪽만 보았습니다. 이번에는 두 영역이 만나는 지점을 봅니다. "
     "(1) Problem 이 지목한 원인과 Solution 이 작용하는 지점이 이어지는가 "
     "(2) Solution 이 성립하려면 필요한데 아직 나타나지 않은 전제가 있는가 "
     "(3) 둘이 특별히 걸리지 않으면 남은 공백 중 데이터·평가 설계에 가장 큰 영향을 주는 것. "
     "어긋나 보인다고 곧 결함은 아닙니다. 연구자에게 확인할 가치가 있는지로 판단합니다."),
]
SKIP_ANSWER = "(건너뜀 — 합리적으로 가정)"


# ── 헬퍼 ────────────────────────────────────────────────────────────────────────

def _clean(s: Any) -> str:
    return " ".join(str(s or "").split())


def _clean_list(items: Any, limit: int = 12) -> List[str]:
    if isinstance(items, str):
        items = [items]
    out = [_clean(x) for x in (items or []) if _clean(x)]
    return out[:limit]


def parse_clarify_question(data: Any) -> Optional[Dict[str, Any]]:
    """LLM 응답(JSON dict)에서 질문 1개를 정리. {"question": null} 이거나 형식 불량이면 None."""
    if not isinstance(data, dict) or not _clean(data.get("question")):
        return None
    diagnosis = []
    for d in data.get("diagnosis") or []:
        if isinstance(d, dict) and _clean(d.get("gap")):
            diagnosis.append({"gap": _clean(d.get("gap")), "impact": _clean(d.get("impact"))})
    return {
        "question": _clean(data["question"]),
        "examples": _clean_list(data.get("examples"), limit=3),
        "diagnosis": diagnosis[:4],
        "selected_gap": _clean(data.get("selected_gap")),
        "rationale": _clean(data.get("rationale")),
        "dimension": _clean(data.get("dimension")) or "other",
    }


def print_clarify_question(question: Dict[str, Any], round_num: int) -> None:
    stage_name = STAGES[min(round_num - 1, len(STAGES) - 1)][0]
    print(f"\n[Scope] 질문 {round_num}/{MAX_CLARIFY_QUESTIONS} — 초점: {stage_name}")
    if question.get("selected_gap"):
        print(f"  비어 있는 지점: {question['selected_gap']}")
    if question.get("rationale"):
        print(f"  왜 묻는가    : {question['rationale']}")
    print(f"\n  Q{round_num}. {question['question']}")
    if question.get("examples"):
        print("  참고 예시:")
        for i, ex in enumerate(question["examples"], 1):
            print(f"    {i}. {ex}")
    print("  (자기 말로 답하거나, 예시 번호를 치거나, Enter 로 건너뛰기)")


def resolve_clarify_answer(answer: str, examples: List[str]) -> str:
    """빈 입력 → 건너뜀, 예시 번호(1/2/3) → 그 예시, 그 외 → 자유 입력."""
    answer = (answer or "").strip()
    if not answer:
        return SKIP_ANSWER
    if answer.isdigit() and 1 <= int(answer) <= len(examples):
        return examples[int(answer) - 1]
    return answer


# ── 브리프 정규화·렌더링 (내부용) ────────────────────────────────────────────────

def normalize_brief(data: Any) -> Dict[str, Any]:
    """LLM 이 낸 브리프 JSON 을 고정 키·타입으로 정리한다."""
    d = data if isinstance(data, dict) else {}
    ev = d.get("evaluation_candidates") or {}
    if not isinstance(ev, dict):
        ev = {"task": _clean(ev)}
    cands = []
    for c in d.get("data_candidates") or []:
        if isinstance(c, dict) and _clean(c.get("name")):
            cands.append({k: _clean(c.get(k)) for k in ("name", "provider", "form", "scale", "status")})
        elif _clean(c):
            cands.append({"name": _clean(c), "provider": "", "form": "", "scale": "", "status": "추정"})
    return {
        "research_question": _clean(d.get("research_question")),
        "problem": _clean(d.get("problem")),
        "solution": _clean(d.get("solution")),
        "alignment_note": _clean(d.get("alignment_note")),
        "scope_in": _clean_list(d.get("scope_in")),
        "scope_out": _clean_list(d.get("scope_out")),
        "key_concepts_en": _clean_list(d.get("key_concepts_en")),
        "keywords_ko": _clean_list(d.get("keywords_ko"), limit=6),      # PDF 표지용 한국어 핵심어 (finalize/cover.py)
        "data_candidates": cands[:6],
        "evaluation_candidates": {
            "task": _clean(ev.get("task")),
            "metrics": _clean_list(ev.get("metrics")),
            "baselines": _clean_list(ev.get("baselines")),
        },
        "existing_approaches": _clean_list(d.get("existing_approaches"), limit=5),
        "unresolved_reason": _clean(d.get("unresolved_reason")),
        "user_constraints": _clean(d.get("user_constraints")) or "없음",
        "assumptions": _clean_list(d.get("assumptions")),
        "unknowns": _clean_list(d.get("unknowns")),
    }


def _fmt_candidate(c: Dict[str, str]) -> str:
    inner = "; ".join(x for x in (c.get("provider"), c.get("form"), c.get("scale")) if x)
    s = c["name"] + (f" ({inner})" if inner else "")
    return s + (f" [{c['status']}]" if c.get("status") else "")


def render_brief_text(brief: Dict[str, Any]) -> str:
    """research.parse_brief 가 읽는 'FIELD: value' 형식. 값이 빈 항목은 생략하지 않고 (없음) 으로 둔다."""
    ev = brief.get("evaluation_candidates") or {}
    ev_txt = " / ".join(x for x in (
        f"태스크: {ev.get('task')}" if ev.get("task") else "",
        f"지표: {', '.join(ev.get('metrics') or [])}" if ev.get("metrics") else "",
        f"비교 대상: {', '.join(ev.get('baselines') or [])}" if ev.get("baselines") else "",
    ) if x)
    lines = [
        f"RESEARCH QUESTION: {brief.get('research_question') or '(없음)'}",
        f"PROBLEM: {brief.get('problem') or '(없음)'}",
        f"SOLUTION: {brief.get('solution') or '(없음)'}",
        f"ALIGNMENT: {brief.get('alignment_note') or '(없음)'}",
        f"IN SCOPE: {'; '.join(brief.get('scope_in') or []) or '(없음)'}",
        f"OUT OF SCOPE: {'; '.join(brief.get('scope_out') or []) or '(없음)'}",
        f"KEY CONCEPTS: {', '.join(brief.get('key_concepts_en') or []) or '(없음)'}",
        f"DATA CANDIDATES: {'; '.join(_fmt_candidate(c) for c in brief.get('data_candidates') or []) or '(없음)'}",
        f"EVALUATION CANDIDATES: {ev_txt or '(없음)'}",
        f"EXISTING APPROACHES: {'; '.join(brief.get('existing_approaches') or []) or '(없음)'}",
        f"UNRESOLVED REASON: {brief.get('unresolved_reason') or '(없음)'}",
        f"USER CONSTRAINTS: {brief.get('user_constraints') or '없음'}",
        f"ASSUMPTIONS: {'; '.join(brief.get('assumptions') or []) or '없음'}",
        f"UNKNOWNS: {'; '.join(brief.get('unknowns') or []) or '없음'}",
    ]
    return "\n".join(lines)


# ── 노드 ────────────────────────────────────────────────────────────────────────

def scope(state: ResearchPlanState) -> ResearchPlanState:
    """상태 초기화 + 초록을 Problem/Solution 으로 재서술."""
    print(PROMPTS["PROMPT_SCOPE_GUIDE"].format(abstract=state["abstract"], max_questions=MAX_CLARIFY_QUESTIONS))
    print("[Scope] 초록을 문제/해결책으로 정리 중...")
    try:
        data = invoke_json(PROMPTS["PROMPT_SCOPE_RESTATE"].format(
            abstract=state["abstract"], user_requests=state.get("user_requests") or "없음"))
        problem, solution = _clean(data.get("problem")), _clean(data.get("solution"))
        missing, note = _clean_list(data.get("missing"), limit=6), _clean(data.get("note")) or "없음"
    except Exception as exc:  # noqa: BLE001 - 재서술 실패 시 초록 원문으로 진행
        print(f"  [Scope] 재서술 실패 ({type(exc).__name__}) → 초록 원문으로 진행")
        problem, solution, missing, note = state["abstract"], "", [], "없음"

    print("\n[문제 ]\n" + (problem or "(없음)"))
    print("\n[해결책]\n" + (solution or "(없음)"))
    if missing:
        print("\n[아직 서술되지 않은 요소]")
        for m in missing:
            print(f"  · {m}")
    if note and note != "없음":
        print(f"\n[모호했던 지점] {note}")

    return {
        "scope_problem": problem,
        "scope_solution": solution,
        "scope_missing": missing,
        "clarify_round": 0,
        "current_question": None,
        "current_answer": "",
        "clarify_qna": "",
        "research_brief": "",
        "research_brief_data": {},
        "rewrite_count": 0,
        "review_round": 0,
        "review_passed": False,
        "review_a_history": [],
        "review_b_history": [],
        "editor_feedback": "",
        "collector_a_search_count": 0,
        "collector_b_search_count": 0,
        "collector_c_search_count": 0,
        "is_a_sufficient": False,
        "is_b_sufficient": False,
        "is_c_sufficient": False,
    }


def clarify(state: ResearchPlanState) -> ResearchPlanState:
    """직전 답변까지 반영해 이번 단계(Problem → Solution → 정합성)의 진단형 질문 1개를 만들거나 종료."""
    asked = state.get("clarify_round", 0)
    if asked >= MAX_CLARIFY_QUESTIONS:
        print(f"[Scope] 질문 한도({MAX_CLARIFY_QUESTIONS}개) 도달 — 초록 수정으로 진행.\n")
        return {"current_question": None}

    stage_name, _dimension, stage_instruction = STAGES[min(asked, len(STAGES) - 1)]
    print(f"[Scope] 지금까지의 답변을 검토하고 다음 질문 생성 중... ({asked}/{MAX_CLARIFY_QUESTIONS}, 초점 {stage_name})")
    try:
        data = invoke_json(PROMPTS["PROMPT_SCOPE_CLARIFY"].format(
            abstract=state["abstract"],
            user_requests=state.get("user_requests") or "없음",
            problem=state.get("scope_problem") or "(없음)",
            solution=state.get("scope_solution") or "(없음)",
            missing="\n".join(f"- {m}" for m in state.get("scope_missing") or []) or "- (없음)",
            qna_so_far=state.get("clarify_qna") or "(아직 없음)",
            asked_count=asked,
            max_questions=MAX_CLARIFY_QUESTIONS,
            stage_name=stage_name,
            stage_instruction=stage_instruction,
        ))
    except Exception as exc:  # noqa: BLE001 - 질문 생성 실패는 질문 없이 진행
        print(f"  [Scope] 질문 생성 실패 ({type(exc).__name__}) — 질문 없이 진행")
        return {"current_question": None}

    question = parse_clarify_question(data)
    if question is None:
        print("[Scope] 설계를 바꿀 만한 공백이 없음 — 질문을 마칩니다.\n")
        return {"current_question": None}

    print_clarify_question(question, asked + 1)
    return {"current_question": question, "clarify_round": asked + 1}


def human_feedback(state: ResearchPlanState) -> ResearchPlanState:
    """인터럽트 지점. 재개 시 update_state 로 주입된 current_answer 를 문답에 누적."""
    question = state.get("current_question")
    if not question:
        return {}
    n = state.get("clarify_round", 0)
    resolved = resolve_clarify_answer(state.get("current_answer", ""), question.get("examples") or [])
    print(f"  → A{n}: {resolved}")
    entry = f"Q{n} [{question.get('dimension', 'other')}]: {question['question']}\nA{n}: {resolved}"
    qna = state.get("clarify_qna", "")
    return {
        "clarify_qna": f"{qna}\n\n{entry}" if qna else entry,
        "current_question": None,
        "current_answer": "",
    }


def revise_abstract(state: ResearchPlanState) -> ResearchPlanState:
    """문답을 반영해 초록 수정안을 만들고 사용자에게 제시."""
    print("[Scope] 문답을 바탕으로 초록 수정안 생성 중...")
    response = clients.llm.invoke(PROMPTS["PROMPT_REVISE_ABSTRACT"].format(
        abstract=state["abstract"],
        user_requests=state.get("user_requests") or "없음",
        clarify_qna=state.get("clarify_qna") or "(none)",
    ))
    proposal = response.content.strip()

    print("\n" + "=" * 40)
    print("[수정된 초록 제안]")
    print(proposal)
    print("=" * 40)
    print("\n이 초록으로 진행하려면 Enter, 직접 고치려면 초록 전체를 입력하세요.")
    return {"revised_abstract_proposal": proposal}


def human_abstract_feedback(state: ResearchPlanState) -> ResearchPlanState:
    """인터럽트 지점. Enter → 수정안 확정, 텍스트 입력 → 그 텍스트를 초록으로 확정."""
    proposal = state.get("revised_abstract_proposal", "")
    answer = (state.get("current_answer") or "").strip()
    final_abstract = answer if answer else (proposal or state["abstract"])
    print(f"\n[Scope] 최종 초록 확정:\n{final_abstract}\n")
    return {
        "abstract": final_abstract,
        "revised_abstract_proposal": "",
        "current_answer": "",
    }


def write_brief(state: ResearchPlanState) -> ResearchPlanState:
    """확정 초록 + 재서술 + 문답 → 구조화 브리프. 사용자에게 보이지 않고 시스템(수집기·Writer)만 쓴다."""
    print("[Scope] 연구 브리프 작성 중 (내부용)...")
    try:
        data = invoke_json(PROMPTS["PROMPT_RESEARCH_BRIEF"].format(
            abstract=state["abstract"],
            user_requests=state.get("user_requests") or "없음",
            problem=state.get("scope_problem") or "(없음)",
            solution=state.get("scope_solution") or "(없음)",
            clarification_qna=state.get("clarify_qna") or "(질문 없이 진행)",
        ))
    except Exception as exc:  # noqa: BLE001 - 브리프 실패 시 최소 브리프로 진행
        print(f"  [Scope] 브리프 생성 실패 ({type(exc).__name__}) → 초록 기반 최소 브리프로 진행")
        data = {"research_question": state["abstract"], "problem": state.get("scope_problem"),
                "solution": state.get("scope_solution")}
    brief = normalize_brief(data)
    text = render_brief_text(brief)

    try:
        brief_path = research_dir() / "brief.md"
        brief_path.write_text(
            "# Research Brief (internal)\n\n" + text + "\n\n## Q&A\n\n" + (state.get("clarify_qna") or "(none)") + "\n",
            encoding="utf-8")
        saved = f" → {brief_path}"
    except OSError:
        saved = ""
    n_data = len(brief["data_candidates"])
    print(f"  [Scope] 브리프 완료: 핵심어 {len(brief['key_concepts_en'])}개, 데이터 후보 {n_data}개, "
          f"기존 접근 {len(brief['existing_approaches'])}개, 가정 {len(brief['assumptions'])}개{saved}")
    return {
        "research_brief_data": brief,
        "research_brief": text,
        "messages": [AIMessage(content=text, name="write_brief")],
    }
