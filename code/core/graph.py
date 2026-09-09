# -*- coding: utf-8 -*-
"""LangGraph 상태 그래프: 다섯 단계의 노드를 잇고 라우팅한다.

    [Scope]     scope(재서술) → clarify ⇄ human_feedback → revise_abstract → human_abstract_feedback → write_brief(내부용)
    [Research]  supervisor ──┬──> collector_a ──┐
                             ├──> collector_b ──┼──> writer
                             └──> collector_c ──┘
    [Write]     writer(+양식 검사) ──> reviewer_a ──> reviewer_b ──> editor
    [Review]        ▲                                              │  REVISE (≤ MAX_REVIEW_ROUNDS)
                    └──────────────────────────────────────────────┤
    [Finalize]                                                     ▼  PASS / 한도
                                                       plot_framework(Archify 1회) ──> reporter ──> cover(표지) ──> END

human_feedback · human_abstract_feedback 앞에서 인터럽트가 걸리고, main.run() 이 사용자 입력을 넣어 재개한다.
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from core.config import MAX_REVIEW_ROUNDS
from core.state import ResearchPlanState
from finalize.cover import cover
from finalize.diagram import plot_framework
from finalize.reporter import reporter
from research.collectors import collector_a, collector_b, collector_c
from research.supervisor import supervisor
from review.nodes import editor, reviewer_a, reviewer_b
from scope.nodes import clarify, human_abstract_feedback, human_feedback, revise_abstract, scope, write_brief
from write.writer import writer


# ── 라우터 ──────────────────────────────────────────────────────────────────────

def route_after_clarify(state: ResearchPlanState) -> str:
    """질문이 생성됐으면 human_feedback(인터럽트)으로, 아니면 revise_abstract 로."""
    return "human_feedback" if state.get("current_question") else "revise_abstract"


def route_after_editor(state: ResearchPlanState) -> str:
    """심사 결과: REVISE 면 Writer 재작성, PASS(또는 라운드 한도)면 도해 생성으로."""
    if state.get("review_passed", False):
        print("\n[Route] Editor PASS → 도해 생성(plot_framework)")
        return "plot_framework"
    round_num = state.get("review_round", 0)
    if round_num >= MAX_REVIEW_ROUNDS:
        print(f"\n[Route] {MAX_REVIEW_ROUNDS} rounds completed → 도해 생성(plot_framework) (forced)")
        return "plot_framework"
    print(f"\n[Route] Editor REVISE → Writer rewrite (round {round_num} done)")
    return "writer"


# ── 그래프 빌더 ─────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(ResearchPlanState)

    for name, fn in (
        ("scope", scope), ("clarify", clarify), ("human_feedback", human_feedback),
        ("revise_abstract", revise_abstract), ("human_abstract_feedback", human_abstract_feedback),
        ("write_brief", write_brief), ("supervisor", supervisor),
        ("collector_a", collector_a), ("collector_b", collector_b), ("collector_c", collector_c),
        ("writer", writer), ("reviewer_a", reviewer_a), ("reviewer_b", reviewer_b), ("editor", editor),
        ("plot_framework", plot_framework), ("reporter", reporter), ("cover", cover),
    ):
        g.add_node(name, fn)

    g.set_entry_point("scope")

    # Scope: 질문 1개 생성 → 인터럽트(사용자 답변) → 답변 보고 다음 질문 결정. 초록 확정 뒤 내부용 브리프.
    g.add_edge("scope", "clarify")
    g.add_conditional_edges("clarify", route_after_clarify,
                            {"human_feedback": "human_feedback", "revise_abstract": "revise_abstract"})
    g.add_edge("human_feedback", "clarify")
    g.add_edge("revise_abstract", "human_abstract_feedback")
    g.add_edge("human_abstract_feedback", "write_brief")
    g.add_edge("write_brief", "supervisor")

    # Research: supervisor → 세 collector 동시 실행 → 셋 다 끝나야 writer
    for c in ("collector_a", "collector_b", "collector_c"):
        g.add_edge("supervisor", c)
        g.add_edge(c, "writer")

    # Write → Review (REVISE 면 writer 로 되돌아가 재작성)
    g.add_edge("writer", "reviewer_a")
    g.add_edge("reviewer_a", "reviewer_b")
    g.add_edge("reviewer_b", "editor")
    g.add_conditional_edges("editor", route_after_editor, {"writer": "writer", "plot_framework": "plot_framework"})

    # Finalize: 심사 통과 본문으로 도해 1회 → 최종 정리(표기·참고문헌) → 표지 부제·키워드
    g.add_edge("plot_framework", "reporter")
    g.add_edge("reporter", "cover")
    g.add_edge("cover", END)

    return g.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["human_feedback", "human_abstract_feedback"],
    )
