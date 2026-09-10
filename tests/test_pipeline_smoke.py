# -*- coding: utf-8 -*-
"""전체 파이프라인 모의 실행: main.run() 을 모의 LLM·모의 검색으로 처음부터 끝까지 돌린다. API 키 불필요.

    python tests/test_pipeline_smoke.py

검증하는 것
- 그래프 연결과 두 인터럽트(질문 답변 · 초록 확정)를 main.run 의 루프가 처리한다
- Scope 질문 1개(예시 1번 채택) → 브리프 → supervisor → collector A/B/C 각 1라운드 → writer → 심사 1라운드 REVISE → 재작성
  → 심사 2라운드 PASS(라운드마다 심사 기록 저장) → 도해 → reporter(LLM 0회) → cover(부제 LLM 1회, 키워드는 브리프) → final 마크다운 저장. PDF 는 생략.
- 실행 폴더가 runtime/<시각>/ 대신 tests/out/pipeline/<시각>/ 에 생기고 research/ · figures/ 산출물이 그 안에 남는다.
  final 마크다운은 tests/out/pipeline/final/ 에 실행 폴더와 같은 시각 이름으로 저장된다. 프로젝트의 runtime/ · final/ 은 건드리지 않는다.
- 도해는 Node·Archify·Chromium 이 있으면 실제로 그리고(모의 스펙), 없으면 그림 없이 진행되는 경로를 확인한다.
"""
import functools
import json
import re
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "out" / "pipeline"
sys.path.insert(0, str(ROOT / "code"))
os.environ.setdefault("DRAFTER_SKIP_DOTENV", "1")      # 테스트는 프로젝트 .env(키·모델·백엔드)를 읽지 않는다
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

import main                                   # noqa: E402
import research.collectors as collectors      # noqa: E402
import review.nodes as review                 # noqa: E402
from core import clients, paths               # noqa: E402
from test_write_stage import make_doc         # noqa: E402

KNOWN_GOOD = json.loads((ROOT / "tests" / "fixtures" / "methodology.workflow.json").read_text(encoding="utf-8"))
ABSTRACT = "기존 추천 시스템 연구가 세렌디피티를 시스템 관점에서 평가해 온 것과 달리, 사용자 관점에서 세렌디피티를 판단하는 추천 방식을 제안한다."
PLAN_V1 = make_doc()
PLAN_V2 = make_doc(title="# 사용자 디지털 트윈 기반 일인칭 세렌디피티 추천 연구")     # 재작성본 (제목만 다름)
BRIEF_JSON = {
    "research_question": "MovieLens 로그로 만든 사용자 디지털 트윈으로 일인칭 세렌디피티를 오프라인에서 추정할 수 있는가",
    "problem": "기존 지표는 사용자의 기대 상태를 모델링하지 않음.", "solution": "디지털 트윈으로 즐거움과 의외성을 분리 추정함.",
    "alignment_note": "원인에 직접 개입함.", "scope_in": ["영화 추천", "오프라인 평가"], "scope_out": ["온라인 A/B 테스트"],
    "key_concepts_en": ["serendipity recommendation", "user digital twin", "MovieLens"],
    "keywords_ko": ["세렌디피티", "추천 시스템", "사용자 디지털 트윈", "MovieLens", "오프라인 평가"],
    "data_candidates": [{"name": "MovieLens 20M", "provider": "GroupLens", "form": "평점·타임스탬프", "scale": "", "status": "추정"}],
    "evaluation_candidates": {"task": "상위 k 추천 평가", "metrics": ["세렌디피티@k"], "baselines": ["item-kNN"]},
    "existing_approaches": ["시스템 관점 지표 계열"], "unresolved_reason": "개인의 내적 기대 상태를 재현하지 못함(추정).",
    "user_constraints": "없음", "assumptions": ["MovieLens 20M 규모는 확인되지 않음"], "unknowns": [],
}
SCHOLAR_RESULTS = [
    {"title": "A Comparative Analysis of Supportive Navigation on Movie Recommenders", "url": "http://arxiv.org/abs/2311.13494v1",
     "arxiv_id": "2311.13494", "authors": "M. S. Ali, M. M. Tariq, A. Ahmed 외", "year": "2023", "published": "2023-11-22",
     "journal": "", "citation_count": None, "doi": "", "abstract": "We compare navigation support in movie recommenders.", "abstract_source": "arxiv"},
    {"title": "Serendipity in Recommender Systems: A Systematic Literature Review", "url": "https://doi.org/10.1007/s11390-020-0135-9",
     "arxiv_id": "", "authors": "Reza Jafari Ziarani, Reza Ravanmehr", "year": "2021", "published": "2021-01-01",
     "journal": "Journal of Computer Science and Technology", "citation_count": 120, "doi": "10.1007/s11390-020-0135-9",
     "abstract": "A systematic review of serendipity definitions and metrics.", "abstract_source": "snippet"},
]


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """프롬프트의 고유 문구로 단계를 판별해 응답한다. Reviewer A 는 1라운드 REVISE, 2라운드 PASS."""

    def __init__(self):
        self.calls = []
        self.review_a_calls = 0

    def bind(self, **kwargs):
        return self

    def invoke(self, prompt):
        self.calls.append(prompt)
        return FakeResponse(self._reply(prompt))

    def _reply(self, p):
        if '"subtitle"' in p and "[연구 요약]" in p:                                    # finalize: 표지 부제
            return json.dumps({"subtitle": "사용자 디지털 트윈으로 일인칭 세렌디피티를 추정하고 오프라인에서 검증한다."}, ensure_ascii=False)
        if '"missing": [' in p and "[초록]" in p:                                     # scope: RESTATE
            return json.dumps({"problem": "P 재서술", "solution": "S 재서술", "missing": ["데이터 미정"], "note": "없음"}, ensure_ascii=False)
        if "[이번 질문의 초점" in p:                                                 # scope: CLARIFY (1개 뒤 종료)
            if "초점 — Problem]" in p:
                return json.dumps({"diagnosis": [{"gap": "데이터 미정", "impact": "모듈 1 입력이 달라짐"}], "selected_gap": "데이터 미정",
                                   "rationale": "설계를 가장 크게 바꿈", "question": "디지털 트윈을 학습할 로그는 무엇입니까?",
                                   "examples": ["MovieLens 20M", "Netflix Prize"], "dimension": "problem"}, ensure_ascii=False)
            return json.dumps({"question": None})
        if "Original Abstract:" in p:                                                 # scope: REVISE_ABSTRACT
            return "수정된 초록: MovieLens 로그 기반 사용자 디지털 트윈으로 일인칭 세렌디피티를 추정한다."
        if '"research_question"' in p and "[연구자와의 문답]" in p:                   # scope: BRIEF
            return json.dumps(BRIEF_JSON, ensure_ascii=False)
        if '"collector_a"' in p:                                                      # research: SUPERVISOR
            return json.dumps({"collector_a": "배경 지시", "collector_b": "방법 지시", "collector_c": "논문 지시"}, ensure_ascii=False)
        if "Return only the queries, one per line." in p:                              # research: 쿼리 생성
            if "scholarly search queries" in p:
                return "serendipity recommendation user modeling\nunexpectedness recommender\nbeyond accuracy evaluation"
            return "serendipity recommender limitations\nuser perspective serendipity\nrecommender diversity trends"
        if "Card fields:" in p:                                                       # research: 카드화
            indices = [int(x) for x in re.findall(r"^\[(\d+)\] title:", p, re.MULTILINE)]
            is_scholar = "Papers (index" in p
            years = re.findall(r"\| year: (\d{4})", p)
            cards = []
            for k, i in enumerate(indices):
                card = {"index": i, "year": years[k] if is_scholar and k < len(years) else "2023",
                        "summary": f"결과 {i}의 요지임. 방법과 한계를 서술함.", "relevance": 5 if i == 1 else 4,
                        "in_scope": True, "scope_note": "on topic"}
                if is_scholar:
                    card["approach"] = "matrix factorization + re-ranking"
                else:
                    card["kind"] = "기술문서"
                cards.append(card)
            return json.dumps({"cards": cards}, ensure_ascii=False)
        if "Criteria for this channel" in p:                                          # research: 갭 분석 → 충분
            return json.dumps({"coverage": [{"criterion": "background_context", "status": "covered", "cards": ["A-01"], "note": "ok"}],
                               "missing_topics": [], "followup_queries": [], "sufficient": True})
        if "[자동 검사 결과" in p:                                                    # write: 양식 수정 (호출되지 않아야 정상)
            return PLAN_V1
        if "[편집자 통합 피드백]" in p:                                                # write: 재작성
            return PLAN_V2
        if "[작성양식]" in p:                                                         # write: 초안
            return PLAN_V1
        if "Extract key claims" in p:                                                 # review: 검증 쿼리
            return "serendipity recommender limitations\nuser digital twin evaluation\nMovieLens dataset size"
        if "[Tavily 웹검색 결과]" in p:                                               # review: Reviewer A
            self.review_a_calls += 1
            verdict = "REVISE" if self.review_a_calls == 1 else "PASS"
            return f"VERDICT: {verdict}\nFEEDBACK:\n1. 위치: 1. 연구 배경 > 연구 필요성 / 문제: 근거가 약함 / 수정 방향: 카드 근거로 한정"
        if "AI 티가 나는 표현" in p:                                                  # review: Reviewer B
            return "VERDICT: PASS\nFEEDBACK:\n(지적 없음)"
        if "INTEGRATED_FEEDBACK:" in p:                                               # review: Editor
            verdict = "REVISE" if self.review_a_calls == 1 else "PASS"
            return f"FINAL_VERDICT: {verdict}\nINTEGRATED_FEEDBACK:\n## 1. 연구 배경 > 연구 필요성\n1. 위치: 불릿 1 / 문제: 근거가 약함 / 수정 방향: 카드 근거로 한정 / 출처: 내용(A)"
        if "허용 필드" in p:                                                          # finalize: Archify 스펙 작성
            return json.dumps({"caption_ko": "사용자 디지털 트윈 기반 세렌디피티 평가 흐름도", "spec": KNOWN_GOOD}, ensure_ascii=False)
        raise AssertionError("unexpected prompt: " + p[:300])


class FakeTavily:
    def __init__(self):
        self.calls = 0

    def search(self, query, **kwargs):
        self.calls += 1
        slug = re.sub(r"\W+", "-", query.lower())[:30]
        return {"answer": f"answer for {query}", "results": [
            {"title": f"Result {i} for {query}", "url": f"https://example.org/{slug}/{i}", "score": 0.9 - i * 0.1,
             "published_date": "2023-05-01", "content": f"snippet {i}", "raw_content": "본문 " * 100 + f"결과 {i}"}
            for i in range(1, 4)]}


def fake_scholar_search_results(query, *, max_results=None):
    return [dict(r) for r in SCHOLAR_RESULTS]


def section(t):
    print("\n" + "=" * 12, t, "=" * 12)


def main_test():
    # ── 준비: 실제 클라이언트·검색·경로를 모의로 바꾼다 ──────────────────────────────
    fake_llm, fake_tavily = FakeLLM(), FakeTavily()
    main.init_clients = lambda **kw: None
    clients.llm, clients.tavily, clients.arxiv_client = fake_llm, fake_tavily, None
    collectors.scholar_search_results = fake_scholar_search_results                     # Collector C
    review._arxiv_search_block = lambda q: "검색 결과 없음"                               # Reviewer A 의 arXiv 검증 검색
    paths.start_run = functools.partial(paths.start_run, OUT)                            # runtime/<시각> → tests/out/pipeline/<시각>
    main.save_research_paper_as_markdown = functools.partial(main.save_research_paper_as_markdown, output_dir=OUT / "final")
    before_runtime = sorted(p.name for p in (ROOT / "runtime").iterdir())
    before_final = sorted(p.name for p in (ROOT / "final").iterdir())

    # ── 실행 ────────────────────────────────────────────────────────────────────────
    section("main.run() end-to-end with mocks (clarify answer '1', abstract confirmed by Enter, no PDF)")
    fv = main.run(ABSTRACT, "", clarify_answers=["1"], make_pdf=False)

    # ── 검증 ────────────────────────────────────────────────────────────────────────
    section("assertions")
    run_dir = paths.run_dir()
    assert run_dir.parent == OUT, run_dir                                               # 실행 폴더 위치
    assert fv["clarify_round"] == 1 and "A1: MovieLens 20M" in fv["clarify_qna"]          # 질문 1개, 예시 1번 채택
    assert fv["abstract"].startswith("수정된 초록")                                       # Enter → 수정안 확정
    assert "KEY CONCEPTS: serendipity recommendation" in fv["research_brief"]             # 내부용 브리프
    assert (run_dir / "research" / "brief.md").exists()
    assert fv["collector_a_prompt"] == "배경 지시" and fv["collector_c_prompt"] == "논문 지시"
    for side, key in (("A", "background_cards"), ("B", "method_cards"), ("C", "arxiv_cards")):
        assert fv[f"collector_{side.lower()}_search_count"] == 1 and fv[key], side         # 각 1라운드, 카드 있음
        assert (run_dir / "research" / f"cards_{side}.json").exists() and (run_dir / "research" / f"evidence_{side}.md").exists()
    assert sorted(c["authors"].split(",")[0] for c in fv["arxiv_cards"]) == ["M. S. Ali", "Reza Jafari Ziarani"]
    assert fv["review_round"] == 2 and fv["rewrite_count"] == 1 and fv["review_passed"]    # 1라운드 REVISE → 재작성 → 2라운드 PASS
    for n in (1, 2):                                                                       # 라운드별 심사 기록
        assert (run_dir / "review" / f"round_{n}.md").exists() and (run_dir / "review" / f"plan_round_{n}.md").exists()
    r1 = (run_dir / "review" / "round_1.md").read_text(encoding="utf-8")
    assert "코드 판정: REVISE" in r1 and "근거가 약함" in r1                                  # 1라운드는 REVISE, A 의 지적 원문이 남는다
    assert "코드 판정: PASS" in (run_dir / "review" / "round_2.md").read_text(encoding="utf-8")
    assert (run_dir / "review" / "plan_round_1.md").read_text(encoding="utf-8").strip() == PLAN_V1.strip()   # 초안은 여기에만 남는다
    assert fv["review_a_passed"] and fv["review_b_passed"] and fake_llm.review_a_calls == 2
    assert fv["research_plan"].strip() == PLAN_V2.strip()                                 # 재작성본 채택
    assert fv["lint_writer"].endswith("(clean)") and fv["lint_reporter"].endswith("(clean)")
    assert not any("[자동 검사 결과" in c for c in fake_llm.calls)                         # 양식 수정 LLM 은 불필요했음
    assert fv["references_count"] == 2 and "## 참고문헌" in fv["research_paper"]
    assert "- Ali MS, Tariq MM, Ahmed A 외 (2023)." in fv["research_paper"]
    assert fv["reporter_changes"].startswith("0/") and "llm calls 0" in fv["reporter_changes"]
    assert fv["cover_subtitle"].startswith("사용자 디지털 트윈으로") and fv["cover_keywords"][:2] == ["세렌디피티", "추천 시스템"]

    if fv["framework_figure_path"]:
        assert fv["framework_figure_path"].startswith("tests/out/pipeline/") and (ROOT / fv["framework_figure_path"]).exists()
        assert fv["diagram_checks"] == "9/9" and (run_dir / "figures" / "framework.spec.json").exists()
        print("diagram: drawn ->", fv["framework_figure_path"])
    else:
        print("diagram: skipped (Archify/Node/Chromium unavailable) — pipeline continued without a figure")

    md_files = sorted((OUT / "final").glob("research_paper_*.md"))
    assert md_files and md_files[-1].name == f"research_paper_{run_dir.name}.md", md_files   # final 파일명 = 실행 폴더 시각
    front = md_files[-1].read_text(encoding="utf-8").split("---\n", 2)[1]
    assert f"run_dir: tests/out/pipeline/{run_dir.name}" in front and "final_verdict: PASS" in front
    assert "reporter_changes: 0/" in front and "references: 2" in front
    assert "subtitle: 사용자 디지털 트윈으로" in front and "keywords: 세렌디피티, 추천 시스템" in front   # 조판이 읽는 표지 메타
    assert not (OUT / "final" / f"research_paper_{run_dir.name}.pdf").exists()            # make_pdf=False

    assert sorted(p.name for p in (ROOT / "runtime").iterdir()) == before_runtime          # 프로젝트 runtime/ 불변
    assert sorted(p.name for p in (ROOT / "final").iterdir()) == before_final              # 프로젝트 final/ 불변

    print(f"LLM calls: {len(fake_llm.calls)} | Tavily calls: {fake_tavily.calls} | run dir: {run_dir.relative_to(ROOT)}")
    print("\nALL PIPELINE SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
