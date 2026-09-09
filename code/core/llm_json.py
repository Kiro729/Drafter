# -*- coding: utf-8 -*-
"""LLM 을 JSON 모드로 호출해 dict 를 받는 공용 헬퍼.

OpenAI JSON 모드(response_format=json_object)를 우선 쓰고, 모델이 이를 거부하면 일반 호출로
물러난다. 어느 쪽이든 코드펜스·앞뒤 설명을 벗겨 내고 파싱한다. JSON 모드는 프롬프트에
"JSON" 이라는 단어가 있어야 하므로 프롬프트 끝에 항상 "Return ONLY a JSON object" 를 둔다.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict

from core import clients

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_object(raw: str) -> Dict[str, Any]:
    """LLM 응답에서 JSON 객체 하나를 뽑는다. 코드펜스·앞뒤 설명을 허용한다."""
    text = (raw or "").strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM 응답이 JSON 객체가 아님")
    return data


def invoke_json(prompt: str, model=None) -> Dict[str, Any]:
    """clients.llm (LangChain ChatModel) 을 JSON 모드로 호출해 dict 를 반환."""
    model = model or clients.llm
    if model is None:
        raise RuntimeError("clients.init_clients() 가 먼저 호출되어야 합니다")
    try:
        response = model.bind(response_format={"type": "json_object"}).invoke(prompt)
    except Exception as exc:  # noqa: BLE001 - JSON 모드 미지원 모델만 우회
        if "response_format" not in str(exc):
            raise
        response = model.invoke(prompt)
    return parse_json_object(response.content)
