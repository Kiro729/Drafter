# -*- coding: utf-8 -*-
"""프로젝트 폴더 배치와 실행별(run) 산출물 폴더.

    Drafter_0909/
      code/       파이프라인 코드 (core · scope · research · write · review · finalize)
      prompts/    단계별 프롬프트 (core.prompts 가 하위 폴더까지 읽는다)
      vendor/     서드파티 (Archify)
      runtime/    실행마다 runtime/<YYYYMMDD_HHMMSS>/ 아래 research/ · figures/ · pdf_build/
      final/      최종 연구계획서 research_paper_<시각>.md / .pdf

실행 폴더는 main.run() 이 start_run() 으로 한 번 만들고, 각 단계는 research_dir() 같은 접근자로 받는다.
start_run() 없이 접근자를 먼저 부르면(단독 스크립트) 그때 새 폴더가 만들어진다.
테스트는 start_run(tests/out, stamp=...) 으로 산출물 위치를 바꾼다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]      # code/core/paths.py → 프로젝트 루트
PROMPTS_DIR = PROJECT_ROOT / "prompts"
VENDOR_DIR = PROJECT_ROOT / "vendor"
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
FINAL_DIR = PROJECT_ROOT / "final"

_run_dir: Optional[Path] = None


def start_run(root: Optional[Path] = None, stamp: Optional[str] = None) -> Path:
    """실행 폴더를 만들고 현재 실행으로 지정한다. 다시 부르면 새 폴더로 바뀐다."""
    global _run_dir
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    _run_dir = Path(root or RUNTIME_ROOT) / stamp
    _run_dir.mkdir(parents=True, exist_ok=True)
    return _run_dir


def run_dir() -> Path:
    return _run_dir if _run_dir is not None else start_run()


def run_stamp() -> str:
    """실행 폴더 이름. final/ 의 파일명에 같은 값을 써서 실행 폴더와 결과를 짝지운다."""
    return run_dir().name


def _subdir(name: str) -> Path:
    p = run_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def research_dir() -> Path:
    """브리프 · 카드 JSON · 증거 마크다운"""
    return _subdir("research")


def figures_dir() -> Path:
    """Archify 스펙 · 검증 리포트 · HTML · SVG · PNG"""
    return _subdir("figures")


def review_dir() -> Path:
    """라운드별 심사 기록: Reviewer A·B 피드백, Editor 통합 피드백, 그 라운드가 심사한 본문"""
    return _subdir("review")


def pdf_build_dir() -> Path:
    """PDF 조판 입력과 중간 파일"""
    return _subdir("pdf_build")


def relative_to_root(path) -> str:
    """산출물 경로를 프로젝트 루트 기준 POSIX 상대경로로 (프론트매터용). 루트 밖이면 절대경로."""
    if not path:
        return ""
    p = Path(path).resolve()
    try:
        return p.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(p)
