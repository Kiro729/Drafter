# -*- coding: utf-8 -*-
"""Scope 단계 검증 (모의 LLM): 재서술 → 진단형 질문(예시 채택·건너뜀·조기 종료) → 초록 수정·확인 → 내부용 브리프 → Supervisor.

    python tests/test_scope_stage.py

1. 노드를 인터럽트 순서대로 직접 호출해 흐름 전체를 시뮬레이션 (브리프는 사용자 확인 없이 확정 초록으로 생성)
2. 브리프 텍스트가 research.parse_brief / brief_section 과 호환되고 데이터·평가 후보가 수집기 쪽에 전달됨
3. 그래프 연결 (revise_abstract → human_abstract_feedback → write_brief → supervisor)
4. 프롬프트 포맷
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
os.environ.setdefault("DRAFTER_SKIP_DOTENV", "1")      # 테스트는 프로젝트 .env(키·모델·백엔드)를 읽지 않는다

from core import clients
import scope.nodes as ns             # noqa: E402
import research.cards as research
from core import paths
from research.supervisor import supervisor
from core.output import initial_state   # noqa: E402
from core.prompts import PROMPTS   # noqa: E402

paths.start_run(ROOT / "tests" / "out", stamp="scope")   # brief.md 등 산출물을 tests/out/scope/ 에

ABSTRACT = "기존 추천 시스템 연구가 세렌디피티를 시스템 관점에서 평가해 온 것과 달리, 사용자 관점에서 세렌디피티를 판단하는 추천 방식을 제안한다."

BRIEF_JSON = {
    "research_question": "MovieLens 로그로 만든 사용자 디지털 트윈으로 일인칭 세렌디피티를 오프라인에서 추정할 수 있는가",
    "problem": "기존 지표는 사용자의 기대 상태를 모델링하지 않아 개인이 느끼는 놀람과 즐거움을 담지 못함.",
    "solution": "사용자 디지털 트윈으로 즐거움과 의외성을 분리 추정해 곱으로 결합함.",
    "alignment_note": "기대 상태 미모델링이라는 원인에 디지털 트윈이 직접 개입함.",
    "scope_in": ["영화 추천", "오프라인 평가"], "scope_out": ["온라인 A/B 테스트", "타 도메인"],
    "key_concepts_en": ["serendipity recommendation", "user digital twin", "MovieLens"],
    "keywords_ko": ["세렌디피티", " 추천 시스템 "],
    "data_candidates": [{"name": "MovieLens 20M", "provider": "GroupLens", "form": "평점·타임스탬프·장르", "scale": "", "status": "추정"}],
    "evaluation_candidates": {"task": "상위 k 추천 목록 평가", "metrics": ["세렌디피티@k", "nDCG@10"], "baselines": ["item-kNN", "행렬 분해"]},
    "existing_approaches": ["시스템 관점 지표 계열", "사용자 경험 설계 계열"],
    "unresolved_reason": "집단 통계와 사후 설문은 개인의 내적 기대 상태를 재현하지 못함(추정).",
    "user_constraints": "없음",
    "assumptions": ["MovieLens 20M 규모는 확인되지 않음"], "unknowns": ["놀람 임계값의 정의"],
}


class FakeResponse:
    def __init__(self, c):
        self.content = c


class FakeLLM:
    def __init__(self):
        self.calls = []

    def bind(self, **kw):
        return self

    def invoke(self, prompt):
        self.calls.append(prompt)
        if '"missing": [' in prompt and "[초록]" in prompt:                       # RESTATE
            return FakeResponse(json.dumps({"problem": "P 재서술", "solution": "S 재서술",
                                            "missing": ["Problem 원인 — 미서술", "Solution 개입 지점 — 미서술"], "note": "없음"}, ensure_ascii=False))
        if "[이번 질문의 초점" in prompt:                                          # CLARIFY
            if "초점 — Problem]" in prompt:
                return FakeResponse(json.dumps({"diagnosis": [{"gap": "원인 미서술", "impact": "논거가 달라짐"}],
                                                "selected_gap": "원인 미서술", "rationale": "설계를 가장 크게 바꿈",
                                                "question": "기존 지표가 개인 경험을 담지 못하는 이유는 무엇이라고 보십니까?",
                                                "examples": ["기대 상태를 모델링하지 않기 때문", "사후 설문에만 의존하기 때문", "목록 통계만 보기 때문"],
                                                "dimension": "problem"}, ensure_ascii=False))
            if "초점 — Solution]" in prompt:
                assert "A1: 사후 설문에만 의존하기 때문" in prompt                  # 예시 2번 채택이 문답에 반영
                return FakeResponse(json.dumps({"diagnosis": [{"gap": "데이터 미정", "impact": "모듈 1 입력이 달라짐"}],
                                                "selected_gap": "데이터 미정", "rationale": "x",
                                                "question": "디지털 트윈을 학습할 로그는 무엇입니까?",
                                                "examples": ["MovieLens 20M", "Netflix Prize"], "dimension": "solution"}, ensure_ascii=False))
            assert "A2: (건너뜀" in prompt                                        # 2번째는 건너뜀
            return FakeResponse(json.dumps({"question": None}))                    # 3회차: 조기 종료
        if "Original Abstract:" in prompt:                                          # REVISE_ABSTRACT
            return FakeResponse("수정된 초록: 사용자 디지털 트윈으로 일인칭 세렌디피티를 추정한다.")
        if '"research_question"' in prompt and "[연구자와의 문답]" in prompt:        # BRIEF
            assert "[확정된 초록]\n수정된 초록" in prompt                             # 확정 초록으로 브리프 작성
            return FakeResponse(json.dumps(BRIEF_JSON, ensure_ascii=False))
        if '"collector_a"' in prompt:                                               # SUPERVISOR
            assert "DATA CANDIDATES: MovieLens 20M" in prompt
            return FakeResponse(json.dumps({"collector_a": "배경 지시", "collector_b": "방법 지시", "collector_c": "논문 지시"}))
        raise AssertionError(prompt[:300])


def section(t):
    print("\n" + "=" * 12, t, "=" * 12)


def main():
    clients.llm = FakeLLM()
    state = initial_state(ABSTRACT, "")

    # ── 1 ───────────────────────────────────────────────────────────────────────
    section("1. scope → clarify/human_feedback ×3 → revise → brief → confirm loop → supervisor")
    state.update(ns.scope(state))
    assert state["scope_problem"] == "P 재서술" and len(state["scope_missing"]) == 2

    state.update(ns.clarify(state))                                   # Q1 (Problem)
    q1 = state["current_question"]
    assert q1["dimension"] == "problem" and len(q1["examples"]) == 3 and q1["selected_gap"] == "원인 미서술"
    state["current_answer"] = "2"                                     # 예시 2번 채택
    state.update(ns.human_feedback(state))
    assert "A1: 사후 설문에만 의존하기 때문" in state["clarify_qna"] and "[problem]" in state["clarify_qna"]

    state.update(ns.clarify(state))                                   # Q2 (Solution)
    assert state["current_question"]["dimension"] == "solution" and state["clarify_round"] == 2
    state["current_answer"] = ""                                      # 건너뜀
    state.update(ns.human_feedback(state))
    assert "A2: (건너뜀" in state["clarify_qna"]

    state.update(ns.clarify(state))                                   # Q3 → 조기 종료
    assert state["current_question"] is None and state["clarify_round"] == 2
    assert ns.resolve_clarify_answer("나만의 답", ["x"]) == "나만의 답" and ns.resolve_clarify_answer("1", ["첫째"]) == "첫째"

    state.update(ns.revise_abstract(state))
    assert state["revised_abstract_proposal"].startswith("수정된 초록")
    # 초록 확인: Enter → 수정안 확정 (브리프는 아직 없음)
    state["current_answer"] = ""
    state.update(ns.human_abstract_feedback(state))
    assert state["abstract"].startswith("수정된 초록") and state["revised_abstract_proposal"] == ""
    # 직접 입력하면 그 텍스트가 초록이 된다
    alt = ns.human_abstract_feedback({**state, "revised_abstract_proposal": "제안", "current_answer": "내가 쓴 초록"})
    assert alt["abstract"] == "내가 쓴 초록"

    # 브리프는 확정 뒤 내부용으로 생성 (사용자 확인 없음)
    state.update(ns.write_brief(state))
    brief = state["research_brief_data"]
    assert brief["data_candidates"][0]["status"] == "추정"
    assert brief["keywords_ko"] == ["세렌디피티", "추천 시스템"]                    # 표지 키워드 (cover 노드가 쓴다)
    assert "DATA CANDIDATES: MovieLens 20M (GroupLens; 평점·타임스탬프·장르) [추정]" in state["research_brief"]
    assert (paths.research_dir() / "brief.md").exists()
    assert not hasattr(ns, "route_after_abstract_feedback")            # 확인·수정 루프 제거됨

    state.update(supervisor(state))
    assert state["collector_a_prompt"] == "배경 지시" and state["collector_c_prompt"] == "논문 지시"
    n_llm = len(clients.llm.calls)
    print("LLM calls:", n_llm, "(restate 1 + clarify 3 + revise 1 + brief 1 + supervisor 1)")
    assert n_llm == 7
    print("1 ok")

    # ── 2 ───────────────────────────────────────────────────────────────────────
    section("2. brief text is parsed downstream; data/eval/approaches reach collectors")
    f = research.parse_brief(state["research_brief"])
    assert f["RESEARCH QUESTION"].startswith("MovieLens 로그로") and f["OUT OF SCOPE"] == "온라인 A/B 테스트; 타 도메인"
    assert f["KEY CONCEPTS"] == "serendipity recommendation, user digital twin, MovieLens"
    assert f["DATA CANDIDATES"].startswith("MovieLens 20M") and "nDCG@10" in f["EVALUATION CANDIDATES"]
    bs = research.brief_section(state["research_brief"])
    assert "DATA CANDIDATES:" in bs and "EVALUATION CANDIDATES:" in bs and "EXISTING APPROACHES:" in bs and "UNRESOLVED REASON:" in bs
    assert "USER CONSTRAINTS" not in bs                               # '없음' 은 생략
    # 구 형식 브리프(영어 6항목)도 그대로 읽힌다
    legacy = "RESEARCH QUESTION: q\nIN SCOPE: a\nOUT OF SCOPE: b\nKEY CONCEPTS: k\nUSER CONSTRAINTS: none\nASSUMPTIONS: none"
    lf = research.parse_brief(legacy)
    assert lf["IN SCOPE"] == "a" and lf["DATA CANDIDATES"] == "" and "DATA CANDIDATES" not in research.brief_section(legacy)
    print(bs)
    print("2 ok")

    # ── 3 ───────────────────────────────────────────────────────────────────────
    section("3. graph wiring")
    from core import graph
    g = graph.build_graph().get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    assert ("revise_abstract", "human_abstract_feedback") in edges and ("human_abstract_feedback", "write_brief") in edges
    assert ("write_brief", "supervisor") in edges
    assert ("human_abstract_feedback", "human_abstract_feedback") not in edges     # 확인·수정 루프 없음
    print("3 ok")

    # ── 4 ───────────────────────────────────────────────────────────────────────
    section("4. prompt formats")
    PROMPTS["PROMPT_SCOPE_GUIDE"].format(abstract="a", max_questions=3)
    PROMPTS["PROMPT_SCOPE_RESTATE"].format(abstract="a", user_requests="u")
    PROMPTS["PROMPT_SCOPE_CLARIFY"].format(abstract="a", user_requests="u", problem="p", solution="s", missing="- m",
                                           qna_so_far="q", asked_count=0, max_questions=3, stage_name="Problem", stage_instruction="i")
    PROMPTS["PROMPT_RESEARCH_BRIEF"].format(abstract="a", user_requests="u", problem="p", solution="s", clarification_qna="q")
    assert "PROMPT_SCOPE_APPLY_EDITS" not in PROMPTS
    PROMPTS["PROMPT_SUPERVISOR"].format(abstract="a", user_requests="u", research_brief="b")
    w = PROMPTS["PROMPT_WRITER"].format(abstract="a", user_requests="u", research_brief="b", background_data="x", method_data="y", arxiv_data="z")
    assert "브리프 항목의 사용" in w
    print("4 ok")

    print("\nALL SCOPE-STAGE TESTS PASSED")


if __name__ == "__main__":
    main()
