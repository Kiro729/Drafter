# -*- coding: utf-8 -*-
"""Collector A / B / C 노드 (병렬 실행, 출처 카드 파이프라인 + 갭 분석 루프).

라운드마다:
  1) 쿼리 생성   — 브리프(IN/OUT OF SCOPE, KEY CONCEPTS) + supervisor 지시문 + 이전 라운드 갭 분석
  2) 검색        — Tavily(본문 포함) 또는 arXiv(전체 초록, 최근 N년 우선)
  3) 카드화      — 쿼리당 LLM 1회: 요지·종류·연도·관련도·범위 판정
  4) 선별        — 중복 제거 → 범위 안·관련도 기준 이상 → 관련도순 상위 N장(글자 예산 안)
  5) 갭 분석     — LLM 1회: 채널 기준별 covered/partial/missing, 빠진 주제, 후속 쿼리 → 충분하면 종료
결과는 렌더링된 증거 텍스트(background_data 등)와 카드 목록으로 state 에 올라가고
runtime/<실행>/research/ 에 JSON·마크다운으로 남는다.
"""
from __future__ import annotations

from typing import Callable, Dict, List

from core.config import EVIDENCE_TOP_N, MAX_SEARCH, MIN_RELEVANCE, QUERIES_PER_ROUND, resolve_scholar_backend
from core.prompts import PROMPTS
from research.cards import (
    SourceCard,
    brief_section,
    coverage_summary,
    dedup_cards,
    gap_analysis,
    gap_section,
    make_cards,
    render_evidence,
    save_research_artifacts,
    select_cards,
)
from research.scholar import scholar_backend_note, scholar_search_results
from research.search import _generate_queries, tavily_search_results
from core.state import ResearchPlanState

from langchain_core.messages import AIMessage


def _run_collector(
    state: ResearchPlanState,
    *,
    side: str,
    channel: str,
    purpose: str,
    query_prompt_id: str,
    eval_prompt_id: str,
    collector_prompt_key: str,
    data_key: str,
    cards_key: str,
    count_key: str,
    sufficient_key: str,
    coverage_key: str,
    msg_name: str,
    label: str,
    fetch_fn: Callable[[str], list],
) -> ResearchPlanState:
    """Collector 공통 실행 로직 (A/B/C 모두 이 함수를 호출)."""
    brief = state.get("research_brief") or ""
    abstract = state["abstract"]
    collector_prompt = state.get(collector_prompt_key) or "(no supervisor instructions — follow the brief)"
    top_n = EVIDENCE_TOP_N.get(side, 12)

    all_cards: List[SourceCard] = []
    selected: List[SourceCard] = []
    gap: Dict | None = None
    used_queries: List[str] = []
    queries_by_round: Dict[int, List[str]] = {}
    count = 0
    sufficient = False

    while count < MAX_SEARCH:
        count += 1
        print(f"[Collector {side}] {label} 수집 중... ({count}/{MAX_SEARCH} 라운드)")

        try:
            queries = _generate_queries(
                PROMPTS[query_prompt_id],
                n=QUERIES_PER_ROUND,
                n_queries=QUERIES_PER_ROUND,
                brief_section=brief_section(brief),
                collector_prompt=collector_prompt,
                abstract=abstract,
                gap_section=gap_section(gap),
                used_queries="\n".join(f"- {q}" for q in used_queries) or "(none)",
                backend_note=scholar_backend_note() if channel == "scholar" else "",
            )
        except Exception as exc:  # noqa: BLE001 - 쿼리 생성 실패는 라운드 건너뜀
            print(f"  [Collector {side}] 쿼리 생성 실패: {exc}")
            queries = []
        queries = [q for q in queries if q.lower() not in {u.lower() for u in used_queries}]
        if not queries:
            print(f"  [Collector {side}] 새 쿼리가 없어 라운드를 마칩니다.")
            count -= 1          # 실행되지 않은 라운드는 세지 않는다
            break
        used_queries.extend(queries)
        queries_by_round[count] = queries

        print(f"  [Collector {side}] 검색 쿼리:")
        for i, q in enumerate(queries, 1):
            print(f"    {i}. {q}")

        for q in queries:
            try:
                results = fetch_fn(q)
            except Exception as exc:  # noqa: BLE001 - 검색 실패는 해당 쿼리만 건너뜀
                print(f"    '{q[:50]}' → 검색 실패: {type(exc).__name__}: {str(exc)[:100]}")
                continue
            cards = make_cards(
                results, channel=channel, side=side, purpose=purpose, brief=brief,
                query=q, round_no=count, id_start=len(all_cards) + 1,
            )
            all_cards.extend(cards)
            usable = sum(1 for c in cards if c.in_scope and c.relevance >= MIN_RELEVANCE)
            print(f"    '{q[:50]}' → 결과 {len(results)}건 → 카드 {len(cards)}장 (채택 가능 {usable})")

        all_cards = dedup_cards(all_cards)
        selected = select_cards(all_cards, top_n=top_n)
        print(f"  [Collector {side}] 누적 카드 {len(all_cards)}장 → 선별 {len(selected)}장")

        gap = gap_analysis(
            selected, eval_prompt_id=eval_prompt_id, brief=brief, abstract=abstract,
            round_no=count, max_rounds=MAX_SEARCH,
        )
        sufficient = gap["sufficient"]
        summary = coverage_summary(gap)
        if sufficient:
            print(f"  [Collector {side}] 갭 분석: 충분 → 종료 ({summary})")
            break
        if count < MAX_SEARCH:
            print(f"  [Collector {side}] 갭 분석: 부족 → 다음 라운드 ({summary})")
            if gap.get("missing_topics"):
                print(f"    빠진 주제: {'; '.join(gap['missing_topics'])[:200]}")
        else:
            print(f"  [Collector {side}] 갭 분석: 부족하지만 한도 도달 → 종료 ({summary})")

    evidence = render_evidence(selected, label)
    paths = save_research_artifacts(
        side, all_cards=all_cards, selected=selected, gap=gap,
        evidence=evidence, queries_by_round=queries_by_round,
    )
    print(f"  [Collector {side}] 저장: {paths['json']}")

    return {
        data_key: evidence,
        cards_key: [c.to_dict() for c in selected],
        count_key: count,
        sufficient_key: sufficient,
        coverage_key: coverage_summary(gap),
        "messages": [AIMessage(content=evidence[-2000:], name=msg_name)],
    }


def collector_a(state: ResearchPlanState) -> ResearchPlanState:
    return _run_collector(
        state,
        side="A",
        channel="web",
        purpose=("Research background: the context and motivation for this research, "
                 "limitations of existing approaches, and relevant prior work or technology trends."),
        query_prompt_id="PROMPT_COLLECTOR_A_QUERY",
        eval_prompt_id="PROMPT_EVALUATE_A",
        collector_prompt_key="collector_a_prompt",
        data_key="background_data",
        cards_key="background_cards",
        count_key="collector_a_search_count",
        sufficient_key="is_a_sufficient",
        coverage_key="collector_a_coverage",
        msg_name="collector_a",
        label="연구배경 (Tavily)",
        fetch_fn=tavily_search_results,
    )


def collector_b(state: ResearchPlanState) -> ResearchPlanState:
    return _run_collector(
        state,
        side="B",
        channel="web",
        purpose=("Methodology, experimental design and validation: concrete methods or algorithms, "
                 "experimental protocols, evaluation metrics, validation approaches and comparison baselines."),
        query_prompt_id="PROMPT_COLLECTOR_B_QUERY",
        eval_prompt_id="PROMPT_EVALUATE_B",
        collector_prompt_key="collector_b_prompt",
        data_key="method_data",
        cards_key="method_cards",
        count_key="collector_b_search_count",
        sufficient_key="is_b_sufficient",
        coverage_key="collector_b_coverage",
        msg_name="collector_b",
        label="방법론·실험·검증 (Tavily)",
        fetch_fn=tavily_search_results,
    )


def collector_c(state: ResearchPlanState) -> ResearchPlanState:
    backend = resolve_scholar_backend()
    return _run_collector(
        state,
        side="C",
        channel="scholar",
        purpose=("Academic papers directly related to the research question: prior approaches, "
                 "their methods and results, and recent work within the last five years."),
        query_prompt_id="PROMPT_COLLECTOR_C_QUERY",
        eval_prompt_id="PROMPT_EVALUATE_C",
        collector_prompt_key="collector_c_prompt",
        data_key="arxiv_data",
        cards_key="arxiv_cards",
        count_key="collector_c_search_count",
        sufficient_key="is_c_sufficient",
        coverage_key="collector_c_coverage",
        msg_name="collector_c",
        label="학술 논문 (Liner 스콜라 + 초록 보강)" if backend == "liner" else "학술 논문 (arXiv)",
        fetch_fn=scholar_search_results,
    )
