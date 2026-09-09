# -*- coding: utf-8 -*-
"""Reporter 노드: 심사를 통과한 계획서 → 최종 제출본. 심사 뒤에는 문서를 다시 쓰지 않는다.

1) 표기 정리(코드, finalize/cleanup.py): 그림 표기, 허용 위치 밖·반복·카드에 없는 인용, 마크다운 강조, 참고문헌 섹션 제거.
2) 양식 검사(코드). 오류가 남았을 때만 위반 수정 LLM 을 최대 MAX_LINT_FIX_ROUNDS 회 부르고,
   수정본이 지목된 위반에 비해 많은 줄을 바꾸면(LINT_FIX_MAX_LINES_PER_ISSUE) 버리고 이전 본을 유지한다.
3) 참고문헌(코드, finalize/references.py): 본문 인용을 학술 카드와 대조해 생성·부착.
그림은 본문에 넣지 않는다. 경로와 캡션은 프론트매터로 전달되고, 삽입은 조판 단계가 담당한다.
심사 통과본 대비 바뀐 줄 수를 reporter_changes 에 남긴다.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from core.config import LINT_FIX_MAX_LINES_PER_ISSUE
from core.state import ResearchPlanState
from finalize.cleanup import mechanical_cleanup
from finalize.references import attach_references, strip_references_section
from write.lint_loop import count_changed_lines, lint_fix_loop


def reporter(state: ResearchPlanState) -> ResearchPlanState:
    print("[Reporter] 최종 제출본 정리 중... (심사 통과본을 다시 쓰지 않고 표기만 정리)")
    plan = state["research_plan"]
    cards = state.get("arxiv_cards") or []

    cleaned, cleanup = mechanical_cleanup(plan, cards)
    print(f"  [Reporter] 표기 정리: {cleanup.summary()}")

    text, lint_summary, report = lint_fix_loop(
        cleaned, cards, label="reporter", change_guard=LINT_FIX_MAX_LINES_PER_ISSUE,
    )
    llm_calls = int(report.metrics.get("llm_calls", 0))
    fix_lines = int(report.metrics.get("changed_lines", 0))
    rejects = int(report.metrics.get("guard_rejects", 0))
    if llm_calls == 0:
        print("  [Reporter] 양식 오류 없음 → LLM 호출 없이 확정")

    final, info = attach_references(text, cards)
    if info["unmatched_citations"]:
        print(f"  [Reporter] 카드에 없는 인용 {len(info['unmatched_citations'])}건은 표기를 제거함: "
              f"{', '.join(info['unmatched_citations'])}")
    changed, total = count_changed_lines(strip_references_section(plan), strip_references_section(final))
    changes = (f"{changed}/{total} lines (cleanup {cleanup.changed_lines}, lint-fix {fix_lines}, "
               f"llm calls {llm_calls}, guard rejects {rejects})")
    print(f"  [Reporter] 심사 통과본 대비 본문 변경 {changed}/{total}줄 "
          f"(표기 정리 {cleanup.changed_lines}줄, 양식 수정 {fix_lines}줄, LLM 호출 {llm_calls}회, 범위 초과로 버린 수정본 {rejects}건)")
    print(f"  [Reporter] 참고문헌 {info['references']}건 (학술 카드 기반) — 정리 완료")
    return {
        "research_paper": final,
        "lint_reporter": lint_summary,
        "references_count": info["references"],
        "reporter_changes": changes,
        "messages": [AIMessage(content=final, name="reporter")],
    }
