#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Research 단계만 실제 API 로 돌려 본다 (Scope 질문·Writer·심사·PDF 는 건너뜀).

    python scripts/run_research_stage.py
    python scripts/run_research_stage.py --abstract-file my_abstract.txt
    python scripts/run_research_stage.py --only C                 # Collector C 만
    python scripts/run_research_stage.py --brief-file brief.txt   # 브리프 LLM 생성 건너뜀

필요한 키: OPENAI_API_KEY, TAVILY_API_KEY (A/B 채널). LINER_API_KEY 가 있으면 C 채널이 Liner 하이브리드로 돈다.
흐름: 초록 → 브리프(LLM 1회) → supervisor(LLM 1회) → 선택한 collector 들을 순서대로 실행 → 결과 요약 출력.
산출물: runtime/<실행시각>/research/ 의 brief.md, cards_{A,B,C}.json, evidence_{A,B,C}.md (main.py 실행과 같은 배치)
비용 감: collector 하나가 라운드당 LLM 5회, 최대 3라운드. 셋 다 돌리면 LLM 최대 47회.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

DEFAULT_ABSTRACT = (
    "기존 추천 시스템 연구가 세렌디피티(예상치 못한 즐거움)를 사용자 외부의 관점에서 평가해 온 것과 달리, "
    "세렌디피티는 본질적으로 주관적이고 일인칭적인 경험이라는 전제에 기반하여, "
    "사용자의 관점에서 세렌디피티를 판단하는 추천 방식을 제안한다."
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--abstract-file", help="초록 텍스트 파일. 없으면 main.py 의 세렌디피티 초록을 쓴다")
    ap.add_argument("--requests", default="", help="추가 요청사항")
    ap.add_argument("--brief-file", help="이미 만든 브리프 텍스트 파일 (LLM 브리프 생성 건너뜀)")
    ap.add_argument("--only", default="ABC", help="실행할 collector 문자들 (기본 ABC, 예: C 또는 AC)")
    ap.add_argument("--model", default=None, help="OpenAI 모델. 기본은 .env 의 OPENAI_MODEL, 없으면 gpt-5.1")
    args = ap.parse_args()

    from core import paths
    from core.clients import init_clients
    from core.config import resolve_scholar_backend
    from research.collectors import collector_a, collector_b, collector_c
    from research.supervisor import supervisor
    from scope.nodes import write_brief

    abstract = Path(args.abstract_file).read_text(encoding="utf-8").strip() if args.abstract_file else DEFAULT_ABSTRACT
    if not any(s in args.only.upper() for s in "AB"):
        os.environ.setdefault("TAVILY_API_KEY", "unused-collector-c-only")   # C 만 돌릴 때는 Tavily 키를 묻지 않는다
    init_clients(model=args.model)
    print(f"[run] 실행 폴더: {paths.start_run()}")

    state = {"abstract": abstract, "user_requests": args.requests, "clarify_qna": "", "research_brief": ""}
    t0 = time.time()

    if args.brief_file:
        state["research_brief"] = Path(args.brief_file).read_text(encoding="utf-8").strip()
        print("=== Brief (file) ===\n" + state["research_brief"] + "\n")
    else:
        print("=== 1. Research Brief ===")
        state.update(write_brief(state))

    print("=== 2. Supervisor ===")
    state.update(supervisor(state))

    runners = {"A": collector_a, "B": collector_b, "C": collector_c}
    print(f"=== 3. Collectors {list(args.only.upper())}  (scholar backend: {resolve_scholar_backend()}) ===")
    for side in args.only.upper():
        if side not in runners:
            continue
        t1 = time.time()
        state.update(runners[side](state))
        print(f"  → Collector {side} 완료 ({time.time() - t1:.0f}s)\n")

    print("\n===== Research Summary =====")
    for side, cnt, cards, cov in (
        ("A", "collector_a_search_count", "background_cards", "collector_a_coverage"),
        ("B", "collector_b_search_count", "method_cards", "collector_b_coverage"),
        ("C", "collector_c_search_count", "arxiv_cards", "collector_c_coverage"),
    ):
        if side not in args.only.upper():
            continue
        selected = state.get(cards) or []
        print(f"Collector {side}: {state.get(cnt, 0)} rounds, {len(selected)} cards — {state.get(cov) or 'n/a'}")
        if side == "C" and selected:
            src: dict = {}
            for c in selected:
                src[c.get("abstract_source") or "?"] = src.get(c.get("abstract_source") or "?", 0) + 1
            print(f"    abstract sources: {src}")
        for c in selected[:3]:
            print(f"    [{c['id']}] rel {c['relevance']} · {c['year'] or 'n.d.'} · {c['title'][:70]}")
    print(f"total {time.time() - t0:.0f}s | files: {paths.research_dir()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
