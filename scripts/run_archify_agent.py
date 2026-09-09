#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Archify 도해 에이전트 단독 실행.

연구계획서의 "연구 방법론" 절 텍스트 파일 하나로 다이어그램 서브그래프를 돌려 본다.
파이프라인 전체(수집·심사)를 돌리지 않고 도해 품질만 빠르게 확인할 때 쓴다.

    python scripts/run_archify_agent.py tests/fixtures/methodology.md
    python scripts/run_archify_agent.py methodology.md --figure-id framework_manual
    python scripts/run_archify_agent.py methodology.md --feedback "모듈 2 노드가 빠짐"

OPENAI_API_KEY 가 필요하다 (.env 또는 환경변수). Tavily 키는 쓰지 않는다.
결과는 runtime/<실행시각>/figures/<figure_id>.{png,svg,html,spec.json} 으로 남는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("methodology", help="연구 방법론 절 텍스트 파일 (.md/.txt)")
    ap.add_argument("--figure-id", default="framework_manual", help="출력 파일 basename (기본 framework_manual)")
    ap.add_argument("--feedback", default="", help="이전 라운드 피드백을 흉내 낼 때")
    ap.add_argument("--model", default=None, help="OpenAI 모델. 기본은 .env 의 OPENAI_MODEL, 없으면 gpt-5.1")
    args = ap.parse_args()

    text = Path(args.methodology).read_text(encoding="utf-8")

    from core import paths
    from core.clients import init_clients
    from finalize.diagram_agent import DiagramConfig, preflight, run_diagram_agent

    issues = preflight(DiagramConfig(out_dir=ROOT / "runtime"))
    if issues:
        print("preflight 실패:")
        for i in issues:
            print("  -", i)
        return 1

    os.environ.setdefault("TAVILY_API_KEY", "unused-for-diagram-only")   # init_clients 가 요구하지만 여기선 안 쓴다
    init_clients(model=args.model)
    print(f"[run] 실행 폴더: {paths.start_run()}")

    out = run_diagram_agent(text, args.figure_id, feedback=args.feedback)
    if out.get("error"):
        print("실패:", out["error"])
        print("마지막 스펙:", json.dumps(out.get("spec"), ensure_ascii=False, indent=2)[:2000])
        return 1
    print(json.dumps(out["result"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
