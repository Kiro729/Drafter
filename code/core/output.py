# -*- coding: utf-8 -*-
"""초기 상태 생성과 최종 마크다운 저장."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage

from core.config import MAX_REVIEW_ROUNDS, resolve_scholar_backend
from core.paths import FINAL_DIR, relative_to_root, run_dir, run_stamp


def initial_state(abstract: str, user_requests: str = "") -> dict:
    """파이프라인 최초 실행에 필요한 초기 상태."""
    return {
        "abstract": abstract,
        "user_requests": user_requests,
        # scope
        "scope_problem": "", "scope_solution": "", "scope_missing": [],
        "clarify_round": 0, "current_question": None, "current_answer": "", "clarify_qna": "",
        "revised_abstract_proposal": "", "research_brief_data": {}, "research_brief": "",
        # research
        "collector_a_prompt": "", "collector_b_prompt": "", "collector_c_prompt": "",
        "background_data": "", "method_data": "", "arxiv_data": "",
        "background_cards": [], "method_cards": [], "arxiv_cards": [],
        "is_a_sufficient": False, "is_b_sufficient": False, "is_c_sufficient": False,
        "collector_a_coverage": "", "collector_b_coverage": "", "collector_c_coverage": "",
        "collector_a_search_count": 0, "collector_b_search_count": 0, "collector_c_search_count": 0,
        # write · finalize
        "research_plan": "", "lint_writer": "", "lint_reporter": "", "references_count": 0, "reporter_changes": "",
        "cover_subtitle": "", "cover_keywords": [],
        "framework_figure_path": "", "framework_caption": "", "framework_svg_path": "",
        "diagram_checks": "", "diagram_repair_rounds": 0,
        "research_paper": "",
        # review
        "review_round": 0, "review_a_history": [], "review_b_history": [],
        "review_a_passed": False, "review_b_passed": False, "editor_feedback": "", "review_passed": False,
        "rewrite_count": 0,
        "messages": [HumanMessage(content="연구계획서 생성 시작")],
    }


def save_research_paper_as_markdown(state_values: dict, output_dir: Optional[Path] = None) -> str:
    """최종 상태를 프론트매터 + 본문 마크다운으로 저장하고 경로를 돌려준다.

    파일명은 실행 폴더와 같은 시각(run_stamp)을 써서 final/ 의 결과와 runtime/<시각>/ 의 중간 산출물이 짝이 맞는다.
    """
    fv = state_values
    verdict = "PASS" if fv["review_passed"] else f"Max {MAX_REVIEW_ROUNDS} rounds completed"

    lines = [
        "---",
        f"generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"run_dir: {relative_to_root(run_dir())}",
        f"review_rounds: {fv['review_round']}",
        f"final_verdict: {verdict}",
        f"search_count: Tavily(A) {fv['collector_a_search_count']} / Tavily(B) {fv['collector_b_search_count']} / "
        f"scholar(C) {fv['collector_c_search_count']}",
        f"evidence_cards: A {len(fv.get('background_cards') or [])} / B {len(fv.get('method_cards') or [])} / "
        f"C {len(fv.get('arxiv_cards') or [])}",
        f"scholar_backend: {resolve_scholar_backend()}",
    ]
    for side, key in (("A", "collector_a_coverage"), ("B", "collector_b_coverage"), ("C", "collector_c_coverage")):
        if fv.get(key):
            lines.append(f"coverage_{side}: {fv[key]}")
    if fv.get("lint_writer") or fv.get("lint_reporter"):
        lines.append(f"format_lint: writer [{fv.get('lint_writer') or 'n/a'}] / reporter [{fv.get('lint_reporter') or 'n/a'}]")
    if fv.get("reporter_changes"):
        lines.append(f"reporter_changes: {fv['reporter_changes']} vs review-passed text")
    lines.append(f"references: {fv.get('references_count', 0)} (from scholar cards)")
    if fv.get("cover_subtitle"):                                    # 표지용. export_pdf 가 PDF_SUBTITLE/PDF_KEYWORDS 가 빈 경우 쓴다
        lines.append(f"subtitle: {fv['cover_subtitle']}")
    if fv.get("cover_keywords"):
        lines.append(f"keywords: {', '.join(fv['cover_keywords'])}")
    if fv.get("framework_figure_path"):
        lines.append(f"framework_figure: {fv['framework_figure_path']}")
        if fv.get("framework_caption"):
            lines.append(f"framework_caption: {' '.join(fv['framework_caption'].split())}")
        if fv.get("framework_svg_path"):
            lines.append(f"framework_svg: {fv['framework_svg_path']}")
        if fv.get("diagram_checks"):
            lines.append(f"diagram_checks: {fv['diagram_checks']} (repairs {fv.get('diagram_repair_rounds', 0)})")
    lines += ["---", ""]

    out_dir = Path(output_dir) if output_dir else FINAL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    filepath = out_dir / f"research_paper_{run_stamp()}.md"
    content = fv.get("research_paper") or fv.get("research_plan", "")
    filepath.write_text("\n".join(lines) + "\n" + content, encoding="utf-8")
    print(f"  Saved: {filepath}")
    return str(filepath)
