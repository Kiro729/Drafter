# -*- coding: utf-8 -*-
"""도해 노드: 심사 통과 계획서의 '연구 방법론' 절 → Archify workflow 다이어그램 (PNG/SVG).

그래프에서 editor PASS(또는 라운드 한도) 뒤 한 번 실행된다. 실제 작성·검증·렌더는 finalize/diagram_agent.py 의
서브그래프가 하고, 이 노드는 절을 잘라 넘기고 결과 경로·캡션·검증 결과를 state 에 올린다.
산출물은 이번 실행의 figures/ 아래 framework.{png,svg,html,spec.json}. 본문에는 그림을 넣지 않는다 —
경로와 캡션이 프론트매터로 전달되어 조판 단계(finalize/export_pdf.py)가 삽입한다.
Archify·Node·브라우저가 없으면 그림 없이 진행하고 원인을 로그에 남긴다.
"""
from __future__ import annotations

import re

from langchain_core.messages import AIMessage

from core.paths import relative_to_root
from core.state import ResearchPlanState
from finalize.diagram_agent import run_diagram_agent

_METHOD_HEAD_RE = re.compile(r"^##\s*(?:\d+\.\s*)?연구\s*방법론[^\n]*$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s", re.MULTILINE)


def extract_methodology_section(research_plan: str) -> tuple:
    """계획서에서 '## 3. 연구 방법론' 절만 잘라 낸다. 못 찾으면 전문을 돌려준다. (본문, 찾았는지)"""
    m = _METHOD_HEAD_RE.search(research_plan)
    if not m:
        return research_plan, False
    nxt = _H2_RE.search(research_plan, m.end())
    section = research_plan[m.start(): nxt.start() if nxt else len(research_plan)].strip()
    return (section, True) if section else (research_plan, False)


def plot_framework(state: ResearchPlanState) -> ResearchPlanState:
    print("[PlotAgent] 프레임워크 다이어그램 생성 중... (Archify)")

    methodology, found = extract_methodology_section(state["research_plan"])
    if not found:
        print("  [PlotAgent] '연구 방법론' 절을 찾지 못해 계획서 전문을 입력으로 사용")

    result = run_diagram_agent(methodology_text=methodology, figure_id="framework")

    caption = " ".join(str(result.get("caption_ko") or "").split())
    checks = result.get("checks_passed") or ""
    repairs = int(result.get("repair_rounds") or 0)
    error = result.get("error")
    if result.get("note"):
        print(f"  [PlotAgent] {result['note']}")

    if error or not result.get("png_path"):
        print(f"  [PlotAgent] 다이어그램 생성 실패: {error or 'PNG 가 생성되지 않음'}")
        figure_path = svg_path = ""
    else:
        figure_path = relative_to_root(result["png_path"])
        svg_path = relative_to_root(result.get("svg_path"))
        print(f"  [PlotAgent] 렌더링 완료: {figure_path}  (Archify 검증 {checks}, 수리 {repairs}회)")
        if svg_path:
            print(f"  [PlotAgent] SVG: {svg_path}")
        if caption:
            print(f"  [PlotAgent] 캡션: {caption}")

    return {
        "framework_figure_path": figure_path,
        "framework_svg_path": svg_path,
        "framework_caption": caption,
        "diagram_checks": checks,
        "diagram_repair_rounds": repairs,
        "messages": [AIMessage(content=caption or f"[plot_agent error] {error}", name="plot_agent")],
    }
