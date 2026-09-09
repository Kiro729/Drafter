# -*- coding: utf-8 -*-
"""학술 검색 하이브리드(code/scholar.py) 검증. API 키 불필요.

Liner·OpenAlex·arXiv 는 모의 HTTP, LLM 은 모의 객체. 5번만 실제 OpenAlex 를 한 번 호출한다(네트워크 없으면 건너뜀).

    python tests/test_scholar.py

1. Liner 정규화(arXiv ID·DOI 추출, 저자, 연도), scholar endpoint, 429 → Retry-After 재시도, 401/402 오류
2. 초록 보강: 기본 설정(arXiv 만)에서는 외부 조회 없음 / OpenAlex 를 켰을 때의 체인(제목 불일치 거부, 재게재본 가드)
3. 소프트 연도 필터, 중복 제거, 디스패처(auto: 키 유무)
4. collector_c 전 경로 (Liner 백엔드) — 카드에 학술지·인용·근거 표시, PROMPT_CARDS_SCHOLAR 사용
5. OpenAlex 라이브 조회 1건 (선택 출처, 기본 꺼짐)
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
os.environ.pop("LINER_API_KEY", None)
os.environ.pop("SCHOLAR_BACKEND", None)

from core import clients
from core import config
import research.cards as research
import research.scholar as scholar
import research.search as search
import research.collectors as nodes_collector
from core.prompts import PROMPTS  # noqa: E402

from core import paths                  # noqa: E402
paths.start_run(ROOT / "tests" / "out", stamp="scholar")
OUT = paths.research_dir()
scholar.time.sleep = lambda s: None          # 429 재시도 대기 생략


def section(t):
    print("\n" + "=" * 12, t, "=" * 12)


class FakeResp:
    def __init__(self, status, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload


LINER_PAYLOAD = {
    "requestId": "req_1",
    "results": [
        {"title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762v7", "date": "2017-06-12",
         "citationCount": 120000, "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit"],
         "journal": "NeurIPS 2017", "description": "We propose a new simple network architecture, the Transformer."},
        {"title": "Attention Is All You Need (mirror)", "url": "https://arxiv.org/pdf/1706.03762", "date": "2017-06-12",
         "citationCount": 5, "authors": ["A. Vaswani"], "journal": "", "description": "dup"},
        {"title": "Serendipity in Recommender Systems: A Systematic Literature Review",
         "url": "https://doi.org/10.1007/s11390-020-0135-9", "date": "2021-03-01", "citationCount": 123,
         "authors": ["Reza Jafari Ziarani", "Reza Ravanmehr"], "journal": "Journal of Computer Science and Technology",
         "description": "A systematic review of serendipity."},
        {"title": "User Digital Twins for First-Person Serendipity Estimation", "url": "https://example.com/paper-a",
         "date": "2025-02-10", "citationCount": 3, "authors": ["Kim", "Lee"], "journal": "RecSys 2025",
         "description": "We estimate serendipity from the user's perspective using a digital twin."},
        {"title": "A Completely Different Paper About Fish", "url": "https://example.com/paper-b",
         "date": "2024-05-05", "citationCount": 0, "authors": ["Cho"], "journal": "",
         "description": "Snippet about fish that OpenAlex will mismatch."},
        {"title": "Old Classic on Novelty", "url": "https://example.com/classic", "date": "2005-01-01",
         "citationCount": 900, "authors": ["Herlocker"], "journal": "ACM TOIS", "description": "classic novelty metrics"},
    ],
    "totalCount": 6,
}

post_log, get_log = [], []


def make_fake_post(sequence):
    seq = list(sequence)

    def fake_post(url, *, headers, json, timeout):
        post_log.append((url, headers, json))
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return fake_post


def inv(text):
    d = {}
    for i, w in enumerate(text.split()):
        d.setdefault(w, []).append(i)
    return d


def fake_get(url, *, params=None, headers=None, timeout=20):
    get_log.append((url, params))
    if "openalex.org/works/https://doi.org/" in url:
        return FakeResp(200, {"title": "Serendipity in Recommender Systems: A Systematic Literature Review",
                              "doi": "https://doi.org/10.1007/s11390-020-0135-9", "publication_year": 2021,
                              "abstract_inverted_index": inv("Serendipity means unexpected relevant recommendations reviewed systematically"),
                              "cited_by_count": 130, "primary_location": {"source": {"display_name": "JCST"}}})
    if "openalex.org/works" in url:
        q = (params or {}).get("search", "")
        if q.startswith("User Digital Twins"):
            return FakeResp(200, {"results": [{"title": "User digital twins for first-person serendipity estimation",
                                               "doi": "https://doi.org/10.1145/999.888", "publication_year": 2025,
                                               "abstract_inverted_index": inv("We build a digital twin per user and estimate first person serendipity offline"),
                                               "cited_by_count": 4, "primary_location": {"source": {"display_name": "RecSys"}}}]})
        if q.startswith("A Completely Different"):
            return FakeResp(200, {"results": [{"title": "Totally Unrelated Ocean Biology Survey", "doi": None,
                                               "publication_year": 2020, "abstract_inverted_index": inv("fish fish fish"),
                                               "cited_by_count": 1, "primary_location": None}]})
        return FakeResp(200, {"results": []})
    if "semanticscholar" in url:
        raise AssertionError("S2 는 키가 없으면 호출되지 않아야 함")
    return FakeResp(404)


def fake_arxiv_by_ids(ids):
    assert ids == ["1706.03762"], ids
    return [SimpleNamespace(
        title="Attention Is All You Need", entry_id="http://arxiv.org/abs/1706.03762v7",
        authors=[SimpleNamespace(name="Ashish Vaswani"), SimpleNamespace(name="Noam Shazeer")],
        published=datetime(2017, 6, 12), categories=["cs.CL", "cs.LG"],
        summary="The dominant sequence transduction models are based on RNNs. We propose the Transformer.",
        get_short_id=lambda: "1706.03762v7")]


class FakeResponse:
    def __init__(self, c):
        self.content = c


class FakeChatModel:
    def __init__(self):
        self.calls = []

    def bind(self, **kw):
        return self

    def invoke(self, prompt):
        self.calls.append(prompt)
        if "Return only the queries, one per line." in prompt:
            assert "[Search engine note]" in prompt and "Liner" in prompt
            return FakeResponse("first-person serendipity evaluation in recommender systems\nuser digital twin recommendation\nnovelty diversity beyond accuracy metrics")
        if "Criteria for this channel" in prompt:
            return FakeResponse(json.dumps({"coverage": [
                {"criterion": "direct_relevance", "status": "covered", "cards": ["C-01"], "note": "ok"},
                {"criterion": "approach_diversity", "status": "covered", "cards": ["C-01", "C-02"], "note": "ok"},
                {"criterion": "recency", "status": "covered", "cards": ["C-02"], "note": "ok"}],
                "missing_topics": [], "followup_queries": [], "sufficient": True}))
        if "Card fields:" in prompt:
            assert "Papers (index, title, authors, year, venue, citations" in prompt          # PROMPT_CARDS_SCHOLAR
            assert "snippet only (no abstract available): Snippet about fish" in prompt
            assert "abstract (source: arxiv): The dominant sequence" in prompt
            assert "citations: 120000" in prompt and "venue: NeurIPS 2017" in prompt
            found = re.findall(r"^\[(\d+)\] title: (.*)$", prompt, re.MULTILINE)   # 순서가 바뀌므로 제목으로 판정
            cards = [{"index": int(i), "year": "", "approach": "transformer" if "Attention" in t else "survey",
                      "summary": f"논문 {i} 요지임.", "relevance": 0 if "Fish" in t else 4, "in_scope": True, "scope_note": "x"}
                     for i, t in found]
            return FakeResponse(json.dumps({"cards": cards}, ensure_ascii=False))
        raise AssertionError(prompt[:200])


def main():
    # ── 1 ───────────────────────────────────────────────────────────────────────
    section("1. Liner normalization, scholar endpoint, 429 retry, error codes")
    clients.liner_api_key = "test-key"
    scholar._http_post = make_fake_post([FakeResp(429, {}, headers={"Retry-After": "1"}), FakeResp(200, LINER_PAYLOAD)])
    res = scholar.liner_scholar_results("serendipity user perspective", max_results=15)
    assert len(post_log) == 2, "429 후 정확히 한 번 재시도해야 함"
    assert post_log[0][0] == "https://platform.liner.com/api/v1/tools/search/scholar", post_log[0][0]
    assert post_log[0][1]["x-api-key"] == "test-key" and post_log[0][2] == {"query": "serendipity user perspective", "max_results": 15}
    assert len(res) == 6
    a = res[0]
    assert a["arxiv_id"] == "1706.03762" and a["year"] == "2017" and a["citation_count"] == 120000
    assert a["authors"] == "Ashish Vaswani, Noam Shazeer, Niki Parmar 외" and a["journal"] == "NeurIPS 2017"
    assert res[2]["doi"] == "10.1007/s11390-020-0135-9" and res[2]["arxiv_id"] == ""
    assert all(r["abstract"] == "" and r["source"] == "liner" for r in res)
    for status, msg in ((401, "키가 거부"), (402, "크레딧 부족")):
        scholar._http_post = make_fake_post([FakeResp(status, {"error": "x"})])
        try:
            scholar.liner_scholar_results("q")
            raise AssertionError("LinerError 가 나야 함")
        except scholar.LinerError as exc:
            assert msg in str(exc), exc
    clients.liner_api_key = None
    try:
        scholar.liner_scholar_results("q")
        raise AssertionError
    except scholar.LinerError as exc:
        assert "LINER_API_KEY" in str(exc)
    clients.liner_api_key = "test-key"
    print("endpoint:", post_log[0][0])
    print("1 ok")

    # ── 2 ───────────────────────────────────────────────────────────────────────
    section("2. abstract enrichment")
    scholar._http_get = fake_get
    scholar._arxiv_by_ids = fake_arxiv_by_ids
    scholar._http_post = make_fake_post([FakeResp(200, LINER_PAYLOAD)])
    res = scholar.dedup_results(scholar.liner_scholar_results("q"))
    assert len(res) == 5 and sum(1 for r in res if r["arxiv_id"] == "1706.03762") == 1     # arXiv 중복(버전·pdf URL) 제거

    assert config.ABSTRACT_SOURCES == ("arxiv",), config.ABSTRACT_SOURCES
    get_log.clear()
    default_res = [dict(r) for r in res]
    scholar.enrich_abstracts(default_res)
    assert not get_log, f"기본 설정(arXiv 만)에서 외부 HTTP 조회가 있었음: {get_log[:2]}"
    srcs = {r["title"][:20]: r["abstract_source"] for r in default_res}
    assert srcs["Attention Is All You"] == "arxiv" and all(v == "snippet" for k, v in srcs.items() if k != "Attention Is All You"), srcs
    print("default (arxiv only):", srcs)

    scholar.enrich_abstracts(res, sources=("arxiv", "openalex", "semanticscholar"))
    by_title = {r["title"][:20]: r for r in res}
    assert by_title["Attention Is All You"]["abstract_source"] == "arxiv" and by_title["Attention Is All You"]["categories"] == "cs.CL, cs.LG"
    sr = by_title["Serendipity in Recom"]
    assert sr["abstract_source"] == "openalex" and sr["abstract"].startswith("Serendipity means") and sr["citation_count"] == 123
    tw = by_title["User Digital Twins f"]
    assert tw["abstract_source"] == "openalex" and tw["doi"] == "10.1145/999.888"          # 제목 매치 + 연도 일치 → DOI 보충
    assert by_title["A Completely Differe"]["abstract_source"] == "snippet"                # 제목 불일치 → 거부 → 스니펫
    reprint = {"title": "User Digital Twins for First-Person Serendipity Estimation", "doi": "", "year": "2019",
               "journal": "", "citation_count": None}
    found = scholar._openalex_lookup(reprint)
    assert found["abstract_source"] == "openalex" and "doi" not in found and "citation_count" not in found   # 연도 불일치 → 초록만
    print("with openalex enabled:", {k: v["abstract_source"] for k, v in by_title.items()})
    print("2 ok")

    # ── 3 ───────────────────────────────────────────────────────────────────────
    section("3. soft year filter, dispatcher")
    filtered = scholar.soft_year_filter(res, years_back=5, min_recent=2, max_results=4)
    years = [r["year"] for r in filtered]
    assert years[:2] == ["2025", "2024"], years          # 최근 5년 먼저
    assert len(filtered) == 4 and filtered[2]["citation_count"] == 120000 and filtered[3]["citation_count"] == 900
    assert len(scholar.soft_year_filter(res, years_back=5, min_recent=10, max_results=10)) == 5
    os.environ.pop("LINER_API_KEY", None)
    assert config.resolve_scholar_backend() == "arxiv"
    search._arxiv_run = lambda query, max_results: [SimpleNamespace(
        title="P", entry_id="http://arxiv.org/abs/2401.00001v1", authors=[SimpleNamespace(name="X")],
        published=datetime(2024, 1, 1), categories=["cs.IR"], summary="abs", get_short_id=lambda: "2401.00001v1")]
    out = scholar.scholar_search_results("q")
    assert out and out[0]["source"] == "arxiv" and out[0]["abstract_source"] == "arxiv" and "arXiv" in scholar.scholar_backend_note()
    os.environ["LINER_API_KEY"] = "test-key"
    clients.liner_api_key = "test-key"
    assert config.resolve_scholar_backend() == "liner" and "Liner" in scholar.scholar_backend_note()
    scholar._http_post = make_fake_post([FakeResp(200, LINER_PAYLOAD)])
    out = scholar.scholar_search_results("q", max_results=10)
    assert all(r["source"] == "liner" for r in out) and len(out) == 5 and all(r["abstract"] for r in out)
    print("dispatcher ok; liner results:", len(out))
    print("3 ok")

    # ── 4 ───────────────────────────────────────────────────────────────────────
    section("4. collector_c end-to-end on Liner backend")
    clients.llm = FakeChatModel()
    scholar._http_post = make_fake_post([FakeResp(200, LINER_PAYLOAD)])
    state = {"abstract": "세렌디피티",
             "research_brief": "RESEARCH QUESTION: first-person serendipity\nIN SCOPE: recsys\nOUT OF SCOPE: e-commerce\nKEY CONCEPTS: serendipity",
             "collector_c_prompt": "Find papers."}
    upd = nodes_collector.collector_c(state)
    cards, ev = upd["arxiv_cards"], upd["arxiv_data"]
    assert upd["collector_c_search_count"] == 1 and upd["is_c_sufficient"]
    assert all(c["channel"] == "scholar" and c["kind"] == "논문" for c in cards)
    assert "인용 120000" in ev and "NeurIPS 2017" in ev and "arXiv:1706.03762" in ev
    assert "DOI:10.1007/s11390-020-0135-9" in ev and "Journal of Computer Science and Technology" in ev
    assert "근거: 검색 스니펫" in ev
    assert not any("Fish" in c["title"] for c in cards)                       # relevance 0 → 제외
    assert not any("openalex" in c["abstract_source"] for c in cards)         # 기본 설정: arXiv 만
    assert cards[0]["citation_count"] == 120000                               # 관련도 같으면 인용 수 순
    assert "(학술 논문 (Liner 스콜라 + 초록 보강):" in ev
    w = PROMPTS["PROMPT_WRITER"].format(abstract="a", user_requests="u", research_brief="b", background_data="x", method_data="y", arxiv_data=ev)
    assert "학술 논문 카드(C-xx)만 인용한다" in w
    print(ev[:700] + "\n...")
    print("4 ok")

    # ── 5 ───────────────────────────────────────────────────────────────────────
    section("5. live OpenAlex lookup (network) — optional source, disabled by default")
    import importlib
    importlib.reload(scholar)
    try:
        found = scholar._openalex_lookup({"title": "Attention Is All You Need", "doi": "", "journal": "", "citation_count": None, "year": "2017"})
        print("openalex:", {k: (v[:80] if isinstance(v, str) else v) for k, v in (found or {}).items()})
        assert found and found.get("abstract"), found
        print("5 ok")
    except Exception as exc:  # noqa: BLE001
        print("5 SKIPPED (network):", type(exc).__name__, str(exc)[:120])

    os.environ.pop("LINER_API_KEY", None)
    print("\nALL SCHOLAR TESTS PASSED")


if __name__ == "__main__":
    main()
