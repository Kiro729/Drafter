# -*- coding: utf-8 -*-
"""Write 단계 검증: 양식 검사기 · 수정 루프 · 참고문헌 생성 · Writer/Reporter 노드. API 키 불필요.

    python tests/test_write_stage.py

1. 과거 산출물(PASS 판정본)에서 검사기가 실제 위반을 잡는가
2. 양식을 지킨 합성 문서는 오류 0 인가 (오탐 확인)
3. 규칙별 위반을 하나씩 심어 각각 잡히는가 (미탐 확인)
4. 참고문헌 생성: 인용 추출·카드 대조·형식·조판기 링크 규칙·불일치 인용 제거
5. 수정 루프: 지시문에 측정값이 들어가고, 수정본이 나빠지면 이전 본을 유지
6. writer 노드 / 7. reporter 노드: 표기 정리(코드) → 검사 → 오류 없으면 LLM 0회 → 참고문헌
"""
import re
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
os.environ.setdefault("DRAFTER_SKIP_DOTENV", "1")      # 테스트는 프로젝트 .env(키·모델·백엔드)를 읽지 않는다

from core import clients
import write.lint_loop as lint_loop
import finalize.reporter as reporter_node
import write.writer as writer_node
import write.lint as pl
import finalize.references as refs

SAMPLE = (ROOT / "tests" / "fixtures" / "sample_proposal.md").read_text(encoding="utf-8").split("---\n", 2)[2]

CARDS = [
    {"id": "C-01", "channel": "scholar", "title": "A Comparative Analysis of Supportive Navigation on Movie Recommenders",
     "authors": "M. S. Ali, M. M. Tariq, A. Ahmed 외", "year": "2023", "journal": "", "arxiv_id": "2311.13494",
     "doi": "", "url": "http://arxiv.org/abs/2311.13494v1"},
    {"id": "C-02", "channel": "scholar", "title": "Serendipity in Recommender Systems: A Systematic Literature Review",
     "authors": "Reza Jafari Ziarani, Reza Ravanmehr", "year": "2021", "journal": "Journal of Computer Science and Technology",
     "arxiv_id": "", "doi": "10.1007/s11390-020-0135-9", "url": "https://doi.org/10.1007/s11390-020-0135-9"},
]


def section(t):
    print("\n" + "=" * 12, t, "=" * 12)


def codes(report):
    return sorted({i.code for i in report.errors})


# ── 합성 문서 생성기 (양식을 정확히 지키는 문서) ────────────────────────────────

def bullets(n, chars, tail="함", extra=None):
    out = []
    for i in range(n):
        body = "가" * (chars - 1) + tail
        if extra and i in extra:
            body += " " + extra[i]
        out.append(f"- {body}")
    return "\n".join(out)


def module(no, name, sub_chars=77):
    parts = [f"#### 모듈 {no}: {name}"]
    for label in pl.MODULE_LABELS:
        parts.append(f"- {label}")
        parts.append(f"  - {'가' * sub_chars}함")
    return "\n".join(parts)


def make_doc(**over):
    d = {
        "title": "# 사용자 디지털 트윈 기반 세렌디피티 추천 연구",
        "summary": " ".join(["가" * 54 + "다."] * 5),
        "topic": bullets(3, 116),
        "need": bullets(4, 105, extra={0: "[Ali et al., 2023]", 2: "[Ziarani et al., 2021]"}),
        "goal_final": bullets(1, 100),
        "goal_sub": bullets(3, 106),
        "data": bullets(3, 116),
        "overview": bullets(2, 80),
        "m1": module(1, "디지털 트윈 구축"), "m2": module(2, "의외성 추정"), "m3": module(3, "세렌디피티 지표"),
        "exp": bullets(4, 75),
        "contrib": bullets(3, 76),
        "practical": bullets(2, 60),
        "refs": "",
        "extra_section": "",
    }
    d.update(over)
    return f"""{d['title']}

## 연구 요약

{d['summary']}

## 1. 연구 배경

### 연구 주제

{d['topic']}

### 연구 필요성

{d['need']}

## 2. 연구 목표

### 최종 목표

{d['goal_final']}

### 세부 목표

{d['goal_sub']}

## 3. 연구 방법론

### 데이터 수집

{d['data']}

### 제안 방법

{d['overview']}

{d['m1']}

{d['m2']}

{d['m3']}

### 실험 및 평가

{d['exp']}

## 4. 기대 효과 및 활용 방안

### 학술적 기여

{d['contrib']}

### 실용적 활용 방안

{d['practical']}
{d['extra_section']}{d['refs']}"""


class FakeResponse:
    def __init__(self, c):
        self.content = c


class FakeChatModel:
    """프롬프트 종류별 응답. fix 응답은 큐에서 순서대로."""

    def __init__(self, draft, fixes):
        self.draft = draft
        self.fixes = list(fixes)
        self.calls = []

    def bind(self, **kw):
        return self

    def invoke(self, prompt):
        self.calls.append(prompt)
        if "[자동 검사 결과" in prompt:
            return FakeResponse(self.fixes.pop(0) if self.fixes else self.draft)
        if "[작성양식]" in prompt or "[편집자 통합 피드백]" in prompt:
            return FakeResponse(self.draft)
        raise AssertionError(prompt[:200])


def main():
    # ── 1 ───────────────────────────────────────────────────────────────────────
    section("1. lint on a past PASS output catches real violations")
    r = pl.lint(SAMPLE, CARDS)
    print(r.summary())
    print(r.to_instructions()[:1200])
    c = codes(r)
    assert "length_over" in c and "citation_repeat" in c and "length_total" in c, c
    assert "citation_unknown" not in c            # [Ali et al., 2023] 는 카드 C-01 과 일치
    assert "ending" not in c                      # 표본은 ~함/~임/~음 종결을 지켰다
    # 불릿 수: 표본은 지정보다 최대 +2 (연구 주제 5/3, 데이터 수집 5/3, 실험 및 평가 6/4) → 모두 경고, 오류 없음
    assert "bullets_over" not in c
    over_w = [i for i in r.warnings if i.code == "bullets_over"]
    assert any("연구 주제" in i.where and "5개" in i.message for i in over_w), [i.message for i in over_w]
    assert any("실험 및 평가" in i.where and "6개" in i.message for i in over_w)
    assert any("연구 필요성" in i.where for i in over_w)                                              # +1 → 경고
    assert any(i.code == "bullets_under" and "개요" in i.where for i in r.warnings)
    # 완화된 분량 강도: 연구 요약 338자(+21%) 는 경고, 모듈 371~436자(+48~74%) 는 오류
    assert any(i.code == "length_over" and i.where == "연구 요약" for i in r.warnings)
    assert not any(i.code == "length_over" and i.where == "연구 요약" for i in r.errors)
    assert sum(1 for i in r.errors if i.code == "length_over" and "모듈" in i.where) == 3
    assert r.metrics["total_chars"] > pl.TOTAL_CHARS * 1.20                                            # 전체 +22% → 오류
    print("1 ok")

    # ── 2 ───────────────────────────────────────────────────────────────────────
    section("2. compliant synthetic document → no errors")
    good = make_doc()
    r = pl.lint(good, CARDS)
    print(r.summary(), "| total", r.metrics["total_chars"])
    assert r.ok, r.to_instructions()
    assert abs(r.metrics["total_chars"] - pl.TOTAL_CHARS) / pl.TOTAL_CHARS <= 0.15
    assert r.metrics["unique_citations"] == 2
    # 카드가 없으면 인용은 '확인 불가' 경고만
    r0 = pl.lint(good, [])
    assert r0.ok and any(i.code == "citation_unverified" for i in r0.warnings)
    print("2 ok")

    # ── 3 ───────────────────────────────────────────────────────────────────────
    section("3. each rule is detected")
    cases = {
        "forbidden_word": make_doc(topic=bullets(3, 116, extra={0: "다양한 기법을 검토함"})),
        "markdown_emphasis": make_doc(topic=bullets(3, 116, extra={0: "**강조**"})),
        "ending": make_doc(topic=bullets(3, 116, tail="한다")),
        "ordinal": make_doc(topic=bullets(3, 116, extra={0: "첫째, 이것"})),
        "inline_math": make_doc(topic=bullets(3, 116, extra={0: "$x^2$"})),
        "figure_mention": make_doc(topic=bullets(3, 116, extra={0: "[그림 1] 참조"})),
        "citation_outside": make_doc(goal_sub=bullets(3, 106, extra={0: "[Ali et al., 2023]"})),
        "citation_unknown": make_doc(need=bullets(4, 105, extra={0: "[Unknown et al., 2020]"})),
        "citation_noyear": make_doc(need=bullets(4, 105, extra={0: "[Ali et al.]"})),
        "citation_repeat": make_doc(need=bullets(4, 105, extra={0: "[Ali et al., 2023]", 1: "[Ali et al., 2023]", 2: "[Ali et al., 2023]"})),
        "bullets_over": make_doc(topic=bullets(6, 58)),          # 지정 3 + 3 → 오류 (+1, +2 는 경고)
        "length_over": make_doc(exp=bullets(4, 110)),           # 440자 / 300 = +47% → 오류 (+35% 초과)
        "extra_section": make_doc(extra_section="\n## 5. 예상 위험\n\n- 위험 요소가 있음\n"),
        "missing_section": make_doc(data="").replace("### 데이터 수집\n\n\n\n", ""),
        "module_structure": make_doc(m1=module(1, "디지털 트윈 구축") + "\n- 한계와 대응\n  - 네 번째 항목임"),
        "missing_module": make_doc(m3=""),
        "summary_style": make_doc(summary="- 불릿으로 쓴 요약임\n- 두 번째 불릿임"),
        "missing_title": make_doc(title=""),
        # 경량 모델이 작성양식을 베낀 흔적 (2026-09-09 실제 실행에서 관측)
        "heading_annotation": make_doc().replace("## 1. 연구 배경", "## 1. 연구 배경 — 770자"),
        "template_marker": make_doc().replace("### 연구 주제", "  ● 연구 주제(문제 정의) — 350자"),
        "card_id_citation": make_doc(topic=bullets(3, 116, extra={0: "[A-06, A-07]"})),
    }
    for code, doc in cases.items():
        got = codes(pl.lint(doc, CARDS))
        assert code in got, f"{code}: 잡히지 않음. 잡힌 것: {got}"
    # 경고 항목 (완화 구간)
    r_soft = pl.lint(make_doc(topic=bullets(5, 70), exp=bullets(4, 90)), CARDS)     # 불릿 +2, 실험 및 평가 360자(+20%)
    assert r_soft.ok, r_soft.to_instructions()
    assert any(i.code == "bullets_over" and "5개" in i.message for i in r_soft.warnings)
    assert any(i.code == "length_over" and "실험 및 평가" in i.where for i in r_soft.warnings)
    assert any(i.code == "length_under" for i in pl.lint(make_doc(goal_final=bullets(1, 40)), CARDS).warnings)
    assert any(i.code == "summary_sentences" for i in pl.lint(make_doc(summary="가" * 270 + "다."), CARDS).warnings)
    assert any(i.code == "title_long" for i in pl.lint(make_doc(title="# " + "가" * 70), CARDS).warnings)
    ann = codes(pl.lint(cases["heading_annotation"], CARDS))
    assert "missing_section" not in ann and "extra_section" not in ann, ann        # 주석이 붙어도 섹션은 인식하고 주석만 지목
    assert pl._norm_key("3.2 제안 방법 (Proposed Method)") == "제안 방법"
    assert pl._norm_key("연구 주제(문제 정의) — 350자, 상위 불릿 3개") == "연구 주제" and pl._norm_key("1. 연구 배경 — 770자") == "연구 배경"
    assert "module_structure" in codes(pl.lint(make_doc(m1="2) 모듈 1: 그래프 변환\n- 입력과 출력의 정의\n  - 변환함"), CARDS))
    print(f"{len(cases)} error rules + 3 warning rules detected")
    print("3 ok")

    # ── 4 ───────────────────────────────────────────────────────────────────────
    section("4. references from cards")
    doc = make_doc(refs="\n## 참고문헌\n\n- Wrong LLM reference (2019). Made up.\n")
    keys = refs.extract_citations(doc)
    assert keys == [("Ali", "2023"), ("Ziarani", "2021")], keys
    sec, matched, unmatched = refs.build_references(doc, CARDS)
    print(sec)
    assert len(matched) == 2 and not unmatched
    lines = [ln for ln in sec.splitlines() if ln.startswith("- ")]
    assert lines[0].startswith("- Ali MS, Tariq MM, Ahmed A 외 (2023). A Comparative Analysis") and "arXiv:2311.13494." in lines[0]
    assert lines[1].startswith("- Ziarani RJ, Ravanmehr R (2021). Serendipity in Recommender Systems") \
        and "Journal of Computer Science and Technology." in lines[1] and "DOI:10.1007/s11390-020-0135-9." in lines[1]
    # 조판기(build.py build_reference_index) 규칙: 첫 토큰이 성, (YYYY) 존재 → [Ali et al., 2023] 배지가 링크됨
    for ln in lines:
        txt = ln[2:]
        m = re.match(r"\s*([A-Z][A-Za-z\-']+)", txt)
        y = re.search(r"\((\d{4})\)", txt)
        assert m and y and (m.group(1).lower(), y.group(1)) in {("ali", "2023"), ("ziarani", "2021")}, txt
    final, info = refs.attach_references(doc, CARDS)
    assert "Wrong LLM reference" not in final and final.rstrip().endswith("https://doi.org/10.1007/s11390-020-0135-9")
    assert final.count("## 참고문헌") == 1 and info["references"] == 2
    # 카드에 없는 인용은 표기만 제거되고 문장은 남는다
    doc2 = make_doc(need=bullets(4, 105, extra={0: "[Ali et al., 2023]", 1: "[Ghost et al., 2019]"}))
    final2, info2 = refs.attach_references(doc2, CARDS)
    assert info2["unmatched_citations"] == ["Ghost et al., 2019"] and "[Ghost" not in final2 and info2["references"] == 1
    assert "가" * 104 + "함\n" in final2                     # 문장은 유지
    print("4 ok")

    # ── 5 ───────────────────────────────────────────────────────────────────────
    section("5. lint_fix_loop: measured instructions, keep previous when candidate is worse")
    bad = make_doc(topic=bullets(4, 87, extra={0: "다양한 기법"}), exp=bullets(4, 110))        # 오류 2 (금지 표현, 분량) + 경고(불릿 +1)
    worse = make_doc(topic=bullets(7, 50, extra={0: "다양한", 1: "여러 가지"}), exp=bullets(7, 80))  # 오류: 불릿 +4·+3, 금지 2, 분량
    clients.llm = FakeChatModel(bad, fixes=[worse, good])
    text, summary, report = lint_loop.lint_fix_loop(bad, CARDS, label="test")
    print("summary:", summary)
    assert text.strip() == good.strip() and report.ok and summary.endswith("(clean)")   # 루프는 본문을 strip 한다
    assert re.search(r"errors \d+ → \d+ → 0", summary), summary
    fix_prompt = clients.llm.calls[0]
    assert "[자동 검사 결과" in fix_prompt and "상위 불릿 4개 (지정 3개)" in fix_prompt and "금지 표현 '다양한'" in fix_prompt
    assert re.search(r"실험 및 평가: \d+자 \(목표 300", fix_prompt), fix_prompt[:2000]
    first_errors = int(re.match(r"errors (\d+)", summary).group(1))
    assert summary.startswith(f"errors {first_errors} → {first_errors} → 0")   # worse 후보는 버려져 오류 수 유지
    print("5 ok")

    # ── 6 ───────────────────────────────────────────────────────────────────────
    section("6. writer node with lint loop")
    clients.llm = FakeChatModel(bad, fixes=[good])
    state = {"abstract": "a", "user_requests": "", "research_brief": "b", "background_data": "x", "method_data": "y",
             "arxiv_data": "z", "arxiv_cards": CARDS, "rewrite_count": 0, "review_round": 0}
    upd = writer_node.writer(state)
    assert upd["research_plan"].strip() == good.strip() and upd["lint_writer"].endswith("(clean)"), upd["lint_writer"]
    assert len(clients.llm.calls) == 2                       # 초안 1 + 수정 1
    print("lint_writer:", upd["lint_writer"])
    print("6 ok")

    # ── 7 ───────────────────────────────────────────────────────────────────────
    section("7. reporter node: code cleanup → lint → no LLM call when clean → card-based references")
    passed = make_doc(refs="\n## 참고문헌\n\n- Hallucinated, H. (2001). Fake paper. Nowhere.\n",
                      goal_sub=bullets(3, 106, extra={0: "[Ali et al., 2023]"}),          # 허용 위치 밖 인용 → 코드가 표기만 제거
                      overview=bullets(2, 80) + "\n- [그림 1] 연구 프레임워크 개요")         # 그림 불릿 → 코드가 삭제
    clients.llm = FakeChatModel(passed, fixes=[])
    upd = reporter_node.reporter({**state, "research_plan": passed})
    assert clients.llm.calls == []                                                          # 오류가 없으면 LLM 을 부르지 않는다
    paper = upd["research_paper"]
    assert "Hallucinated" not in paper and paper.count("## 참고문헌") == 1 and "[그림" not in paper
    assert "- Ali MS, Tariq MM, Ahmed A 외 (2023)." in paper and "- Ziarani RJ, Ravanmehr R (2021)." in paper
    assert upd["references_count"] == 2 and upd["lint_reporter"].endswith("(clean)")
    assert pl.lint(paper, CARDS).ok
    assert upd["reporter_changes"].startswith("2/") and "llm calls 0" in upd["reporter_changes"]   # 인용 표기 1줄 + 그림 불릿 1줄
    print("reporter_changes:", upd["reporter_changes"], "| lint_reporter:", upd["lint_reporter"])
    print("7 ok")

    # ── 8 ───────────────────────────────────────────────────────────────────────
    section("8. graph order: writer → review → (rewrite) → plot_framework → reporter → cover")
    from core import graph
    g = graph.build_graph().get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    nodes = set(g.nodes)
    assert ("writer", "reviewer_a") in edges and ("writer", "plot_framework") not in edges
    assert ("editor", "writer") in edges and ("editor", "plot_framework") in edges          # REVISE / PASS
    assert ("plot_framework", "reporter") in edges and ("reporter", "cover") in edges and ("cover", "__end__") in edges
    assert "writer_plot_review" not in nodes
    assert ("editor", "reporter") not in edges                                              # reporter 는 도해 뒤에만
    print("edges ok:", sorted(t for s, t in edges if s in ("writer", "editor", "plot_framework")))
    print("8 ok")

    print("\nALL WRITE-STAGE TESTS PASSED")


if __name__ == "__main__":
    main()
