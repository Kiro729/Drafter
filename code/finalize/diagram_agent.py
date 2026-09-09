# -*- coding: utf-8 -*-
"""Archify 기반 다이어그램 에이전트 (plotting-agent 백엔드).

연구계획서의 "연구 방법론" 절을 입력받아 Archify workflow JSON 스펙을 작성하고,
Archify 검증 게이트를 통과할 때까지 수리한 뒤 HTML → SVG/PNG 로 추출한다.

    START → select_type → author → validate ─┬─ ok ────→ deliver → export → finalize → END
                                   ↑         ├─ retry ─→ repair ─┘        (최대 MAX_DIAGRAM_REPAIR_ROUNDS 회)
                                   └─────────┴─ 한도 ──→ downgrade(standard 품질) → validate 한 번 더 → 실패면 finalize(error)

* LLM 이 만드는 것은 이미지가 아니라 Archify JSON 스펙이다. 검증(validate)·렌더(deliver)·
  추출(export)은 결정론적 파이프라인이고, 같은 스펙은 같은 산출물을 낸다.
* Archify `validate` 는 검증 실패 시에도 exit code 0 을 반환한다. 반드시 ``ok`` 필드로 판정한다.
* 실측 제약과 함정(한글 폭, 레인 라벨, locale, route 프리셋 등)은 설계 문서
  DiagramAgent/DiagramAgent.md 에 정리되어 있고, 프롬프트(prompts/finalize/PROMPT_DIAGRAM_*.md)에 반영했다.

호출 지점: finalize.diagram.plot_framework → run_diagram_agent()
단독 점검:  python scripts/preflight.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from core import clients
from core.config import (
    ARCHIFY_HOME,
    CHROME_PATH,
    DIAGRAM_EXPORT_FORMATS,
    DIAGRAM_FALLBACK_QUALITY,
    DIAGRAM_QUALITY,
    MAX_DIAGRAM_REPAIR_ROUNDS,
)
from core.paths import figures_dir
from core.prompts import PROMPTS


# ── 설정 ────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DiagramConfig:
    #: Archify 패키지 루트(bin/archify.mjs) 또는 리포 루트(archify/bin/archify.mjs)
    archify_home: Path = ARCHIFY_HOME
    #: 산출물 디렉터리 (스펙 JSON · 검증 리포트 · HTML · SVG · PNG). None 이면 이번 실행의 figures/
    out_dir: Optional[Path] = None
    node_bin: str = "node"
    #: Chrome/Chromium 실행 파일. None 이면 Playwright 번들 브라우저
    chrome_path: Optional[str] = CHROME_PATH
    quality: str = DIAGRAM_QUALITY
    theme: str = "light"
    export_formats: tuple = DIAGRAM_EXPORT_FORMATS
    max_repair_rounds: int = MAX_DIAGRAM_REPAIR_ROUNDS
    #: showcase 검증이 수리 한도까지 실패하면 이 품질로 한 번 더 검증·렌더한다. None 이면 그림 없이 끝낸다
    fallback_quality: Optional[str] = DIAGRAM_FALLBACK_QUALITY
    #: Archify 업데이트 알림 네트워크 호출 차단
    disable_update_check: bool = True

    def __post_init__(self):
        if self.out_dir is None:
            object.__setattr__(self, "out_dir", figures_dir())      # frozen dataclass
        else:                                                     # archify 는 자기 패키지 폴더에서 실행되므로 절대경로여야 한다
            object.__setattr__(self, "out_dir", Path(self.out_dir).resolve())

    @property
    def cli(self) -> Path:
        for cand in (self.archify_home / "bin" / "archify.mjs",
                     self.archify_home / "archify" / "bin" / "archify.mjs"):
            if cand.exists():
                return cand
        return self.archify_home / "bin" / "archify.mjs"

    @property
    def package_root(self) -> Path:
        """`node bin/archify.mjs ...` 를 실행할 작업 디렉터리 (bin 의 부모)."""
        return self.cli.parent.parent

    def env(self) -> Dict[str, str]:
        env = dict(os.environ)
        if self.disable_update_check:
            env["ARCHIFY_UPDATE_CHECK_DISABLED"] = "1"
        return env


# ── LLM 어댑터 ──────────────────────────────────────────────────────────────────

class LLM(Protocol):
    """노드가 요구하는 최소 인터페이스. 테스트에서는 모의 객체로 대체한다."""

    def complete_json(self, prompt: str) -> Dict[str, Any]: ...


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json_object(raw: str) -> Dict[str, Any]:
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


class ChatModelJSON:
    """clients.llm (LangChain ChatModel) 을 LLM 프로토콜에 맞춘다.

    OpenAI JSON 모드(response_format=json_object)를 우선 쓰고, 모델이 이를 거부하면
    일반 호출로 물러난다. 어느 쪽이든 코드펜스 제거 후 파싱한다.
    """

    def __init__(self, model=None):
        self._model = model

    def complete_json(self, prompt: str) -> Dict[str, Any]:
        model = self._model or clients.llm
        if model is None:
            raise RuntimeError("clients.init_clients() 가 먼저 호출되어야 합니다")
        try:
            response = model.bind(response_format={"type": "json_object"}).invoke(prompt)
        except Exception as exc:  # noqa: BLE001 - JSON 모드 미지원 모델만 우회
            if "response_format" not in str(exc):
                raise
            response = model.invoke(prompt)
        return extract_json_object(response.content)


# ── 프롬프트 ────────────────────────────────────────────────────────────────────

@dataclass
class DiagramPrompts:
    select_type: str
    #: diagram_type -> AUTHOR 프롬프트. 타입마다 허용 필드가 다르므로 분리한다.
    author: Dict[str, str]
    repair: str

    @classmethod
    def from_prompts(cls, prompts: Dict[str, str] = PROMPTS) -> "DiagramPrompts":
        return cls(
            select_type=prompts["PROMPT_DIAGRAM_SELECT_TYPE"],
            author={"workflow": prompts["PROMPT_DIAGRAM_AUTHOR_WORKFLOW"]},
            repair=prompts["PROMPT_DIAGRAM_REPAIR"],
        )


# ── 상태 ────────────────────────────────────────────────────────────────────────

class DiagramState(TypedDict, total=False):
    # 입력
    figure_id: str              # 출력 파일 basename (예: framework)
    methodology_text: str
    feedback: str               # 이전 라운드 Writer 피드백 (없으면 "")

    # select_type
    diagram_type: str
    answered_question: str

    # author / validate / repair
    caption_ko: str
    spec: Dict[str, Any]
    spec_sha256: str
    validate_report: Dict[str, Any]
    repair_rounds: int
    checks_passed: str
    quality: str                # 검증·렌더 품질. 기본 showcase, 폴백 시 standard
    downgraded: bool
    note: str                   # 호출자에게 알릴 메모 (품질 폴백 등)

    # 산출
    html_path: Optional[str]
    svg_path: Optional[str]
    png_path: Optional[str]

    result: Optional[Dict[str, Any]]
    error: Optional[str]


# ── Archify CLI ─────────────────────────────────────────────────────────────────

def _run_archify(cfg: DiagramConfig, args: List[str]) -> Dict[str, Any]:
    """archify CLI 를 --json 으로 실행한다. 판정은 반드시 결과의 ``ok`` 필드로."""
    proc = subprocess.run(
        [cfg.node_bin, str(cfg.cli), *args, "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=cfg.env(), cwd=str(cfg.package_root),
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        return {"ok": False,
                "error": (proc.stderr or "").strip() or f"no output (exit {proc.returncode})"}
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": raw[:2000]}
    if proc.returncode != 0 and "error" not in report:
        report["error"] = (proc.stderr or "").strip() or f"exit {proc.returncode}"
    return report


def spec_hash(spec: Dict[str, Any]) -> str:
    """캐시 키. deliver 가 결정론적이므로 같은 스펙은 재렌더가 불필요하다."""
    canonical = json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


_EDGE_ROUTING_KEYS = ("route", "via", "channelX", "channelY", "fromSide", "toSide")
_DEFAULT_NODE_WIDTH = 136   # 기본 92px 에 한글을 넣으면 글자가 축소된다


def sanitize_spec(spec: Dict[str, Any], *, strip_routing: bool) -> Dict[str, Any]:
    """LLM 이 넣으면 검증에 실패하거나 실패 확률을 높이는 것을 선제 정리한다. 의미는 건드리지 않는다.

    strip_routing: author 단계에서는 명시 라우팅 프리셋을 전부 제거한다(자동 라우팅이 더 안정적).
                   repair 단계에서는 진단이 지시한 라우팅 수정을 살리기 위해 route 만 제거한다.
    """
    if not isinstance(spec, dict):
        return spec
    spec["schema_version"] = 2
    spec["diagram_type"] = "workflow"
    meta = spec.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        spec["meta"] = meta
    meta.pop("locale", None)                 # "ko" 는 허용값(en, zh-CN)이 아니라 검증 실패
    meta.setdefault("title", "연구 프레임워크")
    meta["quality_profile"] = "showcase"
    for node in spec.get("nodes") or []:
        if isinstance(node, dict):
            node.setdefault("width", _DEFAULT_NODE_WIDTH)
    keys = _EDGE_ROUTING_KEYS if strip_routing else ("route",)
    for edge in spec.get("edges") or []:
        if isinstance(edge, dict):
            for k in keys:
                edge.pop(k, None)
    return spec


def _split_author_output(result: Dict[str, Any]) -> tuple:
    """AUTHOR 출력 {"caption_ko", "spec"} 을 (spec, caption) 으로 분리. 스펙만 온 경우도 허용."""
    if isinstance(result.get("spec"), dict):
        return result["spec"], str(result.get("caption_ko") or "").strip()
    if "nodes" in result or "diagram_type" in result:
        caption = str(result.pop("caption_ko", "") or "").strip()   # 스펙 안에 남으면 검증 실패
        return result, caption
    raise ValueError(f"AUTHOR 출력에 spec 이 없음: keys={sorted(result)}")


def _spec_path(cfg: DiagramConfig, figure_id: str) -> Path:
    return cfg.out_dir / f"{figure_id}.spec.json"


# ── SVG/PNG 추출 — 뷰어 공식 API ─────────────────────────────────────────────────

def export_figure(
    cfg: DiagramConfig,
    html_path: Path,
    out_basename: str,
    formats: tuple = ("svg", "png"),
) -> Dict[str, str]:
    """delivered HTML 에서 정적 도해를 추출한다.

    CLI 에는 export 서브커맨드가 없다. 뷰어가 노출하는 전역 API 를 헤드리스로 호출한다:
        window.Archify.exportMenu.run(fmt)    fmt: svg|png|jpeg|webp
        window.Archify.waitForStableLayout()  임의 sleep 대신 사용
    라이브 뷰어의 svg 요소를 스크린샷하면 pan/zoom 컨테이너 때문에 좌우가 잘린다. 반드시 이 API 를 쓸 것.
    SVG 는 @media (prefers-color-scheme) 듀얼테마라 theme 과 무관하게 같은 바이트가 나오고,
    PNG 는 theme 으로 고정된다(PDF 조판에는 PNG 를 쓴다).
    """
    from playwright.sync_api import sync_playwright  # 선택적 의존

    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    produced: Dict[str, str] = {}
    launch_kwargs: Dict[str, Any] = {}
    if cfg.chrome_path:
        launch_kwargs["executable_path"] = cfg.chrome_path

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch_kwargs)
        try:
            page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
            page.goto(f"{html_path.resolve().as_uri()}?theme={cfg.theme}", wait_until="networkidle")
            page.evaluate("() => window.Archify?.waitForStableLayout?.()")
            for fmt in formats:
                with page.expect_download(timeout=60_000) as dl_info:
                    page.evaluate("(f) => window.Archify.exportMenu.run(f)", fmt)
                target = cfg.out_dir / f"{out_basename}.{fmt}"
                dl_info.value.save_as(str(target))
                produced[fmt] = str(target)
        finally:
            browser.close()
    return produced


# ── 노드 ────────────────────────────────────────────────────────────────────────

def make_select_type_node(llm: LLM, prompts: DiagramPrompts):
    """다이어그램 타입을 고른다. 지원 타입이 하나뿐이면 LLM 호출 없이 확정한다.

    archify 내장 추천기(`archify guide`)는 영어·중국어 키워드 매처이고 한국어는 항상
    0 매칭 후 architecture 로 폴백하므로 쓰지 않는다.
    """
    available = sorted(prompts.author)

    def select_type(state: DiagramState) -> DiagramState:
        base = {"repair_rounds": 0, "error": None}
        if len(available) == 1:
            return {**base, "diagram_type": available[0], "answered_question": ""}
        result = llm.complete_json(prompts.select_type.format(
            methodology_text=state["methodology_text"],
            available_types=", ".join(available),
        ))
        dtype = str(result.get("diagram_type") or "").strip()
        if dtype not in available:
            dtype = "workflow" if "workflow" in available else available[0]
        return {**base, "diagram_type": dtype,
                "answered_question": str(result.get("answered_question") or "")}

    return select_type


def make_author_node(llm: LLM, prompts: DiagramPrompts):
    def author(state: DiagramState) -> DiagramState:
        dtype = state.get("diagram_type", "workflow")
        template = prompts.author.get(dtype)
        if template is None:
            return {"error": f"no author prompt for diagram_type={dtype!r}"}

        feedback = (state.get("feedback") or "").strip()
        feedback_section = (
            "## 이전 라운드 Writer 피드백 — 아래 지적을 반드시 반영하십시오\n" + feedback + "\n"
            if feedback else ""
        )
        try:
            result = llm.complete_json(template.format(
                methodology_text=state["methodology_text"],
                feedback_section=feedback_section,
            ))
            spec, caption = _split_author_output(result)
        except Exception as exc:  # noqa: BLE001 - LLM 출력 불량을 상태로 흘린다
            return {"error": f"author failed: {exc}"}

        spec = sanitize_spec(spec, strip_routing=True)
        return {"spec": spec, "caption_ko": caption, "spec_sha256": spec_hash(spec), "error": None}

    return author


def make_validate_node(cfg: DiagramConfig):
    def validate(state: DiagramState) -> DiagramState:
        if state.get("error"):
            return {}
        spec = state.get("spec")
        if not spec:
            return {"error": "no spec to validate"}

        spec_path = _spec_path(cfg, state["figure_id"])
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

        quality = state.get("quality") or cfg.quality
        report = _run_archify(
            cfg, ["validate", state.get("diagram_type", "workflow"), str(spec_path),
                  "--quality", quality],
        )
        report_path = cfg.out_dir / (state["figure_id"] + ".validate.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        checks = report.get("checks") or []
        passed = sum(1 for c in checks if c.get("ok"))
        summary = f"{passed}/{len(checks)}" if checks else "0/0"
        if quality != cfg.quality:
            summary += f" ({quality})"
        return {"validate_report": report, "checks_passed": summary}

    return validate


def _diagnostics_of(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    diags = report.get("diagnostics")
    if diags:
        return diags
    msg = report.get("error") or "validation failed"
    if report.get("stage"):
        msg = f"[{report['stage']}] {msg}"
    return [{"message": msg}]


def make_repair_node(llm: LLM, prompts: DiagramPrompts, cfg: DiagramConfig):
    """진단을 받아 최소 수정한다. 전체를 다시 쓰게 하면 통과했던 부분까지 망가진다."""

    def repair(state: DiagramState) -> DiagramState:
        rounds = state.get("repair_rounds", 0) + 1
        diagnostics = _diagnostics_of(state.get("validate_report") or {})
        try:
            result = llm.complete_json(prompts.repair.format(
                repair_round=rounds,
                max_rounds=cfg.max_repair_rounds,
                diagnostics_json=json.dumps(diagnostics, ensure_ascii=False, indent=2),
                spec_json=json.dumps(state["spec"], ensure_ascii=False, indent=2),
            ))
            spec = result["spec"] if isinstance(result.get("spec"), dict) else result
            if "nodes" not in spec:
                raise ValueError(f"REPAIR 출력에 nodes 가 없음: keys={sorted(spec)}")
            spec.pop("caption_ko", None)
        except Exception as exc:  # noqa: BLE001
            return {"repair_rounds": rounds, "error": f"repair failed: {exc}"}

        spec = sanitize_spec(spec, strip_routing=False)
        return {"spec": spec, "spec_sha256": spec_hash(spec), "repair_rounds": rounds}

    return repair


def make_downgrade_node(cfg: DiagramConfig):
    """showcase 검증을 수리 한도까지 통과하지 못하면 standard 품질로 한 번 더 검증한다.

    standard 는 스키마·구조·겹침·간격 같은 기본 검사(9개)는 그대로 하고, showcase 가 추가하는 마감 검사
    (무관한 엣지의 통로 공유 등)만 뺀다. 그림이 없는 것보다 마감이 덜 된 그림이 낫다는 판단이며,
    결과의 checks_passed 에 "(standard)" 가 남아 구분된다. 2026-09-09 실제 실행의 실패 스펙이 이 경로로 렌더된다.
    """

    def downgrade(state: DiagramState) -> DiagramState:
        first = _diagnostics_of(state.get("validate_report") or {})[0]
        note = (f"showcase 검증이 수리 {state.get('repair_rounds', 0)}회 뒤에도 미통과({first.get('code', '')}) → "
                f"{cfg.fallback_quality} 품질로 렌더")
        return {"quality": cfg.fallback_quality, "downgraded": True, "note": note}

    return downgrade


def make_deliver_node(cfg: DiagramConfig):
    def deliver(state: DiagramState) -> DiagramState:
        if state.get("error"):
            return {}
        spec_path = _spec_path(cfg, state["figure_id"])
        html_path = cfg.out_dir / (state["figure_id"] + ".html")

        quality = state.get("quality") or cfg.quality
        digest = f"{state['spec_sha256']}:{quality}"
        # deliver 는 결정론적이므로 같은 스펙·같은 품질이면 재렌더 불필요
        if html_path.exists() and _cached_hash(cfg, state["figure_id"]) == digest:
            return {"html_path": str(html_path)}

        report = _run_archify(
            cfg, ["deliver", state.get("diagram_type", "workflow"), str(spec_path), str(html_path),
                  "--quality", quality],
        )
        if not report.get("ok", False) and not html_path.exists():
            return {"error": f"deliver failed: {report.get('error')}"}

        _write_cached_hash(cfg, state["figure_id"], digest)
        return {"html_path": str(html_path)}

    return deliver


def make_export_node(cfg: DiagramConfig):
    def export(state: DiagramState) -> DiagramState:
        if state.get("error"):
            return {}
        if not state.get("html_path"):
            return {"error": "no html to export"}
        try:
            produced = export_figure(cfg, Path(state["html_path"]), state["figure_id"],
                                     cfg.export_formats)
        except Exception as exc:  # noqa: BLE001 - 브라우저 실패를 상태로 흘린다
            return {"error": f"export failed: {exc}"}
        return {"svg_path": produced.get("svg"), "png_path": produced.get("png")}

    return export


def finalize(state: DiagramState) -> DiagramState:
    error = state.get("error")
    if not error and not (state.get("png_path") or state.get("svg_path")):
        report = state.get("validate_report") or {}
        if report and not report.get("ok"):
            first = _diagnostics_of(report)[0]
            also = ", standard 품질로도" if state.get("downgraded") else ""
            error = (f"Archify 검증 실패 (수리 {state.get('repair_rounds', 0)}회 후{also} 미통과): "
                     f"{first.get('code', '')} {first.get('message', '')}").strip()
        else:
            error = "no figure produced"
    if error:
        return {"result": None, "error": error}
    return {
        "result": {
            "figure_id": state["figure_id"],
            "diagram_type": state.get("diagram_type"),
            "caption_ko": state.get("caption_ko", ""),
            "svg_path": state.get("svg_path"),
            "png_path": state.get("png_path"),
            "html_path": state.get("html_path"),
            "spec_sha256": state.get("spec_sha256"),
            "checks_passed": state.get("checks_passed"),
            "repair_rounds": state.get("repair_rounds", 0),
            "quality": state.get("quality") or "showcase",
            "note": state.get("note", ""),
        },
        "error": None,
    }


# ── 캐시 ────────────────────────────────────────────────────────────────────────

def _hash_file(cfg: DiagramConfig, figure_id: str) -> Path:
    return cfg.out_dir / (figure_id + ".sha")


def _cached_hash(cfg: DiagramConfig, figure_id: str) -> Optional[str]:
    p = _hash_file(cfg, figure_id)
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def _write_cached_hash(cfg: DiagramConfig, figure_id: str, digest: str) -> None:
    _hash_file(cfg, figure_id).write_text(digest, encoding="utf-8")


# ── 그래프 ──────────────────────────────────────────────────────────────────────

def build_diagram_graph(cfg: DiagramConfig, llm: LLM, prompts: DiagramPrompts):
    g = StateGraph(DiagramState)
    g.add_node("select_type", make_select_type_node(llm, prompts))
    g.add_node("author",      make_author_node(llm, prompts))
    g.add_node("validate",    make_validate_node(cfg))
    g.add_node("repair",      make_repair_node(llm, prompts, cfg))
    g.add_node("downgrade",   make_downgrade_node(cfg))
    g.add_node("deliver",     make_deliver_node(cfg))
    g.add_node("export",      make_export_node(cfg))
    g.add_node("finalize",    finalize)

    def after_validate(state: DiagramState) -> str:
        if state.get("error"):
            return "finalize"
        # validate 는 실패 시에도 exit 0 이다. ok 필드로만 판정한다.
        if (state.get("validate_report") or {}).get("ok"):
            return "deliver"
        if state.get("repair_rounds", 0) >= cfg.max_repair_rounds:
            if cfg.fallback_quality and not state.get("downgraded") and cfg.fallback_quality != cfg.quality:
                return "downgrade"                # showcase 포기 → standard 로 한 번 더
            return "finalize"
        return "repair"

    g.add_edge(START, "select_type")
    g.add_edge("select_type", "author")
    g.add_edge("author", "validate")
    g.add_conditional_edges("validate", after_validate,
                            {"deliver": "deliver", "repair": "repair", "downgrade": "downgrade", "finalize": "finalize"})
    g.add_edge("repair", "validate")          # 재시도 루프
    g.add_edge("downgrade", "validate")       # 품질을 내려 재검증 (한 번만)
    g.add_edge("deliver", "export")
    g.add_edge("export", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


# ── 환경 점검 ───────────────────────────────────────────────────────────────────

_PREFLIGHT_OK: set = set()


def preflight(cfg: DiagramConfig) -> List[str]:
    """런타임 3개(node+archify, playwright, chrome)가 준비됐는지 확인한다. 성공은 프로세스 내 캐시."""
    key = (str(cfg.archify_home), cfg.node_bin, cfg.chrome_path or "")
    if key in _PREFLIGHT_OK:
        return []
    problems: List[str] = []

    if shutil.which(cfg.node_bin) is None:
        problems.append(f"node 를 PATH 에서 찾을 수 없음: {cfg.node_bin!r} (Node.js >= 18 필요)")
    if not cfg.cli.exists():
        problems.append(f"archify CLI 없음: {cfg.cli} "
                        "(ARCHIFY_HOME 확인 또는 vendor/archify 복원)")
    elif not problems:
        doctor = subprocess.run(
            [cfg.node_bin, str(cfg.cli), "doctor"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=cfg.env(), cwd=str(cfg.package_root),
        )
        if "Archify is ready" not in (doctor.stdout or ""):
            problems.append(f"archify doctor 실패:\n{doctor.stdout}\n{doctor.stderr}")

    try:
        import playwright  # noqa: F401
    except ImportError:
        problems.append("playwright 미설치 (pip install playwright && playwright install chromium)")

    if cfg.chrome_path and not Path(cfg.chrome_path).exists():
        problems.append(f"CHROME_PATH 가 존재하지 않음: {cfg.chrome_path}")

    if not problems:
        _PREFLIGHT_OK.add(key)
    return problems


# ── 진입점 ──────────────────────────────────────────────────────────────────────

def run_diagram_agent(
    methodology_text: str,
    figure_id: str,
    feedback: str = "",
    *,
    cfg: Optional[DiagramConfig] = None,
    llm: Optional[LLM] = None,
    prompts: Optional[DiagramPrompts] = None,
) -> Dict[str, Any]:
    """연구방법론 텍스트 → 다이어그램 서브그래프 1회 실행. 최종 DiagramState 를 반환.

    실패해도 예외를 던지지 않고 ``error`` 에 원인을 담아 돌려준다. 호출자(plot_framework)는
    그림 없이 파이프라인을 계속 진행할 수 있다.
    """
    cfg = cfg or DiagramConfig()
    problems = preflight(cfg)
    if problems:
        return {"figure_id": figure_id, "result": None,
                "error": "preflight 실패: " + " | ".join(problems)}

    app = build_diagram_graph(cfg, llm or ChatModelJSON(), prompts or DiagramPrompts.from_prompts())
    return app.invoke({
        "figure_id": figure_id,
        "methodology_text": methodology_text,
        "feedback": feedback or "",
    })
