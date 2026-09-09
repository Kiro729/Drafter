# -*- coding: utf-8 -*-
"""학술 검색 하이브리드 백엔드 (Collector C).

  발견(discovery)   Liner Scholar Search — 제목·저자·연도·학술지·인용 수·URL·스니펫을 준다. 초록은 없다.
                    endpoint: config.LINER_API_URL = POST https://platform.liner.com/api/v1/tools/search/scholar
  초록 보강(enrich) config.ABSTRACT_SOURCES 순서. 기본 ("arxiv",): URL 이 arXiv 인 논문만 ID 일괄 조회로
                    초록을 받고, 나머지는 Liner 스니펫을 요지 근거로 쓴다(카드에 "근거: 검색 스니펫" 표시).
                    OpenAlex / Semantic Scholar 조회 코드는 남겨 두었고 설정에 넣으면 그 순서로 추가 시도한다.
  대체(fallback)    Liner 키가 없으면 기존 arXiv 검색(search.arxiv_search_results)

세 경로가 모두 같은 dict 목록을 돌려주므로 카드 파이프라인(research.make_cards)은 백엔드를 모른다.
결과 dict 키:
    title, url, arxiv_id, doi, authors(문자열), year, published, categories, journal,
    citation_count(int|None), abstract, snippet, abstract_source(arxiv|openalex|semanticscholar|snippet|none),
    source(liner|arxiv)

백엔드 선택은 config.resolve_scholar_backend(): SCHOLAR_BACKEND=auto 이면 LINER_API_KEY 가 있을 때 liner.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable, Dict, List, Optional

import arxiv as arxiv_lib
import requests

from core import clients
from core.config import (
    ABSTRACT_SOURCES,
    ARXIV_MAX_RESULTS,
    ENRICH_WORKERS,
    LINER_API_URL,
    LINER_LANG,
    LINER_MAX_RESULTS,
    LINER_TIMEOUT,
    OPENALEX_MAILTO,
    S2_API_KEY,
    SCHOLAR_MIN_RECENT,
    SCHOLAR_YEARS_BACK,
    resolve_scholar_backend,
)
from research.search import _arxiv_result_dict, arxiv_call, arxiv_search_results


class LinerError(RuntimeError):
    """Liner API 가 결과를 줄 수 없는 상태 (키 없음·401·402·기타 HTTP 오류)."""


# ── 식별자 파싱 ─────────────────────────────────────────────────────────────────

_ARXIV_ID_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/((?:\d{4}\.\d{4,5})|(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7}))(?:v\d+)?",
    re.IGNORECASE,
)
_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s?#\"']+)", re.IGNORECASE)


def parse_arxiv_id(url: str) -> str:
    m = _ARXIV_ID_RE.search(url or "")
    return m.group(1) if m else ""


def parse_doi(text: str) -> str:
    m = _DOI_RE.search(text or "")
    return m.group(1).rstrip(".),;") if m else ""


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ── HTTP (테스트에서 바꿔 끼우는 얇은 층) ───────────────────────────────────────

def _http_post(url: str, *, headers: Dict[str, str], json: Dict[str, Any], timeout: float):
    return requests.post(url, headers=headers, json=json, timeout=timeout)


def _http_get(url: str, *, params: Optional[Dict[str, Any]] = None,
              headers: Optional[Dict[str, str]] = None, timeout: float = 20):
    return requests.get(url, params=params, headers=headers, timeout=timeout)


def _arxiv_by_ids(ids: List[str]) -> list:
    """arXiv ID 목록을 요청 1회로 조회. search.arxiv_call 관문을 지나므로 간격·429 쿨다운이 적용된다."""
    search = arxiv_lib.Search(id_list=ids, max_results=len(ids))
    return arxiv_call(lambda: list(clients.arxiv_client.results(search)))


# ── Liner Scholar Search ────────────────────────────────────────────────────────

def _retry_after_seconds(resp, default: float = 2.0, cap: float = 15.0) -> float:
    try:
        return min(float(resp.headers.get("Retry-After", default)), cap)
    except (TypeError, ValueError):
        return default


def _normalize_liner(r: Dict[str, Any]) -> Dict[str, Any]:
    url = str(r.get("url") or "")
    authors = [str(a).strip() for a in (r.get("authors") or []) if str(a).strip()]
    authors_str = ", ".join(authors[:3]) + (" 외" if len(authors) > 3 else "")
    published = str(r.get("date") or "").strip()
    year = published[:4] if re.match(r"(19|20)\d{2}", published) else ""
    return {
        "title": " ".join(str(r.get("title") or "").split()),
        "url": url,
        "arxiv_id": parse_arxiv_id(url),
        "doi": parse_doi(url),
        "authors": authors_str,
        "year": year,
        "published": published,
        "categories": "",
        "journal": " ".join(str(r.get("journal") or "").split()),
        "citation_count": _int_or_none(r.get("citationCount")),
        "abstract": "",
        "snippet": " ".join(str(r.get("description") or "").split()),
        "abstract_source": "",
        "source": "liner",
    }


def liner_scholar_results(
    query: str,
    *,
    max_results: int = LINER_MAX_RESULTS,
    lang: Optional[str] = LINER_LANG,
    date_range: Optional[str] = None,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Liner Scholar Search 1회 → 정규화된 결과 목록. 429 는 Retry-After 만큼 기다려 한 번 재시도."""
    key = api_key or clients.liner_api_key
    if not key:
        raise LinerError("LINER_API_KEY 가 설정되지 않음")
    body: Dict[str, Any] = {"query": query, "max_results": max(1, min(20, int(max_results)))}
    if lang:
        body["lang"] = lang
    if date_range:
        body["date_range"] = date_range
    headers = {"x-api-key": key, "Content-Type": "application/json"}

    resp = None
    for attempt in range(2):
        resp = _http_post(LINER_API_URL, headers=headers, json=body, timeout=LINER_TIMEOUT)
        if resp.status_code == 429 and attempt == 0:
            wait = _retry_after_seconds(resp)
            print(f"    [Liner] 429 요청 제한 → {wait:.0f}초 후 재시도")
            time.sleep(wait)
            continue
        break

    if resp.status_code == 401:
        raise LinerError("Liner API 키가 거부됨 (401)")
    if resp.status_code == 402:
        raise LinerError("Liner 크레딧 부족 (402) — https://liner.com/developers 에서 충전")
    if resp.status_code != 200:
        raise LinerError(f"Liner HTTP {resp.status_code}: {(resp.text or '')[:200]}")

    data = resp.json()
    results = data.get("results") if isinstance(data, dict) else None
    return [_normalize_liner(r) for r in (results or []) if isinstance(r, dict) and r.get("title")]


# ── 초록 보강 ───────────────────────────────────────────────────────────────────

def _tokens(s: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 2}


def titles_match(a: str, b: str, threshold: float = 0.7) -> bool:
    """제목 토큰 겹침으로 같은 논문인지 판정. 오매칭된 초록이 카드에 들어가는 것을 막는다."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= threshold


def rebuild_inverted_abstract(inv: Optional[Dict[str, List[int]]]) -> str:
    """OpenAlex 의 abstract_inverted_index → 평문."""
    if not inv:
        return ""
    positions: List[tuple] = []
    for word, idxs in inv.items():
        for i in idxs or []:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def _enrich_from_arxiv(pending: List[Dict[str, Any]]) -> None:
    by_id = {r["arxiv_id"]: r for r in pending if r.get("arxiv_id")}
    if not by_id:
        return
    try:
        hits = _arxiv_by_ids(list(by_id))
    except Exception as exc:  # noqa: BLE001 - arXiv 429 등은 다음 출처로 넘긴다
        print(f"    [enrich] arXiv ID 조회 실패 ({type(exc).__name__}) → OpenAlex 로")
        return
    for hit in hits:
        d = _arxiv_result_dict(hit)
        r = by_id.get(d["arxiv_id"])
        if r is None or not d["abstract"]:
            continue
        r["abstract"] = d["abstract"]
        r["abstract_source"] = "arxiv"
        r["categories"] = d["categories"]
        if not r.get("authors"):
            r["authors"] = d["authors"]
        if not r.get("year"):
            r["year"] = d["year"]


def _openalex_lookup(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    select = "title,doi,publication_year,abstract_inverted_index,cited_by_count,primary_location"
    params: Dict[str, Any] = {"select": select}
    if OPENALEX_MAILTO:
        params["mailto"] = OPENALEX_MAILTO
    work = None
    matched_by_doi = False
    if r.get("doi"):
        resp = _http_get(f"https://api.openalex.org/works/https://doi.org/{r['doi']}", params=params)
        if resp.status_code == 200:
            work = resp.json()
            matched_by_doi = True
    if work is None and r.get("title"):
        resp = _http_get("https://api.openalex.org/works",
                         params={**params, "search": r["title"], "per-page": 1})
        if resp.status_code == 200:
            works = (resp.json() or {}).get("results") or []
            if works and titles_match(r["title"], works[0].get("title") or ""):
                work = works[0]
    if not work:
        return None

    # 제목 검색 매치는 같은 제목의 재게재본·복제 레코드일 수 있다 (예: 2017 논문이 2025 DOI 로 매칭).
    # 초록은 그대로 쓰되, 식별자·연도·인용 수 같은 메타데이터는 DOI 매치이거나 연도가 맞을 때만 가져온다.
    year_ok = matched_by_doi or _years_consistent(r.get("year"), work.get("publication_year"))

    out: Dict[str, Any] = {}
    abstract = rebuild_inverted_abstract(work.get("abstract_inverted_index"))
    if abstract:
        out["abstract"] = abstract
        out["abstract_source"] = "openalex"
    if year_ok:
        if not r.get("doi") and work.get("doi"):
            out["doi"] = parse_doi(work["doi"])
        if r.get("citation_count") is None and work.get("cited_by_count") is not None:
            out["citation_count"] = _int_or_none(work["cited_by_count"])
        if not r.get("journal"):
            venue = (((work.get("primary_location") or {}).get("source") or {}).get("display_name"))
            if venue:
                out["journal"] = venue
        if not r.get("year") and work.get("publication_year"):
            out["year"] = str(work["publication_year"])
    return out or None


def _years_consistent(year_a: Any, year_b: Any, tolerance: int = 1) -> bool:
    """두 연도가 모두 있고 tolerance 안이면 True. 한쪽이 없으면 판단 불가 → False (메타데이터를 채우지 않는다)."""
    try:
        return abs(int(year_a) - int(year_b)) <= tolerance
    except (TypeError, ValueError):
        return False


def _s2_lookup(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not S2_API_KEY or not r.get("title"):
        return None
    resp = _http_get(
        "https://api.semanticscholar.org/graph/v1/paper/search/match",
        params={"query": r["title"], "fields": "title,abstract,year,venue,citationCount,externalIds"},
        headers={"x-api-key": S2_API_KEY},
    )
    if resp.status_code != 200:
        return None
    data = (resp.json() or {}).get("data") or []
    if not data or not titles_match(r["title"], data[0].get("title") or ""):
        return None
    hit = data[0]
    out: Dict[str, Any] = {}
    if hit.get("abstract"):
        out["abstract"] = " ".join(str(hit["abstract"]).split())
        out["abstract_source"] = "semanticscholar"
    if _years_consistent(r.get("year"), hit.get("year")):       # 제목 매치이므로 연도가 맞을 때만 메타데이터 채움
        ext = hit.get("externalIds") or {}
        if not r.get("doi") and ext.get("DOI"):
            out["doi"] = ext["DOI"]
        if not r.get("arxiv_id") and ext.get("ArXiv"):
            out["arxiv_id"] = ext["ArXiv"]
        if r.get("citation_count") is None and hit.get("citationCount") is not None:
            out["citation_count"] = _int_or_none(hit["citationCount"])
        if not r.get("journal") and hit.get("venue"):
            out["journal"] = hit["venue"]
    return out or None


def _safe(fn: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]):
    def wrapped(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            return fn(r)
        except Exception:  # noqa: BLE001 - 보강 실패는 조용히 다음 출처로
            return None
    return wrapped


def _enrich_parallel(pending: List[Dict[str, Any]], fn, workers: int) -> None:
    if not pending:
        return
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for r, found in zip(pending, ex.map(_safe(fn), pending)):
            if found:
                r.update(found)


def enrich_abstracts(
    results: List[Dict[str, Any]],
    *,
    sources: tuple = ABSTRACT_SOURCES,
    workers: int = ENRICH_WORKERS,
) -> List[Dict[str, Any]]:
    """초록이 없는 결과에 순서대로 출처를 시도해 초록(과 빠진 메타데이터)을 채운다. 끝까지 없으면 스니펫."""
    def pending() -> List[Dict[str, Any]]:
        return [r for r in results if not r.get("abstract")]

    if "arxiv" in sources and pending():
        _enrich_from_arxiv(pending())
    if "openalex" in sources and pending():
        _enrich_parallel(pending(), _openalex_lookup, workers)
    if "semanticscholar" in sources and S2_API_KEY and pending():
        _enrich_parallel(pending(), _s2_lookup, workers=1)          # S2 는 키 있어도 1 RPS

    for r in results:
        if not r.get("abstract"):
            r["abstract"] = r.get("snippet") or ""
            r["abstract_source"] = "snippet" if r["abstract"] else "none"
    return results


# ── 필터 · 중복 제거 · 디스패처 ─────────────────────────────────────────────────

def soft_year_filter(results: List[Dict[str, Any]], years_back: int, min_recent: int,
                     max_results: int) -> List[Dict[str, Any]]:
    """최근 years_back 년 결과를 앞에 두고, 충분히 많으면 오래된 것은 인용 수 순으로 남는 자리만 채운다."""
    if not years_back:
        return results[:max_results]
    cutoff = date.today().year - years_back + 1

    def year_of(r) -> int:
        try:
            return int(r.get("year") or 0)
        except ValueError:
            return 0

    recent = [r for r in results if year_of(r) >= cutoff]
    older = [r for r in results if year_of(r) < cutoff]
    if len(recent) < min_recent:
        return (recent + older)[:max_results]
    older.sort(key=lambda r: -(r.get("citation_count") or 0))
    return (recent + older)[:max_results]


def _dedup_key(r: Dict[str, Any]) -> str:
    if r.get("arxiv_id"):
        return "arxiv:" + r["arxiv_id"].lower()
    if r.get("doi"):
        return "doi:" + r["doi"].lower()
    if r.get("url"):
        return "url:" + r["url"].lower().split("?")[0].rstrip("/")
    return "title:" + " ".join(_tokens(r.get("title", "")))


def dedup_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in results:
        k = _dedup_key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def scholar_backend_note() -> str:
    """쿼리 생성 프롬프트에 넣는 백엔드별 안내."""
    if resolve_scholar_backend() == "liner":
        return ("The scholar search engine (Liner) accepts natural-language queries and rewrites them itself. "
                "Prefer a precise English phrasing of the concept, e.g. "
                "\"first-person serendipity evaluation in recommender systems\".")
    return ("The scholar search engine (arXiv) matches keywords: use 3–7 content words, no stopwords, "
            "no natural-language sentences.")


def scholar_search_results(query: str, *, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
    """Collector C 의 fetch 함수. 백엔드에 따라 Liner(+초록 보강) 또는 arXiv 결과를 같은 형식으로 돌려준다."""
    backend = resolve_scholar_backend()
    if backend == "arxiv":
        out = arxiv_search_results(query, max_results=max_results or ARXIV_MAX_RESULTS)
        for d in out:
            d.update({"doi": "", "journal": "", "citation_count": None, "snippet": "",
                      "abstract_source": "arxiv" if d.get("abstract") else "none", "source": "arxiv"})
        return out

    results = liner_scholar_results(query, max_results=max_results or LINER_MAX_RESULTS)
    results = dedup_results(results)
    results = soft_year_filter(results, SCHOLAR_YEARS_BACK, SCHOLAR_MIN_RECENT,
                               max_results or LINER_MAX_RESULTS)
    enrich_abstracts(results)
    n_abs = sum(1 for r in results if r["abstract_source"] not in ("snippet", "none"))
    print(f"    [scholar] Liner {len(results)}건 → 초록 보강 {n_abs}건, 스니펫 {len(results) - n_abs}건")
    return results
