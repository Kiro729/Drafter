# -*- coding: utf-8 -*-
"""양식 검사 → 지목된 위반만 고치는 LLM 호출 → 재검사 루프.

Writer 초안·재작성과 Reporter(심사 뒤) 에 붙는다. 검사(write.lint.lint)는 코드가 하고, 수정만 LLM 이 한다.
오류가 없으면 LLM 을 부르지 않는다. 수정본의 오류가 이전보다 많아지면 이전 본을 유지한다.

change_guard 를 주면(Reporter) 수정본이 지목된 위반 수에 비해 너무 많은 줄을 바꿨을 때도 버린다.
LLM 은 문서 전체를 다시 출력하므로 "지목되지 않은 곳은 바꾸지 마라" 는 지시를 지켰는지는 코드가
줄 단위 diff 로 재야 확실하다.
"""
from __future__ import annotations

import difflib
import math
from typing import Any, Dict, List, Optional, Tuple

from core import clients
from core.config import MAX_LINT_FIX_ROUNDS
from core.prompts import PROMPTS
from write.lint import LintReport, lint
from write.spec import format_prompt


def count_changed_lines(before: str, after: str) -> Tuple[int, int]:
    """(달라진 줄 수, 기준 본문의 줄 수). 빈 줄과 앞뒤 공백은 무시한다.

    달라진 줄 = 교체·삭제·삽입된 구간마다 양쪽 줄 수 중 큰 쪽의 합. git diff 와 같은 계산(difflib).
    """
    a = [ln.strip() for ln in before.splitlines() if ln.strip()]
    b = [ln.strip() for ln in after.splitlines() if ln.strip()]
    changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            changed += max(i2 - i1, j2 - j1)
    return changed, len(a)


def allowed_changed_lines(per_issue: float, n_issues: int) -> int:
    """지목 n건에 허용하는 변경 줄 수. 불릿 병합처럼 한 건이 여러 줄을 건드리는 경우를 위해 최소 2배를 준다."""
    return max(int(math.ceil(2 * per_issue)), int(math.ceil(per_issue * max(n_issues, 1))))


def lint_fix_loop(
    text: str,
    cards: Optional[List[Dict[str, Any]]],
    *,
    label: str,
    max_rounds: int = MAX_LINT_FIX_ROUNDS,
    change_guard: Optional[float] = None,
) -> Tuple[str, str, LintReport]:
    """(최종 본문, 요약 한 줄, 최종 리포트). 요약 예: 'errors 9 → 2 → 0, warnings 3 (clean)'.

    change_guard: 지목된 위반 1건당 허용 변경 줄 수(config LINT_FIX_MAX_LINES_PER_ISSUE). None 이면 재기만 하고 막지 않는다.
    리포트의 metrics 에 llm_calls, changed_lines(입력 대비 최종), total_lines, guard_rejects 를 남긴다.
    """
    original = text
    report = lint(text, cards)
    history = [len(report.errors)]
    llm_calls = guard_rejects = 0
    print(f"  [Lint:{label}] {report.summary()}")
    rounds = 0
    while report.errors and rounds < max_rounds:
        rounds += 1
        instructions = report.to_instructions()
        n_issues = min(len(report.errors), 25) + min(len(report.warnings), 10)    # to_instructions 가 보내는 건수
        print(f"  [Lint:{label}] 수정 요청 {rounds}/{max_rounds}:")
        for line in instructions.splitlines()[:6]:
            print(f"    {line}")
        response = clients.llm.invoke(format_prompt(
            PROMPTS["PROMPT_WRITER_LINT_FIX"],
            research_plan=text,
            lint_report=instructions,
        ))
        llm_calls += 1
        candidate = (response.content or "").strip()
        if not candidate.lstrip().startswith("#"):
            print("    수정본이 계획서 형식이 아니어서 이전 본을 유지")
            history.append(len(report.errors))
            continue
        new_report = lint(candidate, cards)
        changed, total = count_changed_lines(text, candidate)
        if len(new_report.errors) > len(report.errors):
            print(f"    수정본 오류 {len(new_report.errors)}개 > 이전 {len(report.errors)}개 → 이전 본 유지")
        elif change_guard is not None and changed > allowed_changed_lines(change_guard, n_issues):
            guard_rejects += 1
            print(f"    수정본이 {changed}/{total}줄을 바꿈 (지목 {n_issues}건, 허용 {allowed_changed_lines(change_guard, n_issues)}줄)"
                  f" → 지목되지 않은 부분까지 고친 것으로 보고 이전 본 유지")
        else:
            text, report = candidate, new_report
            print(f"    변경 {changed}/{total}줄 (지목 {n_issues}건)")
        history.append(len(report.errors))
        print(f"  [Lint:{label}] 재검사: {report.summary()}")

    status = "clean" if not report.errors else "unresolved"
    summary = f"errors {' → '.join(map(str, history))}, warnings {len(report.warnings)} ({status})"
    changed_total, total = count_changed_lines(original, text)
    report.metrics.update({"llm_calls": llm_calls, "changed_lines": changed_total,
                           "total_lines": total, "guard_rejects": guard_rejects})
    return text, summary, report
