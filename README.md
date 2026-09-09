# Drafter

연구 초록 한 단락을 받아 국내 연구개발계획서(마크다운 → PDF)를 만드는 LangGraph 멀티에이전트 파이프라인.

## 실행

1. 의존성: `pip install -r requirements.txt`, `playwright install chromium`, Node.js ≥ 18 (도해용. 없으면 그림 없이 진행)
2. API 키·모델: `.env.example` 을 `.env` 로 복사해 채운다 (`OPENAI_API_KEY`, `TAVILY_API_KEY` 필수 · `OPENAI_MODEL`, `LINER_API_KEY` 선택).
   모델은 gpt-5.1 급을 권한다. 경량 모델은 양식을 어겨 심사 통과와 참고문헌 생성이 잘 안 된다.
3. `main.py` 상단의 `ABSTRACT` / `REQUESTS` / `PDF_AUTHOR` 를 고치고 `python main.py` (표지 부제·키워드는 비워 두면 자동)
   - Scope 단계에서 질문이 최대 3개 나온다: 자기 말로 답하거나, 참고 예시 번호를 치거나, Enter 로 건너뛴다.
   - 초록 수정안은 Enter 로 확정한다. 그 뒤는 자동으로 끝까지 진행된다.
4. 결과: `final/research_paper_<실행시각>.md` 와 `.pdf`. 중간 산출물은 `runtime/<실행시각>/`.

## 파이프라인

```
[Scope]    scope(재서술) → clarify ⇄ 질문 답변 → revise_abstract → 초록 확정 → write_brief(내부용 브리프)
[Research] supervisor → collector A(웹·배경) · B(웹·방법론) · C(학술) 병렬 → 출처 카드 · 갭 분석 루프
[Write]    writer(초안, 코드 양식 검사 + 위반 수정 루프)
[Review]   reviewer_a(내용, 검증 검색) → reviewer_b(가독성) → editor(정리) ─ REVISE → writer 재작성 (≤2회)
[Finalize] plot_framework(Archify 도해 1회) → reporter(코드 표기 정리 · 참고문헌) → cover(표지 부제·키워드) → 마크다운 저장 → PDF 조판
```

## 폴더

```
main.py                 실행 진입점 (초록·추가 요청·표지 정보)
.env                    API 키 (직접 만든다, .env.example 참고)
code/
  core/                 config(튠 값) · paths(폴더 배치·실행 폴더) · state · clients · prompts(로더) · graph · output
  scope/                nodes.py
  research/             supervisor · collectors · cards(출처 카드) · search(Tavily·arXiv) · scholar(Liner)
  write/                writer · lint(양식 검사기) · lint_loop(수정 루프·변경 줄 가드)
  review/               nodes.py (reviewer_a · reviewer_b · editor)
  finalize/             diagram(도해 노드) · diagram_agent(Archify 서브그래프) · reporter · cleanup · references · cover(표지) · export_pdf
    presentation/       PDF 렌더러 (build.py · assets/style.css)
prompts/                단계별 프롬프트 (scope · research · write · review · finalize), 파일명 = 프롬프트 ID
vendor/archify/         Archify v2.17 (서드파티, Node CLI)
scripts/                단독 실행: preflight · run_research_stage · run_archify_agent · export_pdf
tests/                  테스트 스위트 (tests/README.md)
docs/                   변경 기록(CHANGES_2026-09.md) · 에이전트 설명서(agents/) · 도해 설명서(plotting-agent.md) · 결과물 예시(samples/)
runtime/<실행시각>/     research/ · figures/ · pdf_build/  (실행마다 새 폴더)
final/                  research_paper_<실행시각>.md / .pdf
```

## 테스트

API 키 없이 모의 LLM·모의 검색으로 전 단계를 검증한다. 명령은 `tests/README.md`.

## 설정

튠 값은 `code/core/config.py` 한 곳에 있다 (검색 라운드, 심사 라운드, 양식 검사 강도, 도해 수리 횟수 등).
`OPENAI_MODEL`, `SCHOLAR_BACKEND`, `CHROME_PATH`, `ARCHIFY_HOME` 은 `.env` 또는 환경변수로 덮어쓸 수 있다.
