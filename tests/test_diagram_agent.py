# -*- coding: utf-8 -*-
"""Archify plotting-agent 검증. LLM 은 모의 객체, Archify·Playwright 는 실제로 돈다 (Node·Chromium 필요, API 키 불필요).

    python tests/test_diagram_agent.py          # A~D (약 1분, 산출물 tests/out/figures*)
    python tests/test_diagram_agent.py --pdf    # E 까지: 생성한 PNG 로 PDF 조판 (중간 파일은 tests/out/pdf_build 에)

A. 검증된 스펙 → 9/9 통과, SVG/PNG 생성, 같은 스펙은 deliver 캐시
B. 스키마 위반 스펙 → repair 1회 → 통과
C. 고칠 수 없는 스펙 → repair 3회 후 standard 로도 실패 → finalize 가 error 로 종료 (파이프라인은 계속 진행 가능)
F. showcase 마감 검증(통로 공유) 실패 → repair 3회 → standard 품질 폴백으로 렌더 (2026-09-09 실제 실행의 실패 스펙)
D. plot_framework 노드 단독 실행 (clients.llm 을 가짜 ChatModel 로 대체)
E. D 의 PNG 를 프론트매터에 넣은 마크다운으로 export_pdf → PDF 조판 (--pdf)
"""
import copy
import functools
import json
import shutil
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "out"
sys.path.insert(0, str(ROOT / "code"))
os.environ.setdefault("DRAFTER_SKIP_DOTENV", "1")      # 테스트는 프로젝트 .env(키·모델·백엔드)를 읽지 않는다

from core import clients
import finalize.diagram_agent as da
import finalize.diagram as diagram               # noqa: E402
from core import paths                           # noqa: E402

KNOWN_GOOD = json.loads((ROOT / "tests" / "fixtures" / "methodology.workflow.json").read_text(encoding="utf-8"))
PAPER_MD = ROOT / "tests" / "fixtures" / "sample_proposal.md"
paths.start_run(OUT, stamp="diagram")            # DiagramConfig() 기본 out_dir 등 실행 산출물을 tests/out/diagram 에


class MockLLM:
    def __init__(self, replies):
        self.replies = [copy.deepcopy(r) for r in replies]
        self.prompts = []

    def complete_json(self, prompt):
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("모의 LLM 응답 소진")
        return self.replies.pop(0)


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeChatModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    def invoke(self, prompt):
        self.calls.append(prompt)
        return FakeResponse(self.replies.pop(0))


def scratch_cfg(name):
    out = OUT / f"figures_{name}"
    if out.exists():
        shutil.rmtree(out)
    return da.DiagramConfig(out_dir=out)


def section(title):
    print("\n" + "=" * 12, title, "=" * 12)


SERENDIPITY_SPEC = {
    "schema_version": 2, "diagram_type": "workflow",
    "meta": {"title": "연구 프레임워크", "quality_profile": "showcase",
             "legend": {"mode": "auto", "entries": {
                 "database": {"label": "수집 자료"}, "backend": {"label": "연구 단계"},
                 "messagebus": {"label": "분석 및 처리"}, "security": {"label": "평가·검증"},
                 "external": {"label": "기존 방법"}, "frontend": {"label": "연구 산출물"}}}},
    "lanes": [{"id": "data", "label": "자료"}, {"id": "method", "label": "제안 방법"}, {"id": "eval", "label": "평가"}],
    "mainPath": ["logs", "prep", "twin", "surprise", "metric", "evaluate"],
    "nodes": [
        {"id": "logs",     "lane": "data",   "col": 0, "type": "database",   "label": "MovieLens 로그",  "sublabel": "평점·타임스탬프", "width": 136},
        {"id": "movies",   "lane": "data",   "col": 1, "type": "database",   "label": "영화 메타데이터", "sublabel": "장르·키워드", "width": 136},
        {"id": "prep",     "lane": "data",   "col": 2, "type": "backend",    "label": "전처리·분할",     "sublabel": "시간순 분할", "width": 136},
        {"id": "twin",     "lane": "method", "col": 2, "type": "backend",    "label": "디지털 트윈 구축", "sublabel": "모듈 1", "width": 136},
        {"id": "surprise", "lane": "method", "col": 3, "type": "messagebus", "label": "의외성 추정",     "sublabel": "모듈 2", "width": 136},
        {"id": "metric",   "lane": "method", "col": 4, "type": "messagebus", "label": "세렌디피티 지표", "sublabel": "모듈 3", "width": 136},
        {"id": "baseline", "lane": "eval",   "col": 3, "type": "external",   "label": "기존 추천기",     "sublabel": "베이스라인", "width": 136},
        {"id": "evaluate", "lane": "eval",   "col": 4, "type": "security",   "label": "오프라인 평가",   "sublabel": "nDCG·의외성", "width": 136},
        {"id": "result",   "lane": "eval",   "col": 5, "type": "frontend",   "label": "평가 결과",       "width": 136},
    ],
    "edges": [
        {"id": "e1", "from": "logs",     "to": "prep",     "label": "평점 로그",  "variant": "default"},
        {"id": "e2", "from": "movies",   "to": "prep",     "label": "메타데이터", "variant": "dashed"},
        {"id": "e3", "from": "prep",     "to": "twin",     "label": "학습 데이터", "variant": "emphasis"},
        {"id": "e4", "from": "twin",     "to": "surprise", "label": "기대 분포",  "variant": "emphasis"},
        {"id": "e5", "from": "surprise", "to": "metric",   "label": "의외성 점수", "variant": "emphasis"},
        {"id": "e6", "from": "prep",     "to": "baseline", "label": "학습 데이터", "variant": "dashed"},
        {"id": "e7", "from": "baseline", "to": "evaluate", "label": "추천 목록",  "variant": "dashed"},
        {"id": "e8", "from": "metric",   "to": "evaluate", "label": "지표 값",    "variant": "emphasis"},
        {"id": "e9", "from": "evaluate", "to": "result",   "label": "결과 도출",  "variant": "emphasis"},
    ],
}


def main(with_pdf: bool):
    problems = da.preflight(da.DiagramConfig())
    if problems:
        print("preflight 실패 — Node/Archify/Playwright 를 먼저 준비하세요:")
        for p in problems:
            print("  -", p)
        return 1

    # ── A ───────────────────────────────────────────────────────────────────────
    section("A. known-good spec → pass first try")
    cfg = scratch_cfg("A")
    llm = MockLLM([{"caption_ko": "연구 절차 개요", "spec": KNOWN_GOOD}])
    out = da.run_diagram_agent("(dummy methodology)", "framework_1", cfg=cfg, llm=llm)
    assert out["error"] is None, out["error"]
    res = out["result"]
    for k in ("svg_path", "png_path", "html_path"):
        assert Path(res[k]).exists(), k
    assert res["checks_passed"] == "9/9" and len(llm.prompts) == 1
    print("checks:", res["checks_passed"], "| png:", Path(res["png_path"]).stat().st_size // 1024, "KB")
    mtime = Path(res["html_path"]).stat().st_mtime
    out2 = da.run_diagram_agent("(dummy)", "framework_1", cfg=cfg, llm=MockLLM([{"caption_ko": "x", "spec": KNOWN_GOOD}]))
    assert out2["error"] is None and Path(out2["result"]["html_path"]).stat().st_mtime == mtime
    print("A ok (deliver cache hit on identical spec)")

    # ── B ───────────────────────────────────────────────────────────────────────
    section("B. schema violation → repair → pass")
    bad = copy.deepcopy(KNOWN_GOOD)
    bad["nodes"][0]["colour"] = "red"
    bad["meta"]["locale"] = "ko"
    bad["edges"][0]["route"] = "outside-right"
    cfg = scratch_cfg("B")
    llm = MockLLM([{"caption_ko": "수리 테스트", "spec": bad}, KNOWN_GOOD])
    out = da.run_diagram_agent("(dummy)", "framework_2", cfg=cfg, llm=llm)
    assert out["error"] is None and out["result"]["repair_rounds"] == 1, out
    first = json.loads((cfg.out_dir / "framework_2.spec.json").read_text(encoding="utf-8"))
    assert "locale" not in first["meta"] and "route" not in first["edges"][0]
    print("repairs:", out["result"]["repair_rounds"], "| checks:", out["result"]["checks_passed"])
    print("B ok")

    # ── C ───────────────────────────────────────────────────────────────────────
    section("C. unrepairable spec → 3 repairs → graceful error")
    hopeless = copy.deepcopy(KNOWN_GOOD)
    hopeless["nodes"][0]["col"] = 9
    cfg = scratch_cfg("C")
    llm = MockLLM([{"caption_ko": "x", "spec": hopeless}, hopeless, hopeless, hopeless])
    out = da.run_diagram_agent("(dummy)", "framework_3", cfg=cfg, llm=llm)
    assert out["result"] is None and out["error"] and out["repair_rounds"] == 3 and len(llm.prompts) == 4
    print("error:", out["error"][:140])
    print("C ok")

    # ── F ───────────────────────────────────────────────────────────────────────
    section("F. showcase composition failure survives 3 repairs → standard-quality fallback renders")
    conflict = json.loads((ROOT / "tests" / "fixtures" / "corridor_conflict.workflow.json").read_text(encoding="utf-8"))
    cfg = scratch_cfg("F")
    llm = MockLLM([{"caption_ko": "통로 충돌 스펙", "spec": conflict}, conflict, conflict, conflict])   # 수리 3회가 모두 같은 스펙을 돌려줌
    out = da.run_diagram_agent("(dummy)", "framework", cfg=cfg, llm=llm)
    assert out["error"] is None, out["error"]
    res = out["result"]
    assert res["quality"] == "standard" and res["checks_passed"].endswith("(standard)") and res["repair_rounds"] == 3, res
    assert Path(res["png_path"]).exists() and Path(res["svg_path"]).exists() and len(llm.prompts) == 4        # 폴백은 LLM 호출 없음
    assert "ambiguous-corridor" in res["note"]
    print("fallback:", res["checks_passed"], "|", res["note"][:80])
    print("F ok")

    # ── D ───────────────────────────────────────────────────────────────────────
    section("D. plot_framework node with fake clients.llm")
    body = PAPER_MD.read_text(encoding="utf-8").split("---\n", 2)[2]
    meth, found = diagram.extract_methodology_section(body)
    assert found and meth.startswith("## 3. 연구 방법론") and "## 4." not in meth
    reply = json.dumps({"caption_ko": "사용자 디지털 트윈 기반 세렌디피티 평가 흐름도", "spec": SERENDIPITY_SPEC}, ensure_ascii=False)
    clients.llm = FakeChatModel(["```json\n" + reply + "\n```"])
    cfg = scratch_cfg("D")
    diagram.run_diagram_agent = functools.partial(da.run_diagram_agent, cfg=cfg)   # 산출물을 tests/out 으로
    upd = diagram.plot_framework({"research_plan": body})
    assert upd["diagram_checks"] == "9/9", upd["diagram_checks"]
    assert upd["framework_figure_path"].endswith("tests/out/figures_D/framework.png"), upd["framework_figure_path"]
    assert (ROOT / upd["framework_figure_path"]).exists() and (ROOT / upd["framework_svg_path"]).exists()
    assert upd["framework_caption"].endswith("흐름도")
    assert clients.llm.bound == {"response_format": {"type": "json_object"}}
    print("figure:", upd["framework_figure_path"], "| caption:", upd["framework_caption"])
    print("D ok")

    # ── E ───────────────────────────────────────────────────────────────────────
    if with_pdf:
        section("E. export_pdf with the Archify PNG (--pdf)")
        from finalize.export_pdf import export_pdf
        paper = PAPER_MD.read_text(encoding="utf-8")
        front, rest = paper.split("---\n", 2)[1], paper.split("---\n", 2)[2]
        lines = []
        for line in front.splitlines():
            if line.startswith("framework_figure:"):
                line = f"framework_figure: {upd['framework_figure_path']}"
            elif line.startswith("framework_caption:"):
                line = f"framework_caption: {upd['framework_caption']}"
            lines.append(line)
        test_md = OUT / "research_paper_archify_test.md"
        test_md.write_text("---\n" + "\n".join(lines) + "\n---\n" + rest, encoding="utf-8")
        pdf = export_pdf(test_md, author="테스트", keywords=["세렌디피티", "Archify"], subtitle="Archify 도해 조판 테스트",
                         work_dir="tests/out/pdf_build")          # 상대경로도 받는다 (build.py 에는 절대경로로 전달)
        assert pdf and Path(pdf).exists(), pdf
        print("pdf:", pdf)
        print("E ok")
    else:
        print("\n(E 건너뜀 — PDF 조판까지 보려면 --pdf)")

    print("\nALL DIAGRAM TESTS PASSED  (outputs:", OUT, ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(with_pdf="--pdf" in sys.argv))
