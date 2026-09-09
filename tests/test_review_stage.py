# -*- coding: utf-8 -*-
"""심사 단계 검증: Reviewer A(내용, 검색) · Reviewer B(가독성, 검색 없음) · Editor(정리, 판정은 코드). API 키 불필요.

    python tests/test_review_stage.py

1. VERDICT 파싱 규칙
2. Reviewer A 는 검증 검색을 하고, 프롬프트에 검색 결과가 붙는다
3. Reviewer B 는 검색을 전혀 하지 않고, 프롬프트에 AI 티 표현 기준이 있다
4. Editor 판정은 코드가 두 VERDICT 로 결정한다 (LLM 의 FINAL_VERDICT 와 달라도)
5. Editor 프롬프트는 한국어 정리 규칙과 계획서 본문을 담는다
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
os.environ.setdefault("DRAFTER_SKIP_DOTENV", "1")      # 테스트는 프로젝트 .env(키·모델·백엔드)를 읽지 않는다

from core import clients
from core import config
import review.nodes as nr
import research.search as search
from core.prompts import PROMPTS   # noqa: E402

PLAN = "# 연구명\n\n## 1. 연구 배경\n\n### 연구 필요성\n\n- 기존 접근은 사용자 기대를 모델링하지 못함 [Ali et al., 2023]\n"


class FakeResponse:
    def __init__(self, c):
        self.content = c


class FakeLLM:
    def __init__(self, a_verdict="REVISE", b_verdict="PASS", editor_verdict="PASS"):
        self.a, self.b, self.e = a_verdict, b_verdict, editor_verdict
        self.calls = []

    def bind(self, **kw):
        return self

    def invoke(self, prompt):
        self.calls.append(prompt)
        if "Extract key claims" in prompt:
            return FakeResponse("serendipity recommender limitations\nuser digital twin evaluation\nMovieLens dataset size")
        if "[Tavily 웹검색 결과]" in prompt:                       # Reviewer A (검색 결과가 붙음)
            return FakeResponse(f"VERDICT: {self.a}\nFEEDBACK:\n1. 위치: 1. 연구 배경 > 연구 필요성 / 인용: \"기존 접근은…\" / 문제: 검색으로 확인되지 않음")
        if "AI 티가 나는 표현" in prompt:                          # Reviewer B
            return FakeResponse(f"VERDICT: {self.b}\nFEEDBACK:\n8. 위치: 전체 / 인용: \"~에 기여할 것으로 기대됨\" / 문제: 상투구 / 고치는 방향: \"세렌디피티 지표 값을 산출함\"")
        if "INTEGRATED_FEEDBACK:" in prompt:                     # Editor
            return FakeResponse(f"FINAL_VERDICT: {self.e}\nINTEGRATED_FEEDBACK:\n## 1. 연구 배경 > 연구 필요성\n1. 위치: … / 인용: \"기존 접근은…\" / 문제: 확인 불가 / 수정 방향: 증거 카드 내용으로 한정 / 출처: 내용(A)")
        raise AssertionError(prompt[:200])


class FakeTavily:
    def __init__(self):
        self.calls = 0

    def search(self, query, **kw):
        self.calls += 1
        return {"answer": f"answer for {query}", "results": [{"url": "https://example.org/a"}]}


arxiv_calls = []


def fake_arxiv_run(query, max_results):
    arxiv_calls.append(query)
    return []


def section(t):
    print("\n" + "=" * 12, t, "=" * 12)


def main():
    # ── 1 ───────────────────────────────────────────────────────────────────────
    section("1. VERDICT parsing")
    assert nr.parse_verdict("VERDICT: PASS\nFEEDBACK: fine") is True
    assert nr.parse_verdict("VERDICT: REVISE\nFEEDBACK: ...\nFINAL_VERDICT: PASS") is False   # FINAL_ 은 무시
    assert nr.parse_verdict("FINAL_VERDICT: PASS") is False                                  # 리뷰어 VERDICT 없음
    assert nr.parse_verdict("  verdict: pass") is True                                        # 대소문자·앞 공백 허용
    assert nr.parse_verdict("") is False
    print("1 ok")

    # ── 2 ───────────────────────────────────────────────────────────────────────
    section("2. Reviewer A searches; prompt carries search blocks")
    clients.llm = FakeLLM(a_verdict="REVISE")
    clients.tavily = FakeTavily()
    search._arxiv_run = fake_arxiv_run
    arxiv_calls.clear()
    state = {"abstract": "초록", "research_plan": PLAN, "review_round": 0, "review_a_history": [], "review_b_history": []}
    upd_a = nr.reviewer_a(state)
    assert upd_a["review_a_passed"] is False and upd_a["review_round"] == 1
    assert clients.tavily.calls == 3 and len(arxiv_calls) == 3
    a_prompt = clients.llm.calls[-1]
    assert "[Tavily 웹검색 결과]" in a_prompt and "[arXiv 학술 검색 결과]" in a_prompt
    assert "내용 심사위원" in a_prompt and "데이터 구체성" in a_prompt and "AI 티" not in a_prompt
    print("A: tavily", clients.tavily.calls, "arxiv", len(arxiv_calls), "| passed", upd_a["review_a_passed"])
    print("2 ok")

    # ── 3 ───────────────────────────────────────────────────────────────────────
    section("3. Reviewer B never searches; prompt has readability + AI-style criteria")
    assert config.REVIEWER_B_SEARCH is False
    clients.tavily = FakeTavily()
    arxiv_calls.clear()
    n_calls = len(clients.llm.calls)
    upd_b = nr.reviewer_b({**state, **upd_a})
    assert upd_b["review_b_passed"] is True and "review_round" not in upd_b
    assert clients.tavily.calls == 0 and not arxiv_calls
    assert len(clients.llm.calls) == n_calls + 1                     # 쿼리 생성 호출도 없음
    b_prompt = clients.llm.calls[-1]
    assert "[Tavily 웹검색 결과]" not in b_prompt and "검색하거나 사실의 진위를 따지지 않습니다" in b_prompt
    assert "AI 티가 나는 표현" in b_prompt and "연구 요약의 직관성" in b_prompt and "설득력" in b_prompt
    assert "금지 표현" in b_prompt and "심사하지 않습니다" in b_prompt   # 코드가 잡는 항목 제외 안내
    print("B: tavily", clients.tavily.calls, "arxiv", len(arxiv_calls), "| passed", upd_b["review_b_passed"])
    print("3 ok")

    # ── 4 ───────────────────────────────────────────────────────────────────────
    section("4. Editor verdict is decided by code from both reviewers")
    # A REVISE + B PASS, LLM 이 PASS 라고 써도 → REVISE
    clients.llm = FakeLLM(editor_verdict="PASS")
    st = {**state, "review_round": 1, "review_a_passed": False, "review_b_passed": True,
          "review_a_history": ["VERDICT: REVISE\nFEEDBACK: x"], "review_b_history": ["VERDICT: PASS\nFEEDBACK: y"], "rewrite_count": 0}
    upd = nr.editor(st)
    assert upd["review_passed"] is False and upd["rewrite_count"] == 1
    assert upd["editor_feedback"].startswith("## 1. 연구 배경 > 연구 필요성")
    # A PASS + B PASS, LLM 이 REVISE 라고 써도 → PASS
    clients.llm = FakeLLM(editor_verdict="REVISE")
    upd = nr.editor({**st, "review_a_passed": True, "review_b_passed": True})
    assert upd["review_passed"] is True and upd["rewrite_count"] == 0
    # 리뷰어 판정이 state 에 없으면(과거 실행 호환) REVISE 로 본다
    upd = nr.editor({k: v for k, v in st.items() if not k.endswith("_passed")})
    assert upd["review_passed"] is False
    print("4 ok")

    # ── 5 ───────────────────────────────────────────────────────────────────────
    section("5. Editor prompt: Korean, grouped by section, carries the plan")
    e_prompt = clients.llm.calls[-1]
    assert "한국어로 씁니다" in e_prompt and "문서 순서대로" in e_prompt and "출처: 내용(A) / 가독성(B) / 공통" in e_prompt
    assert PLAN.strip() in e_prompt                                   # 계획서 본문 포함
    assert "코드가 따로 처리하므로 뺍니다" in e_prompt                   # 형식 지적 제외
    PROMPTS["PROMPT_EDITOR"].format(abstract="a", research_plan="p", review_a="x", review_b="y")
    print("5 ok")

    print("\nALL REVIEW-STAGE TESTS PASSED")


if __name__ == "__main__":
    main()
