# -*- coding: utf-8 -*-
"""검색 백엔드 헬퍼 및 LLM 쿼리 생성 유틸리티.

노드 함수들이 공통으로 사용하는 검색·생성 함수를 모아둔 모듈.
clients 모듈의 전역 객체를 참조할 때는 반드시 `import clients; clients.llm`
형태로 사용해야 init_clients() 이후의 최신 값을 얻을 수 있다.

두 계층이 있다.
  * tavily_search_results / arxiv_search_results — 결과를 dict 목록으로 돌려준다(본문·전체 초록 포함).
    Collector 의 출처 카드 파이프라인(research/cards.py)이 쓴다.
  * _tavily_search_block / _arxiv_search_block — 결과를 짧은 텍스트 블록으로 직렬화한다.
    Reviewer 의 주장 검증 검색이 쓴다(변경 없음).
"""
from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any, Callable, Dict, List

import arxiv as arxiv_lib

from core import clients
from core.config import (
    ARXIV_429_WAIT,
    ARXIV_MAX_RESULTS,
    ARXIV_MIN_BEFORE_FALLBACK,
    ARXIV_MIN_INTERVAL,
    ARXIV_YEARS_BACK,
    QUERIES_PER_ROUND,
    RAW_CONTENT_CHAR_LIMIT,
    TAVILY_MAX_RESULTS,
    TAVILY_SEARCH_DEPTH,
)


# ── Tavily ─────────────────────────────────────────────────────────────────────

def tavily_search_results(
    query: str,
    *,
    max_results: int = TAVILY_MAX_RESULTS,
    search_depth: str = TAVILY_SEARCH_DEPTH,
    raw_content_limit: int = RAW_CONTENT_CHAR_LIMIT,
) -> List[Dict[str, Any]]:
    """Tavily 검색 1건 → 결과별 dict (title, url, published_date, content(본문), snippet).

    include_raw_content 로 페이지 본문을 받고, 본문이 비어 있으면 Tavily 의 발췌(content)를 쓴다.
    """
    resp = clients.tavily.search(
        query=query,
        max_results=max_results,
        search_depth=search_depth,
        include_raw_content=True,
        include_answer=False,
    )
    out: List[Dict[str, Any]] = []
    for r in resp.get("results", []) or []:
        raw = r.get("raw_content") or ""
        snippet = r.get("content") or ""
        content = raw if raw.strip() else snippet
        out.append({
            "title": " ".join(str(r.get("title") or r.get("url") or "").split()),
            "url": r.get("url", ""),
            "published_date": r.get("published_date") or "",
            "score": r.get("score"),
            "content": " ".join(content.split())[:raw_content_limit],
            "snippet": " ".join(snippet.split())[:500],
        })
    return out


def _tavily_search_block(query: str, max_results: int = 3) -> str:
    """Tavily 검색 1건을 '쿼리/요약/출처' 텍스트 블록으로 직렬화. (Reviewer 용)"""
    results = clients.tavily.search(
        query=query, max_results=max_results, include_answer=True
    )
    answer = results.get("answer", "")
    sources = [r["url"] for r in results["results"]]
    return f"쿼리: {query}\n요약: {answer}\n출처: {', '.join(sources)}"


# ── arXiv 요청 관문: 속도 제한 + 429 쿨다운 ─────────────────────────────────────

class ArxivRateLimited(RuntimeError):
    """arXiv 429 가 재시도에서도 반복되어 요청을 포기했거나, 그 뒤라서 요청을 보내지 않았다."""


_ARXIV_GATE: Dict[str, Any] = {
    "min_interval": float(ARXIV_MIN_INTERVAL),   # 요청 간 최소 간격 (초)
    "wait_after_429": float(ARXIV_429_WAIT),     # 첫 429 뒤 재시도 전 대기 (초)
    "last_request": 0.0,                         # time.monotonic() 기준 마지막 요청 시각
    "disabled": False,                           # 429 가 재시도에서도 나오면 True → 이번 실행에서 arXiv 중단
}
_arxiv_lock = threading.Lock()


def _is_rate_limit(exc: BaseException) -> bool:
    return getattr(exc, "status", None) == 429 or "429" in str(exc)


def arxiv_call(fn: Callable[[], Any]) -> Any:
    """모든 arXiv 요청이 지나는 관문.

    * 요청 사이에 min_interval(4초) 이상 간격을 두고, 락으로 한 번에 하나만 보낸다 (arXiv 약관: 3초, 단일 연결).
    * 429 를 받으면 wait_after_429(5분) 를 기다린 뒤 딱 한 번 재시도한다. 짧게 재요청하면 제한이 길어지기 때문이다.
      재시도도 429 면 이번 실행에서는 arXiv 요청을 더 보내지 않는다 (이후 호출은 서버에 닿지 않고 바로 실패).
    * 429 가 아닌 오류(네트워크 등)는 간격을 지켜 한 번 더 시도한다.
    """
    g = _ARXIV_GATE

    def attempt():
        wait = g["last_request"] + g["min_interval"] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - 호출자가 분류한다
            g["last_request"] = time.monotonic()
            return None, exc
        g["last_request"] = time.monotonic()
        return result, None

    with _arxiv_lock:
        if g["disabled"]:
            raise ArxivRateLimited("arXiv HTTP 429 가 재시도에서도 반복되어 이번 실행에서는 arXiv 요청을 보내지 않습니다")

        result, exc = attempt()
        if exc is None:
            return result

        if _is_rate_limit(exc):
            print(f"    [arXiv] HTTP 429 → {g['wait_after_429']:.0f}초 기다린 뒤 한 번만 다시 시도합니다")
            time.sleep(g["wait_after_429"])
            result, exc2 = attempt()
            if exc2 is None:
                return result
            if _is_rate_limit(exc2):
                g["disabled"] = True
                print("    [arXiv] 재시도도 HTTP 429 → 이번 실행에서 arXiv 요청을 더 보내지 않습니다")
                raise ArxivRateLimited("arXiv HTTP 429 반복 — 이번 실행에서 arXiv 중단") from exc2
            raise exc2

        # 429 가 아닌 오류: 간격을 지켜 한 번만 더
        result, exc2 = attempt()
        if exc2 is None:
            return result
        raise exc2


# ── arXiv ──────────────────────────────────────────────────────────────────────

def _arxiv_run(query: str, max_results: int) -> list:
    search = arxiv_lib.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv_lib.SortCriterion.Relevance,
    )
    return arxiv_call(lambda: list(clients.arxiv_client.results(search)))


def _arxiv_result_dict(r) -> Dict[str, Any]:
    authors = ", ".join(a.name for a in r.authors[:3])
    if len(r.authors) > 3:
        authors += " 외"
    short_id = r.get_short_id()
    short_id = short_id.split("v")[0] if "v" in short_id[-4:] else short_id
    return {
        "title": " ".join((r.title or "").split()),
        "url": r.entry_id,
        "arxiv_id": short_id,
        "authors": authors,
        "year": str(r.published.year) if r.published else "",
        "published": r.published.strftime("%Y-%m-%d") if r.published else "",
        "categories": ", ".join((r.categories or [])[:3]),
        "abstract": " ".join((r.summary or "").split()),
    }


def arxiv_search_results(
    query: str,
    *,
    max_results: int = ARXIV_MAX_RESULTS,
    years_back: int = ARXIV_YEARS_BACK,
    min_before_fallback: int = ARXIV_MIN_BEFORE_FALLBACK,
) -> List[Dict[str, Any]]:
    """arXiv 검색 1건 → 논문별 dict (전체 초록 포함).

    최근 years_back 년 제출 논문으로 먼저 검색하고, 결과가 min_before_fallback 보다 적으면
    무필터 검색으로 보충한다. 같은 논문(arXiv id)은 한 번만 남긴다.
    """
    results: list = []
    if years_back and years_back > 0:
        y = date.today().year
        dated = f"{query} AND submittedDate:[{y - years_back + 1}01010000 TO {y}12312359]"
        try:
            results = _arxiv_run(dated, max_results)
        except ArxivRateLimited:
            raise                       # 429 로 arXiv 가 중단된 상태에서는 무필터 재시도도 하지 않는다
        except Exception as exc:  # noqa: BLE001 - 필터 문법·네트워크 실패는 무필터로 넘어간다
            # 상태 코드를 함께 남긴다: HTTP 400 = 필터 문법 거부(코드 문제), 그 외 = 네트워크
            detail = str(exc).split("(http", 1)[0].strip()[:90]
            print(f"    [arXiv] 날짜 필터 검색 실패 → 무필터로 재시도 ({type(exc).__name__}: {detail})")
            results = []
    if len(results) < min_before_fallback:
        try:
            results += _arxiv_run(query, max_results)
        except Exception:
            if not results:
                raise

    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in results:
        d = _arxiv_result_dict(r)
        if d["arxiv_id"] in seen:
            continue
        seen.add(d["arxiv_id"])
        out.append(d)
        if len(out) >= max_results:
            break
    return out


def _arxiv_search_block(query: str, max_results: int = 3) -> str:
    """arXiv 검색 1건을 '쿼리/논문 목록(제목·저자·발행·초록·URL)' 으로 직렬화. (Reviewer 용)"""
    items: list[str] = []
    try:
        for r in _arxiv_run(query, max_results):
            d = _arxiv_result_dict(r)
            summary = d["abstract"]
            if len(summary) > 300:
                summary = summary[:300] + "..."
            items.append(
                f"제목: {d['title']}\n"
                f"저자: {d['authors']}\n"
                f"발행: {d['published'] or 'N/A'}\n"
                f"초록: {summary}\n"
                f"URL: {d['url']}"
            )
    except Exception as exc:
        return f"쿼리: {query}\n검색 실패: {exc}"

    if not items:
        return f"쿼리: {query}\n결과 없음"
    return f"쿼리: {query}\n\n" + "\n\n".join(items)


# ── LLM 쿼리 생성 ──────────────────────────────────────────────────────────────

def _generate_queries(prompt_template: str, *, n: int = QUERIES_PER_ROUND, **fmt) -> list[str]:
    """LLM 으로 줄바꿈 구분 쿼리 최대 n개를 생성. 번호·불릿·따옴표는 벗겨 낸다."""
    response = clients.llm.invoke(prompt_template.format(**fmt))
    queries: list[str] = []
    for line in response.content.strip().split("\n"):
        q = line.strip().lstrip("-*•").strip()
        q = q[q.find(".") + 1:].strip() if q[:2].rstrip(".").isdigit() and "." in q[:3] else q
        q = q.strip('"\'' + "“”‘’")
        if q:
            queries.append(q)
    return queries[:n]


# ── 피드백 누적 섹션 빌더 ──────────────────────────────────────────────────────

def build_prev_feedback_section(history: list, reviewer_name: str) -> str:
    """이전 라운드 피드백 누적 섹션 생성 (Reviewer A/B 공용)."""
    if not history:
        return ""
    prev = "\n\n---\n".join(
        f"[{i + 1}라운드 피드백]\n{fb}" for i, fb in enumerate(history)
    )
    return (
        f"\n[{reviewer_name} 이전 라운드 피드백 - 반영 여부를 반드시 확인하세요]\n"
        f"{prev}\n"
    )
