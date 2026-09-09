# -*- coding: utf-8 -*-
"""Research 단계(출처 카드 + 브리프 연결 + 갭 루프) 검증. API 키 불필요.

LLM·Tavily 는 모의 객체, arXiv 는 가짜 결과를 쓴다. 산출물은 tests/out/research/ 에 쓴다.

    python tests/test_research.py

1. parse_brief / 쿼리 정리 규칙
2. collector_a: Tavily 본문 → 카드 → 범위·관련도 필터 → 중복 제거 → 갭 루프(1회차 부족 → 2회차 충분)
3. collector_c: arXiv 경로(날짜 필터 시도 → 결과 부족 시 무필터 보충 → id 중복 제거) → 카드
4. LLM 카드화 실패 시 원문 발췌 폴백
5. writer / reporter 프롬프트가 새 증거 형식으로 포맷됨, 그래프 컴파일
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
os.environ.setdefault("DRAFTER_SKIP_DOTENV", "1")      # 테스트는 프로젝트 .env(키·모델·백엔드)를 읽지 않는다
os.environ.pop("LINER_API_KEY", None)        # 이 테스트는 arXiv 경로를 검증한다
os.environ.pop("SCHOLAR_BACKEND", None)

from core import clients
import research.cards as research
import research.search as search
import research.collectors as nodes_collector
from core.prompts import PROMPTS  # noqa: E402

from core import paths                  # noqa: E402
paths.start_run(ROOT / "tests" / "out", stamp="research")
OUT = paths.research_dir()

BRIEF = """RESEARCH QUESTION: How can serendipity in movie recommendation be estimated from the user's own
first-person perspective using a probabilistic user digital twin built from MovieLens logs?
IN SCOPE: first-person serendipity, user digital twin, surprise and enjoyment modeling, MovieLens offline evaluation
OUT OF SCOPE: online A/B testing with real users, e-commerce product recommendation, music streaming
KEY CONCEPTS: serendipity recommendation, user digital twin, unexpectedness, offline evaluation, MovieLens, probabilistic preference model
USER CONSTRAINTS: none
ASSUMPTIONS: MovieLens-25M is the primary dataset"""
ABSTRACT = "사용자의 관점에서 세렌디피티를 판단하는 추천 방식을 제안한다."


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeChatModel:
    """프롬프트의 고유 문구로 어느 단계인지 판별해 알맞은 응답을 돌려준다. 호출 기록을 남긴다."""

    def __init__(self):
        self.calls = []
        self.bad_cards_for_query = None       # 이 쿼리의 카드화 응답은 깨진 JSON 으로

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    def invoke(self, prompt):
        self.calls.append(prompt)
        if "Return only the queries, one per line." in prompt:
            if "Gap analysis of the previous round" in prompt:
                return FakeResponse("1. serendipity metric definition survey\n2. \"digital twin evaluation protocol\"\n3. novelty diversity accuracy tradeoff")
            if "scholarly search queries" in prompt:
                return FakeResponse("serendipity recommendation user modeling\nunexpectedness recommender probabilistic\nrecommender offline evaluation beyond accuracy")
            return FakeResponse("- serendipity recommender systems limitations\n- user perspective serendipity evaluation\n- recommender diversity trends industry")
        if "Criteria for this channel" in prompt:
            return self._gap(prompt)
        if "Card fields:" in prompt:
            m = re.search(r"Search query that produced these results: (.*)", prompt)
            query = m.group(1).strip() if m else ""
            if self.bad_cards_for_query and query == self.bad_cards_for_query:
                return FakeResponse("Sorry, here are the cards: not json at all")
            indices = [int(x) for x in re.findall(r"^\[(\d+)\] title:", prompt, re.MULTILINE)]
            is_scholar = "Papers (index" in prompt
            cards = []
            for i in indices:
                card = {"index": i, "year": "2023" if i % 2 else "2020",
                        "summary": f"결과 {i}의 요지임. 방법과 한계를 서술함. 지표는 nDCG@10 을 사용함.",
                        "relevance": 5 if i == 1 else (1 if i == 3 else 4),
                        "in_scope": i != 2, "scope_note": "out of scope: e-commerce" if i == 2 else "on topic"}
                if is_scholar:
                    card["approach"] = "matrix factorization + re-ranking" if i % 2 else "LLM user simulator"
                else:
                    card["kind"] = "기술문서" if i % 2 else "기사"
                cards.append(card)
            return FakeResponse(json.dumps({"cards": cards}, ensure_ascii=False))
        raise AssertionError("unexpected prompt: " + prompt[:300])

    def _gap(self, prompt):
        round_no = int(re.search(r"Round (\d+) of", prompt).group(1))
        if round_no == 1:
            return FakeResponse(json.dumps({
                "coverage": [
                    {"criterion": "background_context", "status": "covered", "cards": ["A-01"], "note": "ok"},
                    {"criterion": "existing_limitations", "status": "partial", "cards": ["A-04"], "note": "single source"},
                    {"criterion": "prior_work_trends", "status": "missing", "cards": [], "note": "no trend evidence"},
                ],
                "missing_topics": ["industry trend toward beyond-accuracy metrics", "named limitations of accuracy-centric recommenders"],
                "followup_queries": ["beyond accuracy recommender metrics trend", "serendipity metric limitations survey"],
                "sufficient": False}))
        return FakeResponse(json.dumps({
            "coverage": [
                {"criterion": "background_context", "status": "covered", "cards": ["A-01"], "note": "ok"},
                {"criterion": "existing_limitations", "status": "covered", "cards": ["A-04", "A-09"], "note": "ok"},
                {"criterion": "prior_work_trends", "status": "covered", "cards": ["A-07"], "note": "ok"},
            ],
            "missing_topics": [], "followup_queries": [], "sufficient": True}))


class FakeTavily:
    def __init__(self):
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        slug = re.sub(r"\W+", "-", query.lower())[:30]
        results = []
        for i in range(1, 6):
            url = f"https://example.org/{slug}/{i}"
            if i == 5:
                url = "https://example.org/shared-page?utm_source=x"      # 모든 쿼리에 공통 → 중복 제거 대상
            results.append({
                "title": f"Result {i} for {query}", "url": url, "score": 0.9 - i * 0.1,
                "published_date": "2023-05-01" if i % 2 else None,
                "content": f"snippet {i}", "raw_content": ("본문 " * 200 + f"결과 {i}") if i != 4 else "",
            })
        return {"results": results}


arxiv_calls = []


def fake_arxiv_run(query, max_results):
    """search._arxiv_run 대체. 날짜 필터 쿼리에는 2편만(부족) → 무필터 보충이 일어나게 한다."""
    arxiv_calls.append(query)
    n = 2 if "submittedDate" in query else 6
    out = []
    for i in range(1, n + 1):
        sid = f"2301.0000{i}"
        out.append(SimpleNamespace(
            title=f"Paper {i}: {query[:20]}", entry_id=f"http://arxiv.org/abs/{sid}v2",
            authors=[SimpleNamespace(name=f"Author{i}A"), SimpleNamespace(name=f"Author{i}B"),
                     SimpleNamespace(name="C"), SimpleNamespace(name="D")],
            published=datetime(2020 + i % 5, 1, 1), categories=["cs.IR", "cs.LG"],
            summary=f"Abstract of paper {i}. " * 20, get_short_id=lambda sid=sid: sid + "v2",
        ))
    return out


def section(t):
    print("\n" + "=" * 12, t, "=" * 12)


def main():
    # ── 0 ───────────────────────────────────────────────────────────────────────
    section("0. arXiv request gate: 4s spacing, 429 → 5min wait → one retry → give up (no real requests)")
    real_sleep = search.time.sleep
    sleeps, calls = [], []
    search.time.sleep = lambda s: sleeps.append(s)
    search._ARXIV_GATE.update({"min_interval": 4.0, "wait_after_429": 300.0, "last_request": 0.0, "disabled": False})
    assert search.arxiv_call(lambda: calls.append(1) or "ok") == "ok"
    search.arxiv_call(lambda: calls.append(2) or "ok")
    assert len(calls) == 2 and sleeps and 3.5 <= sleeps[-1] <= 4.0, sleeps          # 두 번째 요청 전 4초 간격 대기

    class Fake429(Exception):
        status = 429

    hits = []

    def once_429_then_ok():
        hits.append(1)
        if len(hits) == 1:
            raise Fake429("Page request resulted in HTTP 429")
        return "ok-after-wait"

    sleeps.clear()
    assert search.arxiv_call(once_429_then_ok) == "ok-after-wait"                   # 첫 429 → 5분 대기 → 재시도 성공
    assert 300.0 in sleeps and len(hits) == 2 and search._ARXIV_GATE["disabled"] is False

    def always_429():
        calls.append("429")
        raise Fake429("Page request resulted in HTTP 429")

    n_before = calls.count("429")
    try:
        search.arxiv_call(always_429)
        raise AssertionError("ArxivRateLimited 가 나야 함")
    except search.ArxivRateLimited as exc:
        assert "이번 실행에서 arXiv 중단" in str(exc)
    assert calls.count("429") == n_before + 2 and search._ARXIV_GATE["disabled"] is True   # 정확히 2회 시도 후 포기
    n = len(calls)
    try:
        search.arxiv_call(lambda: calls.append("must-not-run"))
        raise AssertionError
    except search.ArxivRateLimited as exc:
        assert "보내지 않습니다" in str(exc)
    assert len(calls) == n                                                          # 중단 뒤엔 요청 자체를 안 보냄
    # 중단 상태에서는 날짜 필터 → 무필터 보충도 시도하지 않는다
    try:
        search.arxiv_search_results("q")
        raise AssertionError
    except search.ArxivRateLimited:
        pass
    search._ARXIV_GATE["disabled"] = False
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("boom")
        return "ok"

    assert search.arxiv_call(flaky) == "ok" and len(attempts) == 2                  # 429 아닌 오류는 1회 재시도
    search.time.sleep = real_sleep
    print("gate ok: spacing", round(sleeps[0], 1) if sleeps else None, "| 429 wait 300s once | calls", calls)

    # ── 1 ───────────────────────────────────────────────────────────────────────
    section("1. parse_brief / query cleaning")
    f = research.parse_brief(BRIEF)
    assert f["RESEARCH QUESTION"].startswith("How can serendipity") and "MovieLens logs?" in f["RESEARCH QUESTION"]
    assert f["OUT OF SCOPE"].startswith("online A/B testing")
    assert f["ASSUMPTIONS"] == "MovieLens-25M is the primary dataset"
    bs = research.brief_section(BRIEF)
    assert "USER CONSTRAINTS" not in bs and "OUT OF SCOPE: online" in bs
    assert research.parse_brief("free text brief")["RESEARCH QUESTION"] == "free text brief"
    clients.llm = FakeChatModel()
    qs = search._generate_queries("x {gap} Return only the queries, one per line.", n=3, gap="Gap analysis of the previous round")
    assert qs == ["serendipity metric definition survey", "digital twin evaluation protocol", "novelty diversity accuracy tradeoff"], qs
    print("brief fields ok; cleaned queries:", qs)

    # ── 2 ───────────────────────────────────────────────────────────────────────
    section("2. collector_a with fake Tavily (gap loop: round1 insufficient → round2 sufficient)")
    clients.llm = FakeChatModel()
    clients.tavily = FakeTavily()
    state = {"abstract": ABSTRACT, "research_brief": BRIEF, "collector_a_prompt": "Collect background on serendipity."}
    upd = nodes_collector.collector_a(state)
    cards = upd["background_cards"]
    print("rounds:", upd["collector_a_search_count"], "| sufficient:", upd["is_a_sufficient"], "| selected:", len(cards))
    print("coverage:", upd["collector_a_coverage"])
    assert upd["collector_a_search_count"] == 2 and upd["is_a_sufficient"] is True
    assert upd["collector_a_coverage"].startswith("covered 3 / partial 0 / missing 0")
    _, kw0 = clients.tavily.calls[0]
    assert kw0["include_raw_content"] is True and kw0["search_depth"] == "advanced" and kw0["max_results"] == 5
    assert len(clients.tavily.calls) == 6                                     # 2 라운드 × 3 쿼리
    assert all(c["in_scope"] and c["relevance"] >= 2 for c in cards)         # 범위 밖·저관련 제외
    assert not any(c["title"].startswith(("Result 2 ", "Result 3 ")) for c in cards)
    assert len([c for c in cards if "shared-page" in c["url"]]) == 1          # URL 중복 제거 (utm 무시)
    r4 = [c for c in cards if c["title"].startswith("Result 4 ")]
    assert r4 and r4[0]["excerpt"].startswith("snippet 4")                  # 본문 없으면 발췌로 카드화
    round2 = [p for p in clients.llm.calls if "Return only the queries" in p][1]
    assert "Gap analysis of the previous round" in round2
    assert "prior_work_trends: MISSING" in round2 and "existing_limitations: PARTIAL" in round2
    assert "Missing topics: industry trend" in round2 and "Suggested queries: beyond accuracy" in round2
    assert "- serendipity recommender systems limitations" in round2         # used_queries
    for p in clients.llm.calls:
        assert "OUT OF SCOPE: online A/B testing" in p                        # 브리프가 모든 프롬프트에
    ev = upd["background_data"]
    assert ev.startswith("(연구배경 (Tavily): 출처 카드") and "[A-01]" in ev and "관련도 5/5" in ev and "요지:" in ev
    assert len(ev) <= 12000
    saved = json.loads((OUT / "cards_A.json").read_text(encoding="utf-8"))
    assert saved["selected_ids"] == [c["id"] for c in cards] and saved["queries_by_round"]["2"]
    assert (OUT / "evidence_A.md").exists()
    assert len(clients.llm.calls) == 2 * (1 + 3 + 1)                          # 라운드당 쿼리 1 + 카드 3 + 갭 1
    print("cards_A.json: all", len(saved["cards"]), "selected", len(saved["selected_ids"]), "| LLM calls:", len(clients.llm.calls))
    print("2 ok")

    # ── 3 ───────────────────────────────────────────────────────────────────────
    section("3. collector_c on arXiv path (date filter → fallback → dedup)")
    clients.llm = FakeChatModel()
    arxiv_calls.clear()
    search._arxiv_run = fake_arxiv_run
    upd_c = nodes_collector.collector_c({**state, "collector_c_prompt": "Find papers on serendipity."})
    cards_c = upd_c["arxiv_cards"]
    print("rounds:", upd_c["collector_c_search_count"], "| selected:", len(cards_c), "| arxiv calls:", len(arxiv_calls))
    assert any("submittedDate:[" in q and "AND" in q for q in arxiv_calls)    # 날짜 필터 시도
    assert any("submittedDate" not in q for q in arxiv_calls)                 # 결과 부족 → 무필터 보충
    assert all(c["arxiv_id"] and not c["arxiv_id"].endswith("v2") for c in cards_c)
    assert len({c["arxiv_id"] for c in cards_c}) == len(cards_c)
    assert all(c["authors"].endswith(" 외") for c in cards_c)
    evc = upd_c["arxiv_data"]
    assert "arXiv:2301.0000" in evc and "접근: " in evc and "(Author1A, Author1B, C 외, 202" in evc
    print("3 ok")

    # ── 4 ───────────────────────────────────────────────────────────────────────
    section("4. LLM card failure → excerpt fallback keeps the round alive")
    clients.llm = FakeChatModel()
    clients.llm.bad_cards_for_query = "user perspective serendipity evaluation"
    clients.tavily = FakeTavily()
    upd4 = nodes_collector.collector_a(state)
    fallback = [c for c in upd4["background_cards"] if c["scope_note"].startswith("LLM 카드화 실패")]
    assert fallback and all(c["relevance"] == 2 for c in fallback)
    print("fallback cards:", len(fallback), "| total selected:", len(upd4["background_cards"]))
    print("4 ok")

    # ── 5 ───────────────────────────────────────────────────────────────────────
    section("5. downstream prompts accept the evidence; graph compiles")
    w = PROMPTS["PROMPT_WRITER"].format(abstract=ABSTRACT, user_requests="없음", research_brief=BRIEF,
                                        background_data=ev, method_data=ev, arxiv_data=evc)
    assert "[증거 읽는 법]" in w and "[A-01]" in w and "arXiv:2301" in w
    # Reporter 에는 정리 프롬프트가 없다 (09-09: 코드 표기 정리 + 위반 수정 루프만). 수정 프롬프트는 위반 목록만 받는다.
    assert "PROMPT_REPORTER" not in PROMPTS
    r = PROMPTS["PROMPT_WRITER_LINT_FIX"].format(research_plan="plan", lint_report="report")
    assert "지목된 위반만 고치십시오" in r and "{background_data}" not in r and "참고문헌 항목은 쓰지 않는다" in r
    from core import graph
    g = graph.build_graph()
    print("writer prompt:", len(w), "chars | graph nodes:", len(g.get_graph().nodes))
    print("5 ok")

    print("\nALL RESEARCH TESTS PASSED  (outputs:", OUT, ")")


if __name__ == "__main__":
    main()
