# -*- coding: utf-8 -*-
"""prompts/ 아래 단계별 폴더의 PROMPT_*.md 를 읽어 {ID: 본문} 으로.

파일명이 곧 프롬프트 ID (예: prompts/scope/PROMPT_SCOPE_GUIDE.md → "PROMPT_SCOPE_GUIDE").
폴더는 사람이 찾기 쉽게 단계별로 나눈 것이고 ID 는 전역이므로, 같은 이름이 두 폴더에 있으면 오류다.
본문은 str.format(**vars) 으로 변수를 주입한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from core.paths import PROMPTS_DIR

_EXPECTED_PROMPTS = {
    # scope
    "PROMPT_SCOPE_GUIDE", "PROMPT_SCOPE_RESTATE", "PROMPT_SCOPE_CLARIFY", "PROMPT_REVISE_ABSTRACT", "PROMPT_RESEARCH_BRIEF",
    # research
    "PROMPT_SUPERVISOR", "PROMPT_COLLECTOR_A_QUERY", "PROMPT_COLLECTOR_B_QUERY", "PROMPT_COLLECTOR_C_QUERY",
    "PROMPT_CARDS_WEB", "PROMPT_CARDS_SCHOLAR", "PROMPT_EVALUATE_A", "PROMPT_EVALUATE_B", "PROMPT_EVALUATE_C",
    # write
    "PROMPT_WRITER", "PROMPT_WRITER_REVIEW", "PROMPT_WRITER_LINT_FIX",
    # review
    "PROMPT_REVIEWER_A", "PROMPT_REVIEWER_B", "PROMPT_EDITOR", "PROMPT_EXTRACT_CLAIMS",
    # finalize
    "PROMPT_DIAGRAM_SELECT_TYPE", "PROMPT_DIAGRAM_AUTHOR_WORKFLOW", "PROMPT_DIAGRAM_REPAIR", "PROMPT_COVER_SUBTITLE",
}


def load_prompts(prompts_dir: Path = PROMPTS_DIR) -> Dict[str, str]:
    if not prompts_dir.exists():
        raise FileNotFoundError(f"prompts 폴더를 찾을 수 없음: {prompts_dir}")
    prompts: Dict[str, str] = {}
    duplicates: list = []
    for path in sorted(prompts_dir.rglob("PROMPT_*.md")):
        if path.stem in prompts:
            duplicates.append(path.stem)
        prompts[path.stem] = path.read_text(encoding="utf-8")
    if duplicates:
        raise FileExistsError(f"같은 ID 의 프롬프트가 두 폴더에 있음: {sorted(set(duplicates))}")
    missing = sorted(_EXPECTED_PROMPTS - set(prompts))
    if missing:
        raise FileNotFoundError(f"누락된 프롬프트 파일 ({len(missing)}개): {missing}\n위치: {prompts_dir}")
    return prompts


# 모듈 임포트 시점에 한 번 로드 (전역 캐시)
PROMPTS: Dict[str, str] = load_prompts()
