#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""도해 런타임 점검: node · archify doctor · playwright · CHROME_PATH. API 키 불필요.

    python scripts/preflight.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from finalize.diagram_agent import DiagramConfig, preflight   # noqa: E402

cfg = DiagramConfig(out_dir=ROOT / "runtime")       # 점검만 하므로 실행 폴더를 만들지 않는다
issues = preflight(cfg)
if issues:
    print("preflight 실패:")
    for issue in issues:
        print("  -", issue)
    raise SystemExit(1)
print(f"preflight ok  (archify: {cfg.cli})")
