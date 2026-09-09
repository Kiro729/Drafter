# -*- coding: utf-8 -*-
"""Drafter — 연구 초록 한 단락 → 국내 연구개발계획서 (마크다운 → PDF).

사용법
  1) API 키·모델: 이 파일 옆에 .env 를 만들어 적는다 (.env.example 참고). 환경변수로 줘도 된다.
       OPENAI_API_KEY   필수
       TAVILY_API_KEY   필수 (웹 검색)
       OPENAI_MODEL     선택 (LLM 모델. 없으면 gpt-5.1)
       LINER_API_KEY    선택 (학술 검색. 없으면 arXiv)
  2) 아래 ABSTRACT / REQUESTS / PDF_AUTHOR 를 고친다. 표지의 부제·키워드는 비워 두면 자동으로 만든다.
  3) python main.py
     Scope 단계에서 질문이 최대 3개 나온다: 자기 말로 답하거나, 참고 예시 번호를 치거나, Enter 로 건너뛴다.
     초록 수정안은 Enter 로 확정한다(직접 고치려면 초록 전체 입력). 그 뒤는 자동으로 끝까지 진행된다.

산출물
  runtime/<실행시각>/   research/ (브리프·카드·증거)   figures/ (도해)   pdf_build/ (조판 중간 파일)
  final/                research_paper_<실행시각>.md / .pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "code"))

from core import paths                                                      # noqa: E402
from core.clients import init_clients                                       # noqa: E402
from core.config import ENV_FILE, ENV_LOADED, MAX_REVIEW_ROUNDS             # noqa: E402
from core.graph import build_graph                                          # noqa: E402
from core.output import initial_state, save_research_paper_as_markdown      # noqa: E402
from finalize.export_pdf import export_pdf                                  # noqa: E402

_SCOPE_LOOP_NODES = {"scope", "clarify", "human_feedback", "revise_abstract", "write_brief", "human_abstract_feedback"}


def _drain(graph, cfg, inputs=None) -> None:
    """다음 인터럽트 또는 END 까지 그래프를 진행시키며 scope 루프 외 노드 완료를 로그."""
    for event in graph.stream(inputs, config=cfg):
        for node_name in event:
            if node_name in _SCOPE_LOOP_NODES or node_name.startswith("__"):      # __interrupt__ 같은 그래프 이벤트는 노드가 아니다
                continue
            print(f"  ✓ {node_name} 완료")
            if node_name == "supervisor":
                print("\n=== 2단계: 자료 수집 · 연구계획서 생성 시작 ===\n")
            elif node_name == "editor" and event[node_name] and event[node_name].get("review_passed"):
                print("\n=== 3단계: 심사 통과 → 도해 생성 · 최종 정리 ===\n")


def run(
    abstract: str,
    user_requests: str = "",
    *,
    clarify_answers: list = None,
    make_pdf: bool = True,
) -> dict:
    """초록과 추가 요청을 받아 전체 파이프라인을 끝까지 실행하고 최종 state 를 반환.

    clarify_answers: 확인 질문에 대한 답변 리스트 (질문 순서대로 소비). 각 항목은 자유 텍스트, 참고 예시 번호("1"/"2"/"3"),
        또는 "" (건너뜀). None 이면 콘솔 input() 으로 받는다. 초록 확정도 리스트가 있으면 Enter(수정안 확정)로 처리한다.
    make_pdf: 마크다운 저장 후 조판된 PDF 까지 생성할지 여부.
    """
    if ENV_LOADED:
        print(f"[env] {ENV_FILE.name} 에서 설정 {ENV_LOADED}개를 읽었습니다")
    init_clients()
    run_dir = paths.start_run()
    print(f"[run] 실행 폴더: {paths.relative_to_root(run_dir)}")

    graph = build_graph()
    cfg = {"configurable": {"thread_id": "research_plan_1"}}

    print("\n=== 1단계: Scope — 확인 질문 루프 ===")
    _drain(graph, cfg, initial_state(abstract, user_requests))

    # 인터럽트 루프: human_feedback(질의응답) 및 human_abstract_feedback(초록 확정) 처리
    answer_idx = 0
    while True:
        snapshot = graph.get_state(cfg)
        next_nodes = set(snapshot.next) if snapshot.next else set()

        if "human_feedback" in next_nodes:
            if clarify_answers is not None:
                ans = clarify_answers[answer_idx] if answer_idx < len(clarify_answers) else ""
            else:
                try:
                    ans = input("답변 (자기 말로 입력 · 참고 예시 번호 · Enter=건너뛰기): ")
                except EOFError:
                    ans = ""
            answer_idx += 1
            graph.update_state(cfg, {"current_answer": ans})
            _drain(graph, cfg)

        elif "human_abstract_feedback" in next_nodes:
            if clarify_answers is not None:
                ans = ""
            else:
                try:
                    ans = input("Enter=이 초록으로 확정 / 직접 고치려면 초록 전체 입력: ")
                except EOFError:
                    ans = ""
            graph.update_state(cfg, {"current_answer": ans})
            _drain(graph, cfg)

        else:
            break

    fv = graph.get_state(cfg).values
    md_path = save_research_paper_as_markdown(fv)

    pdf_path = None
    if make_pdf:
        print("\n=== 4단계: PDF 조판 ===")
        pdf_path = export_pdf(md_path, author=PDF_AUTHOR, keywords=PDF_KEYWORDS, subtitle=PDF_SUBTITLE)

    print("\n===== Run Summary =====")
    for name, cnt_key, cards_key, cov_key in (
        ("Collector A (Tavily)  ", "collector_a_search_count", "background_cards", "collector_a_coverage"),
        ("Collector B (Tavily)  ", "collector_b_search_count", "method_cards", "collector_b_coverage"),
        ("Collector C (scholar) ", "collector_c_search_count", "arxiv_cards", "collector_c_coverage"),
    ):
        print(f"{name}: {fv[cnt_key]} rounds, {len(fv.get(cards_key) or [])} cards selected — "
              f"{fv.get(cov_key) or 'coverage n/a'}")
    if fv.get("framework_figure_path"):
        print(f"Framework diagram     : {fv['framework_figure_path']}")
        if fv.get("diagram_checks"):
            print(f"Archify validation    : {fv['diagram_checks']} checks (repairs {fv.get('diagram_repair_rounds', 0)})")
    else:
        print("Framework diagram     : 생성 실패 — PDF 는 그림 없이 조판됨")
    print(f"Review rounds         : {fv['review_round']}")
    print(f"Writer rewrites       : {fv['rewrite_count']}")
    print(f"Format lint (writer)  : {fv.get('lint_writer') or 'n/a'}")
    print(f"Format lint (reporter): {fv.get('lint_reporter') or 'n/a'}")
    print(f"Reporter changes      : {fv.get('reporter_changes') or 'n/a'} vs review-passed text")
    print(f"Cover subtitle        : {PDF_SUBTITLE or fv.get('cover_subtitle') or 'n/a'}")
    print(f"Cover keywords        : {', '.join(PDF_KEYWORDS or fv.get('cover_keywords') or []) or 'n/a'}")
    print(f"References            : {fv.get('references_count', 0)} (generated from scholar cards)")
    print(f"Final verdict         : {'PASS' if fv['review_passed'] else f'max {MAX_REVIEW_ROUNDS} rounds'}")
    print(f"Runtime dir           : {paths.relative_to_root(run_dir)}")
    print(f"Markdown              : {paths.relative_to_root(md_path)}")
    print(f"PDF                   : {paths.relative_to_root(pdf_path) if pdf_path else '생성 안 함'}")
    return fv


# ── 실행할 초록과 추가 요청을 여기서 수정하세요 ────────────────────────────────────

ABSTRACT = """
추천 시스템(Recommender Systems, RS)은 희소성(sparsity)이나 노이즈(noise)와 같은 학습 데이터의 특성에 큰 영향을 받는다. 협업 필터링(Collaborative Filtering, CF)은 사용자-아이템 상호작용 행렬을 활용하여 추천을 수행하는 대표적인 추천 방법이다.
본 연구에서는 기존의 추천 모델과 달리, 생성자(generator)를 위한 정답(ground-truth) 음성 샘플을 생성하는 문제를 해결하기 위해 생성적 적대 신경망(Generative Adversarial Networks, GANs)과 그래프 오토인코더(Graph Autoencoders, GAEs)의 개념을 활용한 추천 프레임워크를 구축한다. 특히 Graph Generative Adversarial Recommendation(G2R)이라 불리는 GAN 기반 추천 모델에 초점을 맞춘다.
본 연구에서는 G2R 프레임워크의 핵심 단계 중 하나인 생성자의 증강 손실(augmented loss)을 학습하는 문제를 다룬다. 특히, 생성자를 위한 증강 손실을 어떻게 학습할 것인지에 초점을 맞춘다.
""".strip()

REQUESTS = ""

# PDF 표지 정보. 제목·작성일·그림은 결과물에서 자동으로 채워진다.
PDF_AUTHOR = "사용자01"
# 부제·키워드는 비워 두면 자동이다: 부제는 완성된 연구 요약을 읽고 LLM 이 한 문장으로 쓰고(cover 노드),
# 키워드는 Scope 단계 브리프가 초록에 맞춰 낸 한국어 핵심어를 쓴다. 직접 정하고 싶을 때만 채운다.
PDF_SUBTITLE = ""                 # 예: "MovieLens 로그 기반 디지털 트윈으로 세렌디피티를 오프라인에서 검증한다."
PDF_KEYWORDS: list = []           # 예: ["세렌디피티", "추천시스템", "오프라인 평가"]

if __name__ == "__main__":
    run(ABSTRACT, REQUESTS)
