# -*- coding: utf-8 -*-
"""Supervisor 노드: 확정 초록 + 내부용 브리프 → Collector A/B/C 지시문 (LLM 1회, JSON).

Research 단계의 첫 노드. 지시문은 각 collector 의 쿼리 생성 프롬프트에 들어가며, 비어 있으면 collector 는 브리프만으로 진행한다.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage

from core.llm_json import invoke_json
from core.prompts import PROMPTS
from core.state import ResearchPlanState

_KEYS = ("collector_a", "collector_b", "collector_c")


def _clean(s: Any) -> str:
    return " ".join(str(s or "").split())


def supervisor(state: ResearchPlanState) -> ResearchPlanState:
    print("[Supervisor] Collector 지시문 생성 중...")
    prompt = PROMPTS["PROMPT_SUPERVISOR"].format(
        abstract=state["abstract"],
        user_requests=state.get("user_requests") or "없음",
        research_brief=state.get("research_brief") or "없음",
    )
    try:
        data = invoke_json(prompt)
        instr = {k: _clean(data.get(k)) for k in _KEYS}
        raw = json.dumps(data, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 - 지시문 실패는 브리프만으로 진행
        print(f"  [Supervisor] 지시문 생성 실패 ({type(exc).__name__}) → collector 는 브리프만으로 진행")
        instr = {k: "" for k in _KEYS}
        raw = f"[supervisor error] {exc}"
    if not all(instr.values()):
        print("  [Supervisor] 지시문 일부가 비어 있음 — 해당 collector 는 브리프만으로 진행")

    print("\n" + "=" * 40)
    for label, key in (("Collector A 프롬프트 — 웹/연구배경", "collector_a"),
                       ("Collector B 프롬프트 — 웹/방법론", "collector_b"),
                       ("Collector C 프롬프트 — 학술 논문", "collector_c")):
        print(f"[{label}]\n{instr[key] or '(없음)'}\n")
    print("=" * 40 + "\n")

    return {
        "collector_a_prompt": instr["collector_a"],
        "collector_b_prompt": instr["collector_b"],
        "collector_c_prompt": instr["collector_c"],
        "messages": [AIMessage(content=raw, name="supervisor")],
    }
