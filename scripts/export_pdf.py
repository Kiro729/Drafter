#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""final/ 의 마크다운을 PDF 로 다시 조판한다. 표지 정보는 main.py 의 PDF_* 를 쓴다.

    python scripts/export_pdf.py                                  # 가장 최근 research_paper_*.md
    python scripts/export_pdf.py final/research_paper_20260909_143012.md

중간 파일은 runtime/<새 실행시각>/pdf_build/ 에 남는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(ROOT))

from finalize.export_pdf import export_pdf, latest_markdown   # noqa: E402
import main as entry                                           # noqa: E402  (PDF_AUTHOR 등 표지 상수)

target = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_markdown()
if target is None:
    print("변환할 research_paper_*.md 를 final/ 에서 찾을 수 없습니다.")
    raise SystemExit(1)
print(f"입력: {target}")
result = export_pdf(target, author=entry.PDF_AUTHOR, keywords=entry.PDF_KEYWORDS, subtitle=entry.PDF_SUBTITLE)
raise SystemExit(0 if result else 1)
