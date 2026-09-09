# -*- coding: utf-8 -*-
"""연구계획서 마크다운 → 디자인 적용 PDF 브리지.

presentation/build.py 렌더러는 순수 마크다운 한 개와 그림 한 장을 받아 표지·목차·본문 PDF 를 만든다.
이 모듈이 그 입력을 준비한다.
  1) YAML 프론트매터 제거 (렌더러는 '# 제목' 으로 시작하는 본문을 기대)
  2) 프론트매터의 framework_figure 를 figure1.png 로 복사
  3) 본문에 '- [그림 1] 캡션' 불릿 삽입 — Reporter 가 그림 표기를 모두 지우므로 위치는 항상 코드가 정한다
  4) 표지 메타(작성자·작성일·부제·키워드) 를 meta.json 으로. 부제·키워드는 인자(main.py PDF_*) → 프론트매터(cover 노드가
     연구 요약을 읽고 만든 subtitle, 브리프의 keywords) → 연구 요약 첫 문장 순으로 정한다
  5) build.py 실행. 중간 파일은 이번 실행의 pdf_build/ 에, PDF 는 마크다운 옆(final/)에 남는다.

단독 재조판: python scripts/export_pdf.py [final/research_paper_*.md]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.paths import FINAL_DIR, PROJECT_ROOT, pdf_build_dir

PRESENTATION_DIR = Path(__file__).resolve().parent / "presentation"
BUILD_SCRIPT = PRESENTATION_DIR / "build.py"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# ── 입력 준비 ───────────────────────────────────────────────────────────────────

def _split_frontmatter(text: str) -> tuple:
    """'---' 로 감싼 프론트매터를 {key: value} 로 파싱하고 본문과 분리."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    front = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            front[key.strip()] = value.strip()
    return front, text[match.end():].lstrip("\n")


def _resolve_figure(front: dict, explicit) -> Optional[Path]:
    """사용할 프레임워크 이미지. 우선순위: 명시적 인자 → 프론트매터 framework_figure. 둘 다 없으면 그림 없이 조판."""
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.exists():
            return path
        print(f"  [PDF] 지정한 그림을 찾지 못함: {path}")
    recorded = front.get("framework_figure")
    if recorded:
        path = PROJECT_ROOT / recorded.replace("\\", "/")
        if path.exists():
            return path
        print(f"  [PDF] 프론트매터의 그림을 찾지 못함: {path}")
    return None


# 렌더러는 '- [그림 N] 캡션' 독립 불릿만 그림으로 바꾼다. Reporter 가 본문의 그림 표기를 모두 제거하므로
# 보통은 참조가 없고, 여기서 '### 제안 방법' 개요 불릿 끝에 코드가 하나 넣는다. (사람이 손본 마크다운에
# 다른 형태가 남아 있어도 같은 형태로 통일한다.)
_FIG_BULLET_RE = re.compile(r"^\s*[-*]\s*\[그림\s*\d+\]", re.MULTILINE)
_FIG_INLINE_RE = re.compile(r"^([ \t]*[-*][ \t]+)(.+?)(\[그림\s*\d+\].*)$", re.MULTILINE)
_MD_IMAGE_RE = re.compile(r"^[ \t]*[-*]?[ \t]*!\[[^\]]*\]\([^)]*\)[ \t]*\n?", re.MULTILINE)
# 제목에 번호("3.2")나 덧말("(Proposed Method)")이 붙어도 찾는다. 소제목이 전혀 없는 문서는 연구 방법론 절 머리로 폴백.
_PROPOSAL_HEAD_RE = re.compile(r"^###\s*(?:\d+(?:\.\d+)*[.)]?\s*)?제안\s*방법\b[^\n]*$", re.MULTILINE)
_MODULE_HEAD_RE = re.compile(r"^####[ \t]*모듈", re.MULTILINE)
_METHOD_CHAPTER_RE = re.compile(r"^##\s*(?:\d+\.\s*)?연구\s*방법론[^\n]*$", re.MULTILINE)


def _figure_insert_index(lines: list) -> tuple:
    """(그림 불릿을 넣을 줄 번호, 어디에 넣었는지). 못 찾으면 (None, '')."""
    body = "\n".join(lines)
    head = _PROPOSAL_HEAD_RE.search(body)
    if head:                                            # '### 제안 방법' 의 개요 불릿 묶음 끝
        start = body[:head.end()].count("\n") + 1
        last_bullet = None
        for i in range(start, len(lines)):
            stripped = lines[i].strip()
            if stripped.startswith("#"):
                break
            if stripped.startswith(("-", "*")):
                last_bullet = i
        return (last_bullet + 1 if last_bullet is not None else start), "제안 방법 개요 뒤에 삽입"
    module = _MODULE_HEAD_RE.search(body)               # 첫 모듈 소제목 바로 앞
    if module:
        return body[:module.start()].count("\n"), "첫 모듈 소제목 앞에 삽입"
    chapter = _METHOD_CHAPTER_RE.search(body)           # 소제목이 전혀 없는 문서: 연구 방법론 절 머리
    if chapter:
        return body[:chapter.end()].count("\n") + 1, "연구 방법론 절 머리에 삽입 (소제목 없음)"
    return None, ""


def _normalize_figure_reference(body: str, caption: str) -> tuple:
    """본문의 그림 참조를 '- [그림 1] 캡션' 독립 불릿 하나로 통일. (본문, 조치) 반환."""
    body, removed = _MD_IMAGE_RE.subn("", body)
    if _FIG_BULLET_RE.search(body):
        return body, "이미지 문법 제거" if removed else ""
    split_body, n = _FIG_INLINE_RE.subn(r"\1\2\n\1\3", body, count=1)     # 문장 뒤에 붙은 참조를 독립 불릿으로
    if n:
        return split_body, "문장 뒤 참조를 독립 불릿으로 분리"
    lines = body.splitlines()
    index, where = _figure_insert_index(lines)
    if index is None:
        return body, "삽입 위치를 찾지 못함 — 그림 생략됨"
    lines.insert(index, f"- [그림 1] {caption}")
    return "\n".join(lines) + "\n", where


def _derive_subtitle(body: str) -> str:
    """'## 연구 요약' 첫 문장을 표지 부제로 사용."""
    match = re.search(r"^##\s*(?:연구\s*요약|요약|초록)\s*$\n+(.+?)$", body, re.MULTILINE)
    if not match:
        return ""
    return re.split(r"(?<=다\.)\s", match.group(1).strip(), maxsplit=1)[0].strip()


# ── 실행 ────────────────────────────────────────────────────────────────────────

def export_pdf(
    md_path,
    *,
    figure_path=None,
    author: str = "사용자01",
    keywords: Optional[list] = None,
    subtitle: str = "",
    figure_caption: str = "연구 프레임워크 개요",
    meta_overrides: Optional[dict] = None,
    out_path=None,
    work_dir=None,
) -> Optional[str]:
    """마크다운 연구계획서를 PDF 로 변환하고 결과 경로를 반환. 실패 시 None.

    work_dir: 조판 입력·중간 파일 폴더. 기본은 이번 실행의 pdf_build/.
    out_path: 기본은 마크다운과 같은 이름의 .pdf (final/).
    """
    md_path = Path(md_path)
    if not md_path.is_absolute():
        md_path = PROJECT_ROOT / md_path
    if not md_path.exists():
        print(f"  [PDF] 마크다운을 찾을 수 없음: {md_path}")
        return None
    if not BUILD_SCRIPT.exists():
        print(f"  [PDF] 렌더러를 찾을 수 없음: {BUILD_SCRIPT}")
        return None

    front, body = _split_frontmatter(md_path.read_text(encoding="utf-8"))

    figure = _resolve_figure(front, figure_path)
    if figure:
        caption = front.get("framework_caption") or figure_caption
        body, action = _normalize_figure_reference(body, caption)
        print(f"  [PDF] 그림: {figure.name}" + (f" ({action})" if action else ""))
    else:
        print("  [PDF] 프레임워크 그림 없음 — 그림 없이 조판 (도해 생성이 실패한 실행)")      # 그림 불릿을 넣지 않으므로 캡션도 없다

    work = Path(work_dir) if work_dir else pdf_build_dir()
    if not work.is_absolute():
        work = PROJECT_ROOT / work          # build.py 는 자기 폴더에서 실행되므로 넘기는 경로는 모두 절대경로여야 한다
    work.mkdir(parents=True, exist_ok=True)
    (work / "proposal.md").write_text(body, encoding="utf-8")
    fig_target = work / "figure1.png"
    if figure:
        shutil.copyfile(figure, fig_target)
    elif fig_target.exists():
        fig_target.unlink()

    meta: dict = {"figures": {"1": str(fig_target)}}
    resolved_subtitle = subtitle.strip() or front.get("subtitle", "").strip() or _derive_subtitle(body)
    if resolved_subtitle:
        meta["subtitle"] = resolved_subtitle
    resolved_keywords = list(keywords) if keywords else [k.strip() for k in front.get("keywords", "").split(",") if k.strip()]
    if resolved_keywords:
        meta["keywords"] = resolved_keywords
    generated = front.get("generated", "").split()
    meta["meta_rows"] = [
        ["작성자", author],
        ["작성일", generated[0] if generated else datetime.now().strftime("%Y-%m-%d")],
    ]
    if meta_overrides:
        meta.update(meta_overrides)
    meta_file = work / "meta.json"
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    out = Path(out_path) if out_path else md_path.with_suffix(".pdf")
    if not out.is_absolute():
        out = PROJECT_ROOT / out

    print("  [PDF] 렌더링 중... (Chromium)")
    started = time.time()
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT),
         "--md", str(work / "proposal.md"),
         "--out", str(out),
         "--meta", str(meta_file),
         "--build-dir", str(work)],
        cwd=str(PRESENTATION_DIR),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},   # 자식 프로세스 콘솔 인코딩을 UTF-8 로 (cp949 에서 기호 출력 죽음 방지)
    )
    produced = out.exists() and out.stat().st_mtime >= started - 1
    if result.returncode != 0 and not produced:
        print(f"  [PDF] 변환 실패 (exit {result.returncode})")
        if result.stderr.strip():
            print("  " + result.stderr.strip()[-800:])
        return None
    for line in result.stdout.strip().splitlines():
        print(f"  {line.strip()}")
    if result.returncode != 0:
        print(f"  [PDF] 렌더러가 종료 코드 {result.returncode} 를 냈지만 PDF 는 생성됨: {out.name}")
    return str(out)


def latest_markdown() -> Optional[Path]:
    """final/ 에서 가장 최근에 생성된 research_paper_*.md."""
    files = sorted(FINAL_DIR.glob("research_paper_*.md"))
    return files[-1] if files else None
