# -*- coding: utf-8 -*-
"""Finalize(Review 이후) 검증: Reporter 표기 정리 · 변경 줄 계산 · 수정본 변경 범위 가드 · reporter 노드. API 키 불필요.

    python tests/test_finalize_stage.py

1. mechanical_cleanup: 그림 줄 · 허용 위치 밖 인용 · 반복 인용 · 카드에 없는 인용 · 강조 · 참고문헌 섹션을 코드가 정리하고 문장은 유지
2. 애매한 경우는 남긴다: 문장 속 그림 언급, 연도 없는 인용 → 검사기가 지목
3. count_changed_lines: 줄 단위 변경 수 (빈 줄 무시, 교체·삭제·삽입)
4. lint_fix_loop 가드: 지목 범위를 넘게 바꾼 수정본은 버리고 이전 본 유지, 범위 안 수정본은 채택. 가드 없는 Writer 경로는 그대로
5. reporter 노드: 오류 없으면 LLM 0회 / 오류 1건이면 수정 1회 / 통째로 다시 쓴 수정본은 거부하고 심사 통과본 유지
6. cover 노드: 연구 요약을 읽고 부제 생성(LLM 1회) · 브리프 keywords_ko → 표지 키워드 · LLM 실패 시 요약 첫 문장
7. 그림 삽입 위치: 번호·덧말이 붙은 "### 제안 방법", 소제목이 없는 문서의 연구 방법론 절 머리 폴백
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
os.environ.setdefault("DRAFTER_SKIP_DOTENV", "1")      # 테스트는 프로젝트 .env(키·모델·백엔드)를 읽지 않는다
sys.path.insert(0, str(ROOT / "tests"))

from core import clients
import write.lint_loop as lint_loop
import finalize.reporter as reporter_node
import write.lint as pl
import finalize.references as refs
from finalize.cleanup import mechanical_cleanup                       # noqa: E402
from write.lint_loop import count_changed_lines                       # noqa: E402
from test_write_stage import CARDS, FakeChatModel, bullets, make_doc, section   # noqa: E402


def main():
    # ── 1 ───────────────────────────────────────────────────────────────────────
    section("1. mechanical cleanup removes markup only, keeps sentences")
    doc = make_doc(
        topic=bullets(3, 116, extra={1: "[Ali et al., 2023]"}),                                   # 허용 위치 밖
        need=bullets(4, 105, extra={0: "[Ali et al., 2023]", 1: "[Ali et al., 2023]",
                                    2: "[Ali et al., 2023]", 3: "[Ghost et al., 2019]"}),          # 3회째 반복 · 카드 없음
        overview=bullets(2, 80) + "\n- [그림 1] 연구 프레임워크 개요\n"
                                  "- ![framework](runtime/20260909_120000/figures/framework.png)\n그림 1. 프레임워크",
        data=bullets(3, 116, extra={0: "**핵심** [A-06, A-07]", 1: "*강조*"}),
        refs="\n## 참고문헌\n\n- Old, O. (2000). Stale. Nowhere.\n",
    )
    out, rep = mechanical_cleanup(doc, CARDS)
    print("cleanup:", rep.summary())
    assert rep.figure_lines == 3 and rep.citations_outside == 1 and rep.citations_repeat == 1 and rep.citations_unknown == 1
    assert rep.emphasis == 2 and rep.references_section and rep.changed_lines == 8 and rep.card_ids == 1
    assert "[A-06" not in out                                                                   # 카드 ID 표기 제거
    assert "[그림" not in out and "![" not in out and "그림 1." not in out and "## 참고문헌" not in out
    assert out.count("[Ali et al., 2023]") == 2 and "[Ghost" not in out and "*" not in out and "핵심" in out and "강조" in out
    topic_sec = out.split("### 연구 주제")[1].split("### 연구 필요성")[0]
    assert "[" not in topic_sec and topic_sec.count("함\n") == 3                                  # 표기만 뗐고 문장은 그대로
    report = pl.lint(out, CARDS)
    assert report.ok, [i.render() for i in report.errors]
    print("1 ok")

    # ── 2 ───────────────────────────────────────────────────────────────────────
    section("2. ambiguous cases are left for the linter")
    doc2 = make_doc(overview=bullets(2, 80, extra={0: "[그림 1]과 같이 구성함"}),
                    need=bullets(4, 105, extra={0: "[Ali et al.]"}))
    out2, rep2 = mechanical_cleanup(doc2, CARDS)
    assert rep2.figure_lines == 0 and rep2.changed_lines == 0
    assert "[그림 1]과 같이 구성함" in out2 and "[Ali et al.]" in out2
    codes2 = sorted({i.code for i in pl.lint(out2, CARDS).errors})
    assert codes2 == ["citation_noyear", "figure_mention"], codes2
    print("2 ok")

    # ── 3 ───────────────────────────────────────────────────────────────────────
    section("3. count_changed_lines")
    a = "# T\n\n- 하나\n- 둘\n- 셋\n"
    assert count_changed_lines(a, a) == (0, 4)
    assert count_changed_lines(a, "# T\n- 하나\n- 둘!\n- 셋\n") == (1, 4)          # 빈 줄 무시, 1줄 교체
    assert count_changed_lines(a, "# T\n- 하나\n- 셋\n") == (1, 4)                  # 1줄 삭제
    assert count_changed_lines(a, "# T\n- 하나\n- 둘\n- 셋\n- 넷\n") == (1, 4)      # 1줄 삽입
    assert count_changed_lines(a, "# X\n- A\n- B\n- C\n") == (4, 4)                 # 전부 교체
    print("3 ok")

    # ── 4 ───────────────────────────────────────────────────────────────────────
    section("4. change guard: reject a fix that rewrote far beyond the flagged issues")
    bad = make_doc(topic=bullets(3, 116, extra={0: "다양한 기법"}))                                # 오류 1 (금지 표현)
    fixed_ok = make_doc(topic=bullets(3, 116, extra={0: "세 가지 기법"}))                         # 지목된 1줄만 고침
    rewritten = make_doc(topic=bullets(3, 116, extra={0: "세 가지 기법"}),                        # 오류 0 이지만 17줄을 다시 씀
                         summary=" ".join(["나" * 54 + "다."] * 5),
                         goal_sub=bullets(3, 106, tail="임"), data=bullets(3, 116, tail="임"),
                         exp=bullets(4, 75, tail="임"), contrib=bullets(3, 76, tail="임"),
                         practical=bullets(2, 60, tail="임"))
    assert pl.lint(rewritten, CARDS).ok and count_changed_lines(bad, rewritten)[0] >= 17
    assert lint_loop.allowed_changed_lines(4, 1) == 8 and lint_loop.allowed_changed_lines(4, 5) == 20

    clients.llm = FakeChatModel(bad, fixes=[rewritten, fixed_ok])
    text, summary, report = lint_loop.lint_fix_loop(bad, CARDS, label="guard", change_guard=4)
    print("summary:", summary, "| metrics:", report.metrics)
    assert text.strip() == fixed_ok.strip() and report.ok
    assert report.metrics["guard_rejects"] == 1 and report.metrics["llm_calls"] == 2 and report.metrics["changed_lines"] == 1
    assert summary.startswith("errors 1 → 1 → 0"), summary

    clients.llm = FakeChatModel(bad, fixes=[rewritten])                                            # 가드 없음 (Writer 단계) → 채택
    text2, _, report2 = lint_loop.lint_fix_loop(bad, CARDS, label="noguard")
    assert text2.strip() == rewritten.strip() and report2.metrics["guard_rejects"] == 0 and report2.metrics["llm_calls"] == 1

    clients.llm = FakeChatModel(make_doc(), fixes=[])                                              # 오류 없음 → LLM 0회
    _, summary3, report3 = lint_loop.lint_fix_loop(make_doc(), CARDS, label="clean", change_guard=4)
    assert report3.metrics["llm_calls"] == 0 and clients.llm.calls == [] and summary3.endswith("(clean)")
    print("4 ok")

    # ── 5 ───────────────────────────────────────────────────────────────────────
    section("5. reporter node: 0 LLM calls when clean / 1 targeted fix / wholesale rewrite rejected")
    base = {"abstract": "a", "arxiv_cards": CARDS}

    clients.llm = FakeChatModel(make_doc(), fixes=[])
    upd = reporter_node.reporter({**base, "research_plan": make_doc(goal_sub=bullets(3, 106, extra={0: "[Ali et al., 2023]"}))})
    assert clients.llm.calls == [] and upd["references_count"] == 2
    assert upd["reporter_changes"].startswith("1/") and "llm calls 0" in upd["reporter_changes"], upd["reporter_changes"]
    print("5a:", upd["reporter_changes"])

    clients.llm = FakeChatModel(bad, fixes=[fixed_ok])
    upd = reporter_node.reporter({**base, "research_plan": bad})
    assert len(clients.llm.calls) == 1 and "[자동 검사 결과" in clients.llm.calls[0]
    assert refs.strip_references_section(upd["research_paper"]).strip() == fixed_ok.strip()
    assert upd["lint_reporter"].startswith("errors 1 → 0") and "llm calls 1" in upd["reporter_changes"]
    assert upd["reporter_changes"].startswith("1/")
    print("5b:", upd["reporter_changes"])

    clients.llm = FakeChatModel(bad, fixes=[rewritten, rewritten])
    upd = reporter_node.reporter({**base, "research_plan": bad})
    assert len(clients.llm.calls) == 2 and "guard rejects 2" in upd["reporter_changes"]
    assert upd["lint_reporter"].endswith("(unresolved)") and upd["reporter_changes"].startswith("0/")
    assert refs.strip_references_section(upd["research_paper"]).strip() == bad.strip()             # 심사 통과본 그대로
    assert "## 참고문헌" in upd["research_paper"] and upd["references_count"] == 2
    print("5c:", upd["reporter_changes"], "|", upd["lint_reporter"])
    print("5 ok")

    # ── 6 ───────────────────────────────────────────────────────────────────────
    section("6. cover node: subtitle from LLM reading the whole summary, keywords from brief, fallback")
    import finalize.cover as cover

    class CoverLLM:
        def __init__(self, reply=None, fail=False):
            self.reply, self.fail, self.calls = reply, fail, []

        def bind(self, **kw):
            return self

        def invoke(self, prompt):
            self.calls.append(prompt)
            if self.fail:
                raise RuntimeError("boom")
            return type("R", (), {"content": self.reply})()

    paper = make_doc(summary="첫 문장이다. 둘째 문장이다. 셋째 문장이다. 넷째 문장이다. 다섯째 문장이다.")
    assert cover.extract_summary(paper).startswith("첫 문장이다. 둘째") and cover.extract_title(paper).startswith("사용자 디지털 트윈")
    clients.llm = CoverLLM(json.dumps({"subtitle": "요약을 읽고 만든 부제 문장이다."}, ensure_ascii=False))
    upd = cover.cover({"research_paper": paper, "research_brief_data": {"keywords_ko": ["세렌디피티", " 추천 시스템 ", "", "디지털 트윈"]}})
    assert upd["cover_subtitle"] == "요약을 읽고 만든 부제 문장이다."
    assert upd["cover_keywords"] == ["세렌디피티", "추천 시스템", "디지털 트윈"]
    assert len(clients.llm.calls) == 1 and "[연구 요약]" in clients.llm.calls[0]
    assert "첫 문장이다. 둘째 문장이다. 셋째 문장이다." in clients.llm.calls[0]          # 첫 문장이 아니라 요약 전체를 읽는다
    clients.llm = CoverLLM(fail=True)
    upd2 = cover.cover({"research_paper": paper, "research_brief_data": {}})
    assert upd2["cover_subtitle"] == "첫 문장이다." and upd2["cover_keywords"] == []        # LLM 실패 → 첫 문장, 키워드 없음
    print("6 ok")

    # ── 7 ───────────────────────────────────────────────────────────────────────
    section("7. figure insertion: numbered/annotated 제안 방법 heading, and fallback to the methodology chapter head")
    from finalize import export_pdf as xp
    flat = ("# 제목\n\n## 연구 요약\n\n요약이다.\n\n## 3. 연구 방법론 — 1,580자\n\n  ● 데이터 수집 — 350자\n  - 자료를 모음\n\n"
            "## 4. 기대 효과 및 활용 방안\n\n- 효과임\n")
    body, action = xp._normalize_figure_reference(flat, "연구 프레임워크")
    assert "연구 방법론 절 머리" in action, action
    assert body.index("## 3. 연구 방법론") < body.index("- [그림 1] 연구 프레임워크") < body.index("● 데이터 수집")
    numbered = make_doc().replace("### 제안 방법", "### 3.2 제안 방법 (Proposed Method)")
    body2, action2 = xp._normalize_figure_reference(numbered, "캡션")
    assert "제안 방법 개요 뒤" in action2 and "- [그림 1] 캡션" in body2, action2
    assert xp._normalize_figure_reference("# 제목\n\n## 연구 요약\n\n요약이다.\n", "캡션")[1].startswith("삽입 위치를 찾지 못함")
    print("7 ok")

    print("\nALL FINALIZE-STAGE TESTS PASSED")


if __name__ == "__main__":
    main()
