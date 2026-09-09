# -*- coding: utf-8 -*-
"""연구개발계획서 양식의 단일 원본 (single source of truth).

Writer 프롬프트(prompts/write/PROMPT_WRITER*.md)와 양식 검사기(write/lint.py)가 같은 숫자를
각자 들고 있으면, 한쪽만 고쳤을 때 Writer 가 **지킬 수 없는 규칙**으로 검사기에 계속 지목당한다
(수정 루프가 MAX_LINT_FIX_ROUNDS 를 다 쓰고 `(unresolved)` 로 끝난다). 그래서 양식의 숫자와
라벨은 이 모듈에만 두고,

  · write/lint.py       이 모듈에서 임포트해 검사한다
  · prompts/write/*.md  `{chars[연구 주제]}` 같은 자리표시자로 같은 값을 받는다
                        (format_prompt() 이 prompt_vars() 로 채운다)

양식을 고칠 곳은 이 파일 하나다. 프롬프트의 .md 에는 숫자를 직접 적지 않는다.

상위 항목의 글자수는 하위 항목의 합으로 **계산한다**. 부모와 자식이 서로 어긋난 목표를 갖는
조합 자체를 없애기 위한 것이다 — 그런 조합은 어느 쪽을 맞춰도 다른 쪽이 지적되는, 고칠 수 없는
규칙이 된다. 정합성은 임포트 시점에 _self_check() 가 검사하므로 어긋난 값은 즉시 드러난다.

주의: 검사기가 재는 값은 본문(## 섹션들)뿐이고 `# 연구명` 줄은 세지 않는다. 그래서
BODY_CHARS(검사 기준)와 TOTAL_CHARS(프롬프트가 알리는 전체 = 제목 + 본문)를 구분한다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core.config import LINT_LENGTH_WARN

# ── 제목 · 연구 요약 ─────────────────────────────────────────────────────────────

TITLE_CHARS = 40                                  # "40자 내외", 1행
TITLE_MAX_CHARS = int(TITLE_CHARS * 1.5)          # 60. 이 이상이면 경고 (오류는 아니다)

SUMMARY_CHARS = 280
SUMMARY_SENTENCES = 5                             # 문제 정의 → 기존 한계 → 제안 → 검증 → 기대 결과

# ── 제안 방법 = 전체 구조 개요 + 모듈 MODULE_COUNT 개 ────────────────────────────

OVERVIEW_CHARS = 160
OVERVIEW_BULLETS = 2

#: 모듈마다 이 라벨의 상위 불릿을 이 순서로 정확히 셋만 둔다
MODULE_PARTS: Tuple[Tuple[str, int], ...] = (
    ("입력과 출력의 정의", 80),
    ("핵심 메커니즘", 90),
    ("채택 근거", 80),
)
MODULE_LABELS: Tuple[str, ...] = tuple(label for label, _ in MODULE_PARTS)
MODULE_CHARS = sum(chars for _, chars in MODULE_PARTS)          # 250
MODULE_COUNT = 3

PROPOSAL_KEY = "제안 방법"                                       # 개요 + 모듈을 담는 ### 항목
PROPOSAL_CHARS = OVERVIEW_CHARS + MODULE_COUNT * MODULE_CHARS   # 910

# ── 섹션 · 항목 ─────────────────────────────────────────────────────────────────

#: (## 섹션 키, [(### 항목 키, 글자수, 상위 불릿 수)]). 섹션 글자수는 항목 합으로 계산한다.
#: 불릿 수 None 은 개수를 세지 않는 항목 (제안 방법 — 개요·모듈로 따로 검사한다).
_SECTIONS: List[Tuple[str, List[Tuple[str, int, Optional[int]]]]] = [
    ("연구 요약", []),                                          # 섹션 자체가 하나의 항목
    ("연구 배경", [("연구 주제", 350, 3), ("연구 필요성", 420, 4)]),
    ("연구 목표", [("최종 목표", 100, 1), ("세부 목표", 320, 3)]),
    ("연구 방법론", [("데이터 수집", 350, 3), (PROPOSAL_KEY, PROPOSAL_CHARS, None), ("실험 및 평가", 300, 4)]),
    ("기대 효과 및 활용 방안", [("학술적 기여", 230, 3), ("실용적 활용 방안", 120, 2)]),
]

#: lint 가 쓰는 형태: (섹션 키, 섹션 글자수, [(항목 키, 글자수, 상위 불릿 수)])
SECTION_SPEC: List[Tuple[str, int, List[Tuple[str, int, Optional[int]]]]] = [
    (key, SUMMARY_CHARS if not subs else sum(c for _, c, _ in subs), subs)
    for key, subs in _SECTIONS
]

BODY_CHARS = sum(chars for _, chars, _ in SECTION_SPEC)     # 3380 — 검사기가 재는 값 (제목 제외)
TOTAL_CHARS = TITLE_CHARS + BODY_CHARS                      # 3420 — 프롬프트가 알리는 전체

# ── 표기 · 인용 · 금지 표현 ──────────────────────────────────────────────────────

REFERENCE_KEYS = ("참고문헌", "References")
CITATION_ALLOWED_IN = ("연구 필요성",)      # 인용을 허용하는 ### 항목
MAX_SAME_CITATION = 2                        # 같은 출처를 문서 전체에서 이 횟수까지

FORBIDDEN_EMPHASIS = ["획기적인", "매우 중요한", "최초의", "혁신적인", "전례 없는"]
#: 모호한 정도 표현. "여러" 는 뒤에 오는 말에 따라 정상 용법이 있어 문맥 제한 정규식으로만 잡는다
FORBIDDEN_VAGUE = ["다양한", "여러", "상당한", "개선된"]
FORBIDDEN_VAGUE_PARTIAL = ("여러",)
#: 전체 일치로 잡는 금지 표현 (lint 의 정규식 목록 순서와 같다)
FORBIDDEN_WORDS = FORBIDDEN_EMPHASIS + [w for w in FORBIDDEN_VAGUE if w not in FORBIDDEN_VAGUE_PARTIAL]

# ── 정합성 검사 (임포트 시점) ────────────────────────────────────────────────────


def _self_check() -> None:
    """양식 안에서 서로 맞아야 하는 값들. 어긋나면 임포트가 실패해 즉시 드러난다."""
    assert MODULE_CHARS == sum(c for _, c in MODULE_PARTS), "모듈 글자수는 하위 항목의 합이어야 함"
    assert PROPOSAL_CHARS == OVERVIEW_CHARS + MODULE_COUNT * MODULE_CHARS, "제안 방법 = 개요 + 모듈 합"
    assert PROPOSAL_KEY in item_keys(), f"'{PROPOSAL_KEY}' 항목이 양식에 없음 (모듈을 담는 항목)"
    assert bullets_of(PROPOSAL_KEY) is None, f"'{PROPOSAL_KEY}' 는 개요·모듈로 따로 검사하므로 불릿 수를 두지 않는다"
    for key, chars, subs in SECTION_SPEC:
        if subs:
            assert chars == sum(c for _, c, _ in subs), f"'{key}' 섹션 글자수 {chars} ≠ 항목 합"
        for sub_key, sub_chars, n_bullets in subs:
            assert sub_chars > 0, f"'{sub_key}' 글자수가 0 이하"
            assert n_bullets is None or n_bullets >= 1, f"'{sub_key}' 불릿 수가 1 미만"
    assert BODY_CHARS == sum(c for _, c, _ in SECTION_SPEC), "BODY_CHARS 는 섹션 글자수의 합이어야 함"
    assert TOTAL_CHARS == TITLE_CHARS + BODY_CHARS, "TOTAL_CHARS = 연구명 + 본문"
    assert TITLE_MAX_CHARS >= TITLE_CHARS, "제목 경고 상한이 목표보다 작음"
    assert SUMMARY_SENTENCES >= 1, "연구 요약 문장 수가 1 미만"
    # [섹션 간 정합성 제약] 1·2 — 세부 목표 · 모듈 · 학술적 기여가 일대일로 대응해야 한다.
    # 셋 중 하나만 바꾸면 프롬프트의 대응 지시가 지킬 수 없는 규칙이 된다.
    assert bullets_of("세부 목표") == MODULE_COUNT == bullets_of("학술적 기여"), (
        f"세부 목표 불릿 {bullets_of('세부 목표')} · 모듈 {MODULE_COUNT} · "
        f"학술적 기여 불릿 {bullets_of('학술적 기여')} 는 서로 같아야 함")
    assert set(CITATION_ALLOWED_IN) <= set(item_keys()), "인용 허용 항목이 양식에 없음"
    assert MAX_SAME_CITATION >= 1, "같은 출처 허용 횟수가 1 미만 (인용을 아예 못 쓰게 된다)"


# ── 조회 ────────────────────────────────────────────────────────────────────────

def item_keys() -> List[str]:
    """모든 ### 항목 키 (양식 순서)."""
    return [sub_key for _, _, subs in SECTION_SPEC for sub_key, _, _ in subs]


def chars_of(key: str) -> int:
    """섹션 또는 항목의 목표 글자수."""
    for sec_key, sec_chars, subs in SECTION_SPEC:
        if sec_key == key:
            return sec_chars
        for sub_key, sub_chars, _ in subs:
            if sub_key == key:
                return sub_chars
    raise KeyError(key)


def bullets_of(key: str) -> Optional[int]:
    """항목의 상위 불릿 수. 개수를 세지 않는 항목은 None."""
    for _, _, subs in SECTION_SPEC:
        for sub_key, _, n_bullets in subs:
            if sub_key == key:
                return n_bullets
    raise KeyError(key)


def _per_bullet(key: str) -> int:
    """불릿당 목표 글자수. 프롬프트에 '각 N자' 로 적히므로 5자 단위로 내려 읽기 쉽게 한다."""
    n = bullets_of(key)
    if not n:
        raise KeyError(f"'{key}' 는 불릿 수가 지정되지 않은 항목")
    return int(chars_of(key) / n / 5) * 5


_self_check()


# ── 프롬프트 주입 ───────────────────────────────────────────────────────────────

_ORDINALS = ("", "첫", "두", "세", "네", "다섯", "여섯", "일곱")     # "네 번째 항목은 삭제" 용


def prompt_vars() -> Dict[str, Any]:
    """프롬프트(.md)의 양식 자리표시자를 채우는 값들.

    `{chars[연구 주제]}` · `{bullets[연구 주제]}` · `{per_bullet[세부 목표]}` 처럼 쓰고,
    천 단위 구분이 필요하면 `{chars[연구 방법론]:,}` 로 쓴다.
    """
    chars: Dict[str, int] = {
        "연구명": TITLE_CHARS,
        "본문": BODY_CHARS,
        "전체": TOTAL_CHARS,
        "개요": OVERVIEW_CHARS,
        "모듈": MODULE_CHARS,
    }
    bullets: Dict[str, int] = {"개요": OVERVIEW_BULLETS}
    per_bullet: Dict[str, int] = {}
    for sec_key, sec_chars, subs in SECTION_SPEC:
        chars[sec_key] = sec_chars
        for sub_key, sub_chars, n_bullets in subs:
            chars[sub_key] = sub_chars
            if n_bullets:
                bullets[sub_key] = n_bullets
                per_bullet[sub_key] = _per_bullet(sub_key)
    for label, part_chars in MODULE_PARTS:
        chars[label] = part_chars

    return {
        "chars": chars,
        "bullets": bullets,
        "per_bullet": per_bullet,
        "length_rules": render_length_rules(),                              # 양식 전체를 요약한 목록
        "summary_sentences": SUMMARY_SENTENCES,
        "length_tolerance_pct": int(round(LINT_LENGTH_WARN * 100)),
        "module_count": MODULE_COUNT,
        "module_numbers": "·".join(str(i) for i in range(1, MODULE_COUNT + 1)),     # "1·2·3"
        "module_slash": " / ".join(f"모듈 {i}" for i in range(1, MODULE_COUNT + 1)),
        "module_headings": "\n".join(f"#### 모듈 {i}: (모듈명)" for i in range(1, MODULE_COUNT + 1)),
        "module_labels_arrow": " → ".join(MODULE_LABELS),
        # 모듈에 허용된 하위 불릿은 셋뿐이므로 "네 번째 항목은 삭제" 처럼 지목한다
        "module_next_ordinal": (_ORDINALS[MODULE_COUNT + 1] if MODULE_COUNT + 1 < len(_ORDINALS)
                                else f"{MODULE_COUNT + 1}"),
        "citation_allowed_in": " · ".join(CITATION_ALLOWED_IN),
        "max_same_citation": MAX_SAME_CITATION,
        "citation_repeat_threshold": MAX_SAME_CITATION + 1,                 # "N회 이상이면 초과분 삭제"
        "forbidden_emphasis": ", ".join(FORBIDDEN_EMPHASIS),
        "forbidden_vague": ", ".join(FORBIDDEN_VAGUE),
    }


_ORDINALS = ("", "첫", "두", "세", "네", "다섯", "여섯")     # module_next_ordinal 용 ("네 번째 항목")


def render_length_rules() -> str:
    """PROMPT_WRITER_REVIEW 의 [분량 규칙] 목록. 양식 전체를 한 덩어리로 요약해 보여 준다."""
    lines = [
        f"- 전체 {TOTAL_CHARS:,}자 (참고문헌 제외)",
        f"- 연구명 {TITLE_CHARS} / 연구 요약 {SUMMARY_CHARS}(산문 1문단, {SUMMARY_SENTENCES}문장)",
    ]
    for n, (sec_key, sec_chars, subs) in enumerate(SECTION_SPEC):
        if not subs:
            continue
        parts = []
        for sub_key, sub_chars, n_bullets in subs:
            if sub_key == PROPOSAL_KEY:
                parts.append(f"{sub_key} {sub_chars:,}"
                             f"(개요 {OVERVIEW_CHARS} + 모듈 {MODULE_COUNT}개 각 {MODULE_CHARS})")
            elif n_bullets:
                per = f", 각 {_per_bullet(sub_key)}" if n_bullets > 1 else ""
                parts.append(f"{sub_key} {sub_chars}(불릿 {n_bullets}개{per})")
            else:
                parts.append(f"{sub_key} {sub_chars}")
        lines.append(f"- {n}. {sec_key} {sec_chars:,} = " + " + ".join(parts))
    return "\n".join(lines)


def format_prompt(template: str, **content: Any) -> str:
    """양식 자리표시자 + 본문 변수를 채워 프롬프트를 완성한다.

    자리표시자가 빠졌으면 KeyError, 본문 변수 이름이 양식 변수와 겹치면 TypeError 로
    바로 드러난다 (조용히 어긋난 프롬프트가 LLM 에 나가는 것보다 낫다).
    """
    return template.format(**prompt_vars(), **content)
