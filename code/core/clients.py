# -*- coding: utf-8 -*-
"""LLM / Tavily / arXiv / Liner 클라이언트 싱글턴과 API 키 로딩.

모듈 전역(llm, tavily, arxiv_client, liner_api_key)은 처음엔 None 이고 init_clients() 가 채운다.
노드는 `from core import clients; clients.llm.invoke(...)` 로 항상 최신 객체를 쓴다.

키와 모델은 환경변수 또는 프로젝트 루트의 .env (core.config 가 임포트 시점에 환경변수로 올린다):
  OPENAI_API_KEY   필수
  OPENAI_MODEL     선택 — LLM 모델. 없으면 config.DEFAULT_LLM_MODEL (gpt-5.1). 모든 에이전트가 같은 모델을 쓴다.
  TAVILY_API_KEY   필수 — Collector A/B 와 Reviewer A 의 웹 검색
  LINER_API_KEY    선택 — Liner Scholar Search. SCHOLAR_BACKEND=auto(기본)면 있을 때만 쓰고 없으면 arXiv 로 간다.
                   SCHOLAR_BACKEND=liner 로 강제하면 없을 때 입력을 요청한다.
  S2_API_KEY / OPENALEX_MAILTO — config.ABSTRACT_SOURCES 에 해당 출처를 넣었을 때만 쓴다 (기본 꺼짐).
없는 필수 키는 실행 시 입력을 요청한다.
"""
from __future__ import annotations

import getpass
import os
from typing import Optional

import arxiv
from langchain_openai import ChatOpenAI
from tavily import TavilyClient

from core.config import ARXIV_MIN_INTERVAL, DEFAULT_LLM_MODEL, resolve_scholar_backend

# 전역 클라이언트 (런타임에 init_clients() 로 채워진다)
llm: Optional[ChatOpenAI] = None
tavily: Optional[TavilyClient] = None
arxiv_client: Optional[arxiv.Client] = None
liner_api_key: Optional[str] = None


def _ensure_env(var: str, prompt: str) -> None:
    if not os.environ.get(var):
        os.environ[var] = getpass.getpass(prompt)


def resolve_llm_model(explicit: Optional[str] = None) -> str:
    """쓸 LLM 모델 이름. 인자 → 환경변수 OPENAI_MODEL(.env 포함) → config.DEFAULT_LLM_MODEL 순."""
    return (explicit or os.environ.get("OPENAI_MODEL") or "").strip() or DEFAULT_LLM_MODEL


def init_clients(model: Optional[str] = None, temperature: float = 0):
    """LLM/Tavily/arXiv(/Liner) 클라이언트를 초기화하고 모듈 전역에 할당한다. model 을 주지 않으면 OPENAI_MODEL 을 따른다."""
    global llm, tavily, arxiv_client, liner_api_key
    _ensure_env("OPENAI_API_KEY", "OpenAI API Key  : ")
    _ensure_env("TAVILY_API_KEY", "Tavily API Key  : ")
    if resolve_scholar_backend() == "liner":
        _ensure_env("LINER_API_KEY", "Liner API Key   : ")
    model = resolve_llm_model(model)
    llm = ChatOpenAI(model=model, temperature=temperature)
    tavily = TavilyClient()
    # 재시도는 라이브러리에 맡기지 않는다. research.search.arxiv_call 관문이 간격(ARXIV_MIN_INTERVAL)과
    # 429 쿨다운을 관리하므로, 여기서 num_retries=0 으로 두어 429 직후 즉시 재요청이 나가지 않게 한다.
    arxiv_client = arxiv.Client(delay_seconds=ARXIV_MIN_INTERVAL, num_retries=0)
    liner_api_key = os.environ.get("LINER_API_KEY") or None
    print(f"[clients] model: {model} | scholar backend: {resolve_scholar_backend()}"
          + (" (Liner + arXiv abstract enrichment)" if liner_api_key else " (arXiv direct)"))
    return llm, tavily, arxiv_client
