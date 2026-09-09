# 테스트

프로젝트 루트(`Drafter_0909/`)에서 실행한다. 산출물은 `tests/out/` 에 쓰고 `runtime/`·`final/` 은 건드리지 않는다.

## 1. 키 없이 돌아가는 것 (모의 LLM · 모의 검색)

```powershell
python scripts\preflight.py               # 도해 런타임 점검: Node · Archify · Playwright
python tests\test_scope_stage.py          # Scope: 재서술 · 진단형 질문(예시 채택·건너뜀·조기 종료) · 초록 확인 · 내부용 브리프 · Supervisor JSON
python tests\test_research.py             # Research: 출처 카드 · 브리프 직결 · 갭 루프 (Collector A, C-arXiv 경로)
python tests\test_scholar.py              # Research: Liner 하이브리드 — 정규화 · endpoint · 429 재시도 · 초록 보강 · Collector C
python tests\test_write_stage.py          # Write: 양식 원본(프롬프트↔검사기 일치) · 양식 검사기 · 수정 루프 · 카드 기반 참고문헌 · writer/reporter 노드 · 그래프 순서
python tests\test_review_stage.py         # Review: A 검색·B 무검색 · VERDICT 파싱 · Editor 코드 판정 · 프롬프트 형식
python tests\test_finalize_stage.py       # Finalize: Reporter 표기 정리(코드) · 변경 줄 계산 · 수정본 변경 범위 가드 · reporter 노드 · cover 노드(부제·키워드)
python tests\test_diagram_agent.py        # Finalize: Archify 도해 — 검증 9/9 · repair 루프 · plot_framework 노드 (약 1분, Node·Chromium 필요)
python tests\test_diagram_agent.py --pdf  # + 생성한 PNG 로 PDF 조판 (tests/out/pdf_build)
python tests\test_pipeline_smoke.py       # 전체: main.run() 을 모의 LLM·모의 검색으로 끝까지 — 그래프 연결 · 인터럽트 · 실행 폴더 · 저장
```

각 스크립트는 마지막 줄에 `ALL ... TESTS PASSED` 를 찍는다. `AssertionError` 가 나면 그 줄의 주석이 무엇을 검사하던 것인지 알려 준다.
테스트는 `DRAFTER_SKIP_DOTENV=1` 을 설정해 프로젝트의 `.env`(키·모델·백엔드)를 읽지 않으므로 실제 키가 있어도 결과가 달라지지 않는다.

## 2. 실제 API 키로 부분 실행

`.env` 에 키를 적어 두면 스크립트가 읽는다 (`.env.example` 참고).

```powershell
# 도해 에이전트만 (Writer 없이 방법론 절 → Archify 다이어그램). LLM 1~4회
python scripts\run_archify_agent.py tests\fixtures\methodology.md

# Research 단계만 (브리프 → supervisor → collector). C 만 돌리면 Tavily 키 없이도 됨
python scripts\run_research_stage.py --only C
python scripts\run_research_stage.py            # A·B·C 전부, LLM 최대 47회
```

결과는 `runtime/<실행시각>/figures/`, `runtime/<실행시각>/research/` 에 남는다.

## 3. 전체 파이프라인

`main.py` 상단의 `ABSTRACT`, `REQUESTS`, `PDF_*` 를 고친 뒤:

```powershell
python main.py
```

Scope 단계에서 질문이 하나씩 나오면 자기 말로 답하거나, 참고 예시 번호, 또는 Enter(건너뛰기)로 답한다. 초록 수정안은 Enter 로 확정한다.
결과는 `final/research_paper_<실행시각>.md / .pdf`, 중간 산출물은 `runtime/<실행시각>/`.
