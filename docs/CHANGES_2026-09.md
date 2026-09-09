# Drafter-main 변경 보고 (2026-09-08 ~ 09-09)

> **경로 주의 (09-09 재구성 이후)**: 1~8절과 7-1절의 파일 경로는 재구성 전(`Drafter-main/`) 기준이다. 새 위치는 9절의 대응표를 보라.

기존 코드(DeepResearch v3.4, 2026-07-28 스냅샷)에서 바꾼 것을 영역별로 정리한다.
그래프의 큰 뼈대(Scope → Brief → Supervisor → Collector A·B·C → Writer → 심사 → 최종)는 유지했고,
도해 생성 시점 하나만 옮겼다.

## 0. 한눈에

| 영역 | 이전 | 지금 |
|---|---|---|
| 도해 | Graphviz. 영어 라벨 강제, 레이아웃 검증 없음, Writer 초안 직후 생성·재작성마다 재생성 | **Archify**. 한글 라벨, 9개 검사 통과본만 렌더, **심사 통과 뒤 1회** 생성 |
| 자료 수집 | 검색 요약을 이어 붙여 앞 4,000자만 Writer 에 전달. 충분성 예/아니오 | **출처 카드**(요지·관련도·범위 판정) → 관련도순 선별. 브리프를 쿼리·카드·판정에 직결. **갭 분석**으로 빠진 항목만 재검색 |
| 학술 검색 | arXiv 관련도순 3편, 초록 300자 | **Liner 스콜라**(키 있을 때)로 발견 + arXiv ID 조회로 초록 보강, 없으면 arXiv. 요청 관문(4초 간격, 429 시 5분 대기 1회) |
| Writer 형식 | LLM 이 글자수 자가 점검 (실측: 6/6 건 위반) | **코드 검사기**가 구조·불릿·글자수·문체·표기·인용을 측정 → 위반만 고치는 수정 루프 |
| 참고문헌 | Reporter LLM 이 작성 | 본문 인용을 학술 카드와 대조해 **코드가 생성** (인용과 1:1) |
| Reporter | 증거 전체를 받아 통째로 재작성 | **LLM 정리 없음.** 코드가 표기만 정리 → 검사 → 오류 있을 때만 위반 수정(변경 줄 가드) → 참고문헌 부착. 심사 통과본 대비 변경 줄 기록 |
| 심사 | A=형식+내용, B=가독성, 둘 다 검색, Editor(영어)가 판정 | **A=내용(검색)**, **B=가독성+AI 표현(무검색)**, Editor(한국어)는 정리만, **판정은 코드** |

## 1. 도해: Graphviz → Archify (09-08)

- `code/diagram_agent.py` (신규): LangGraph 서브그래프 `select_type → author → validate ⇄ repair(≤3) → deliver → export → finalize`.
  LLM 이 Archify workflow JSON 스펙을 쓰고, Archify CLI 가 검증·렌더, Playwright 가 SVG/PNG 추출.
- `skills/plotting-agent/archify/` : Archify v2.17 패키지 사본(MIT, 7.5MB). `ARCHIFY_HOME` 으로 교체 가능.
- 프롬프트 신규: `PROMPT_DIAGRAM_SELECT_TYPE`, `PROMPT_DIAGRAM_AUTHOR_WORKFLOW`(검증 통과 스펙 few-shot 포함), `PROMPT_DIAGRAM_REPAIR`.
  `PROMPT_WRITER_PLOT_REVIEW` 는 Archify 스펙 기준으로 재작성(현재는 꺼진 루프에서만 사용).
- `nodes_writer.plot_framework`: 계획서의 `## 3. 연구 방법론` 절만 입력으로 사용. 산출 `workspace/figures/framework_N.{png,svg,html}`, 스펙·검증 리포트.
- 그림 삽입 절차(프론트매터 `framework_figure` → `export_pdf.py` → `build.py`)는 그대로.
- **순서 변경 (09-08 저녁, 사용자 요청)**: `editor PASS → plot_framework → reporter`. Writer 의 스펙 검토 루프는 `PLOT_REVIEW_ENABLED=False` 로 기본 꺼짐.
- 결정: 타입은 `workflow` 만. PDF 에는 PNG(라이트 고정), SVG 는 보관. Graphviz 폴백 없음(실패 시 그림 없이 진행). 레거시 스크립트·`PROMPT_PLOT_SPEC` 은 삭제하지 않고 남김.

## 2. Research 단계 재설계 (09-08)

### 2.1 출처 카드 파이프라인 — `code/research.py` (신규)
- 검색 결과 1건 = 카드 1장: 제목·URL·연도·종류(또는 접근 계열)·요지(한국어 3~5문장, 고유명사 원문)·관련도 0~5·범위 안팎·근거(초록/스니펫).
- 쿼리당 LLM 1회로 카드화(`PROMPT_CARDS_WEB`, `PROMPT_CARDS_SCHOLAR`). 실패 시 원문 발췌 카드로 폴백.
- 중복 제거(arXiv ID → DOI → URL 정규화) → 범위 안·관련도≥2 → 관련도·인용 수·연도순 상위 N장(A12/B12/C15, 채널당 12,000자 예산).
- writer/reporter 의 `[:4000]` 잘림 제거. 카드 전체·증거 텍스트를 `workspace/research/cards_X.json`, `evidence_X.md` 에 저장.

### 2.2 브리프 직결·필터 — `code/research.py`, 쿼리 프롬프트
- 브리프(RESEARCH QUESTION / IN SCOPE / OUT OF SCOPE / KEY CONCEPTS)를 파싱해 쿼리 생성·카드 판정·갭 분석 프롬프트에 직접 주입.
- `PROMPT_COLLECTOR_{A,B,C}_QUERY` 재작성: 브리프, 이전 갭 분석, 이미 쓴 쿼리, (C) 백엔드 안내.

### 2.3 갭 분석 루프 — `PROMPT_EVALUATE_{A,B,C}`, `nodes_collector.py`
- 예/아니오 충분성 → 채널 기준 3개 covered/partial/missing + 빠진 주제 + 후속 쿼리(JSON). 다음 라운드 쿼리에 주입.
- `MAX_SEARCH` 2 → 3. 규칙 보정: missing 1개 이상 또는 partial 2개 이상이면 불충분. 커버리지 요약을 state·프론트매터·Run Summary 에 기록.

### 2.4 학술 검색 하이브리드 — `code/scholar.py` (신규)
- Liner Scholar Search(`POST platform.liner.com/api/v1/tools/search/scholar`, x-api-key)로 발견(제목·저자·연도·학술지·인용 수·URL·스니펫).
- 초록 보강은 **arXiv 만**(`ABSTRACT_SOURCES=("arxiv",)`, 사용자 결정): arXiv URL 논문은 ID 일괄 조회, 그 외는 스니펫(카드에 "근거: 검색 스니펫").
  OpenAlex·Semantic Scholar 조회 코드는 남겨 두고 설정으로만 켠다(제목 매치 시 연도 일치할 때만 메타데이터 채움).
- `SCHOLAR_BACKEND=auto`: `LINER_API_KEY` 있으면 liner, 없으면 arxiv. 429 는 Retry-After 1회 재시도, 401/402 즉시 실패.
- writer/reporter 규칙 "arXiv 논문만 인용" → "학술 논문 카드(C-xx)만 인용".

### 2.5 arXiv 요청 관문 — `search.arxiv_call` (09-08~09)
- 모든 arXiv 요청(검색·ID 조회·Reviewer 검증 검색)이 한 관문을 지난다. 요청 간 4초, 락으로 단일 연결.
- 429 → 5분 대기 후 1회 재시도, 재시도도 429 → **이번 실행에서 arXiv 중단**(남은 쿼리는 건너뜀). 라이브러리 재시도 0.
- 배경: 이 네트워크에서 arXiv 429 지속. 사용자 지시로 세션 중 라이브 호출 자제.

## 3. Write 단계 (09-08 저녁 ~ 09-09)

### 3.1 양식 검사기 + 수정 루프 — `code/proposal_lint.py`, `code/lint_loop.py`, `PROMPT_WRITER_LINT_FIX` (신규)
- 검사(코드, LLM 없음): 제목·섹션·항목 존재/순서/명칭, 모듈 1~3 과 하위 불릿 3개(입력과 출력의 정의 → 핵심 메커니즘 → 채택 근거),
  항목별 상위 불릿 수, 항목별 글자수(공백 제외), 연구 요약 산문 5문장, 불릿 "~다" 종결, 첫째·둘째, 금지 표현, 마크다운 강조, 인라인 수식, 그림 언급,
  인용 위치(연구 필요성만)·형식·3회 이상 반복, **인용이 학술 카드에 실재하는지**.
- 결과는 측정값이 붙은 지시문("실험 및 평가: 603자 (목표 300, 허용 345, 상한 405)…") → Writer 가 지목된 것만 수정 → 재검사, 최대 2회.
  수정본 오류가 늘면 이전 본 유지. Writer 초안·재작성·Reporter 정리본 뒤에 붙음. state `lint_writer`, `lint_reporter`.
- **강도 (09-09 완화, config LINT_*)**: 글자수 +15% 통과 / +15~35% 경고 / +35% 초과 오류, 부족 -30% 아래만 경고, 전체 +20% 초과만 오류,
  불릿 수 지정 +1~2 경고 / +3 이상 오류(사용자 지정). 구조·금지 표현·강조·인용·종결어미는 오류.
- 근거 실측: 과거 산출물 6건 전부 분량 위반(전체 104~157%), PASS 본도 불릿 수·인용 반복 위반.

### 3.2 참고문헌 생성 + 인용 검증 — `code/references.py` (신규)
- 본문 `[Author et al., Year]` 를 등장 순서로 추출 → 학술 카드와 제1저자 성·연도 대조 → "성 이니셜, 성 이니셜 외 (연도). 제목. 학술지. arXiv:ID 또는 DOI. URL".
- 첫 토큰이 성이라 조판기(build.py)의 인용 배지 링크가 걸림. 카드에 없는 인용은 검사기가 Writer 에 되돌리고, 최종까지 남으면 표기만 제거해 1:1 유지.
- `PROMPT_WRITER` "■ 참고문헌" → 작성하지 않음. state `references_count`.

### 3.3 Reporter 축소 — `nodes_reviewer.reporter`, `code/proposal_cleanup.py` (신규), `PROMPT_REPORTER` 삭제
- 1차(09-08): 증거 입력·참고문헌 작성 규칙 제거. 계획서만 받아 정리(인용 위치·그림 표기·소제목·요약 산문화) → 검사 루프 → 참고문헌 부착.
- **2차(09-09, 사용자 결정 "심사 뒤에 내용을 바꾸는 것은 부적절")**: 자유 정리 LLM 호출을 없앴다. Reporter 가 하던 다섯 가지 중 넷은
  검사기 항목과 겹쳤고(인용 위치·그림 표기·소제목·요약 산문화), 남은 "문체·정합성 재점검" 이 곧 의미가 바뀌는 지점이었다.
  - **표기 정리(코드)**: 독립 `[그림 N]` 불릿·캡션 줄·이미지 문법 줄 삭제, 연구 필요성 밖 인용·3회째 반복·카드에 없는 인용의 표기만 삭제,
    `**강조**` 제거, 참고문헌 섹션 제거. 문장 속 그림 언급·연도 없는 인용 같은 애매한 경우는 남겨 검사기가 지목한다.
  - 양식 검사 → **오류가 있을 때만** 위반 수정 LLM(≤2회). 심사 통과본은 Writer 단계에서 같은 검사를 거쳤으므로 대개 0회.
  - **변경 범위 가드**(`lint_loop`, `LINT_FIX_MAX_LINES_PER_ISSUE=4`): 수정본을 줄 단위 diff(difflib)로 재어 허용 줄 수 max(8, 4×지목 건수)를
    넘으면 버리고 이전 본 유지. "지목되지 않은 곳은 바꾸지 마라" 를 프롬프트가 아니라 코드가 보증한다. Writer 단계(초안 직후)에는 적용하지 않음.
  - state `reporter_changes` = 심사 통과본 대비 변경 줄 (예 `2/138 lines (cleanup 2, lint-fix 0, llm calls 0, guard rejects 0)`).
    콘솔·프론트매터·Run Summary 에 기록.
  - Reporter LLM 호출 1~3회 → 0~2회. `PROMPT_REPORTER.md` 삭제, `prompts_loader` 목록에서 제거.

### 3.4 심사 재배치 — `PROMPT_REVIEWER_A/B`, `PROMPT_EDITOR`, `nodes_reviewer.py` (09-09)
- **Reviewer A(내용)**: 근거·섹션 간 정합성 9항목·데이터 구체성·논거. 검증 검색(쿼리 3 × Tavily·arXiv = 6회) 유일 담당.
- **Reviewer B(가독성)**: 이해 가능성·논리 흐름·불릿 계층·중복·모듈 상세 수준 균질성·설득력·연구 요약 직관성·**AI 티 나는 표현**(대체 문구 제시). 검색 없음(`REVIEWER_B_SEARCH=False`).
- 코드가 잡는 형식·금지 표현·구조·인용 형식은 두 프롬프트에서 제거. 세 프롬프트 모두 한국어(VERDICT/FEEDBACK 표식은 영어).
- **Editor**: 계획서 본문을 받아 문서 순서로 "위치 / 인용 / 문제 / 수정 방향 / 출처(내용 A·가독성 B·공통)" 정리. 형식 지적 제외.
- **판정은 코드**: 각 리뷰어 답변의 `VERDICT:` 를 `parse_verdict()` 로 읽어 `review_a_passed / review_b_passed` 저장, `review_passed = 둘 다 PASS`.
  Editor LLM 의 FINAL_VERDICT 는 참고(다르면 로그).

## 4. 그래프 전후

```
[이전] … collector A·B·C → writer → plot_framework ⇄ writer_plot_review → reviewer_a → reviewer_b → editor ─┬ REVISE → writer
                                                                                                          └ PASS → reporter → END
[지금] … collector A·B·C → writer(+검사) → reviewer_a(검색) → reviewer_b → editor(코드 판정) ─┬ REVISE → writer(재작성+검사)
                                                                                            └ PASS/한도 → plot_framework(1회) → reporter(+검사+참고문헌) → END
```
노드 19 → 18 (`writer_plot_review` 는 `PLOT_REVIEW_ENABLED=True` 일 때만 추가).

## 5. 파일 변경 목록

| 구분 | 파일 |
|---|---|
| 신규 코드 | `code/diagram_agent.py`, `code/llm_json.py`, `code/research.py`, `code/scholar.py`, `code/proposal_lint.py`, `code/lint_loop.py`, `code/references.py`, `code/proposal_cleanup.py` |
| 수정 코드 | `code/config.py`, `clients.py`, `search.py`, `nodes_collector.py`, `nodes_writer.py`, `nodes_reviewer.py`, `graph.py`, `state.py`, `output.py`, `prompts_loader.py`, `main.py` |
| 신규 프롬프트 | `PROMPT_DIAGRAM_SELECT_TYPE`, `PROMPT_DIAGRAM_AUTHOR_WORKFLOW`, `PROMPT_DIAGRAM_REPAIR`, `PROMPT_CARDS_WEB`, `PROMPT_CARDS_SCHOLAR`, `PROMPT_WRITER_LINT_FIX` |
| 수정 프롬프트 | `PROMPT_COLLECTOR_A/B/C_QUERY`, `PROMPT_EVALUATE_A/B/C`, `PROMPT_WRITER`, `PROMPT_WRITER_REVIEW`, `PROMPT_WRITER_PLOT_REVIEW`, `PROMPT_REVIEWER_A`, `PROMPT_REVIEWER_B`, `PROMPT_EDITOR` |
| 삭제 프롬프트 | `PROMPT_REPORTER` (09-09, Reporter 자유 정리 제거 — 3.3) |
| 레거시(미사용, 보존) | `PROMPT_PLOT_SPEC.md`, `skills/plotting-agent/scripts/render_graphviz.py` 외 Graphviz·matplotlib 스크립트 |
| 동봉 | `skills/plotting-agent/archify/` (Archify v2.17) |
| 단독 실행 스크립트 | `skills/plotting-agent/scripts/run_archify_agent.py`, `skills/deepresearch/run_research_stage.py` |
| 테스트 | `tests/test_research.py`, `test_scholar.py`, `test_diagram_agent.py`, `test_write_stage.py`, `test_review_stage.py`, `test_finalize_stage.py`, `tests/README.md`, `tests/fixtures/` |
| 문서 | `skills/plotting-agent/skill.md`, `skills/deepresearch/agents/{collector-a,b,c,writer,reporter,reviewer-a,reviewer-b,editor}/skill.md`, `requirements.txt`, `deepresearch_colab.ipynb`(셀 0·3), `../DiagramAgent/DiagramAgent.md`(구현 위치 메모) |

## 6. 설정값 (`code/config.py`)

| 항목 | 값 | 의미 |
|---|---|---|
| MAX_SEARCH | 3 | collector 라운드 상한 (갭 분석 충분 시 조기 종료) |
| TAVILY_MAX_RESULTS / SEARCH_DEPTH | 5 / advanced | 본문 포함 수집 |
| LINER_MAX_RESULTS / ARXIV_MAX_RESULTS | 15 / 8 | 쿼리당 결과 |
| ABSTRACT_SOURCES | ("arxiv",) | 초록 보강 출처 (openalex, semanticscholar 는 꺼짐) |
| SCHOLAR_BACKEND | auto | LINER_API_KEY 유무로 liner/arxiv |
| ARXIV_MIN_INTERVAL / ARXIV_429_WAIT | 4초 / 300초 | 관문 간격, 429 대기 |
| EVIDENCE_TOP_N / EVIDENCE_CHAR_LIMIT | A12 B12 C15 / 12,000 | writer 에 넘기는 카드 |
| MIN_RELEVANCE | 2 | 카드 채택 하한 |
| MAX_LINT_FIX_ROUNDS | 2 | 양식 수정 루프 |
| LINT_LENGTH_WARN / ERROR / UNDER_WARN | 0.15 / 0.35 / 0.30 | 글자수 경고·오류·부족 |
| LINT_TOTAL_ERROR | 0.20 | 전체 글자수 오류 |
| LINT_BULLET_SLACK | 2 | 불릿 초과 허용 |
| LINT_FIX_MAX_LINES_PER_ISSUE | 4 | Reporter 수정본 변경 줄 가드 (허용 = max(8, 4×지목 건수)) |
| REVIEWER_B_SEARCH | False | B 무검색 |
| PLOT_REVIEW_ENABLED / MAX_PLOT_ROUNDS | False / 2 | Writer 스펙 검토 루프 |
| MAX_DIAGRAM_REPAIR_ROUNDS | 3 | Archify 수리 루프 |

환경변수: `OPENAI_API_KEY`(필수), `TAVILY_API_KEY`(필수), `LINER_API_KEY`(선택), `ARCHIFY_HOME`, `CHROME_PATH`, `SCHOLAR_BACKEND`, `S2_API_KEY`·`OPENALEX_MAILTO`(해당 출처를 켰을 때만).

## 7. 검증 상태

- 모의 LLM·모의 Tavily·모의 Liner·가짜 arXiv 로 여섯 테스트 스위트 전부 통과 (`python tests\test_*.py`).
  Archify 검증·렌더와 Playwright 추출, OpenAlex 조회 1건, PDF 조판은 실제로 실행해 확인.
- **미검증**: 실제 OpenAI·Tavily·Liner 호출(키 없음). arXiv 는 네트워크 429 로 라이브 확인 불가(날짜 필터 문법 포함, 실패 시 무필터 폴백).
- 첫 실제 실행에서 볼 것: 로그의 "갭 분석" 줄, `workspace/research/cards_*.json` 의 요지 충실도, Run Summary 의 `Format lint` 두 줄이 `(clean)` 인지, `References` 수,
  Reviewer B 의 AI 표현 지적이 과하지 않은지.

## 7-1. Scope 단계 재설계 (09-09)

- `code/nodes_scope.py` 재작성. Test_folder/ScopeAgent 실험의 재서술·진단·정합성 프롬프트를 LangGraph 노드로 옮김.
  - `scope`: 초록을 Problem/Solution 으로 재서술(`PROMPT_SCOPE_RESTATE`, 신규), 비어 있는 요소를 질문 후보로.
  - `clarify`: 1회차 Problem → 2회차 Solution → 3회차 정합성. **열린 질문 하나 + 참고 예시 2~3개**(사용자 결정: 보기 대신 예시).
    답은 자유 입력 / 예시 번호 / Enter(건너뜀). 설계를 바꿀 공백이 없으면 조기 종료. `PROMPT_SCOPE_CLARIFY` 재작성.
  - `revise_abstract` → `human_abstract_feedback`: 초록만 확인 (Enter=수정안 확정, 텍스트=그대로 초록).
  - `write_brief`: 확정 초록으로 **구조화 브리프 JSON**(`PROMPT_RESEARCH_BRIEF` 재작성) — 연구 질문·Problem·Solution·범위 안/밖·영어 핵심어·
    데이터 후보(이름·제공 주체·형태·규모·확인/추정)·평가 후보(태스크·지표·비교 대상)·기존 접근 계열·미해결 이유·제약·가정·미해결 질문.
    **사용자에게 보이지 않는 내부용**(사용자 결정). `workspace/research/brief.md` 에 저장. 렌더링 텍스트는 `research.parse_brief` 호환.
  - `supervisor`: JSON 출력(`PROMPT_SUPERVISOR` 재작성), 마커 파싱은 폴백.
- 하류 연결: `research.brief_section` 이 DATA/EVALUATION CANDIDATES·EXISTING APPROACHES·UNRESOLVED REASON 을 collector 프롬프트에 전달.
  `PROMPT_WRITER`/`WRITER_REVIEW` 에 "브리프 항목의 사용" 지침(데이터 후보→데이터 수집, 평가 후보→실험 및 평가, 기존 접근→계열 유형화,
  미해결 이유→논거, 가정·추정 항목은 추정임 명시).
- 그래프: `scope → clarify ⇄ human_feedback → revise_abstract → human_abstract_feedback → write_brief → supervisor` (연결 자체는 원래와 같음).
- LLM 호출: 재서술 1 + 질문 ≤3 + 초록 수정 1 + 브리프 1 + supervisor 1 = 최대 7회 (이전 최대 6회). 사용자 입력: 질문 ≤3 + 초록 확인 1 (변화 없음).
- 테스트 `tests/test_scope_stage.py` (모의 LLM 7회 흐름, 파서 호환, 그래프, 프롬프트 포맷). 실제 LLM 미검증.

## 8. 남은 결정·후속 과제

- **인용 허용 위치**: 지금은 연구 필요성에만. 실험 및 평가(베이스라인·지표 출처)에도 허용하면 참고문헌이 1~3편 → 5~8편. 양식 결정이라 보류.
- **Reviewer 에 카드 제공**: A 가 수집 카드를 함께 보면 "제공된 검색 결과로 확인되지 않음" 판정이 수집 근거와 대조된다. 미구현.
- **간트차트**: 요구사항 두 종류 중 워크플로만 구현. Archify 에 간트가 없어 Mermaid 등 별도 경로 필요.
- **plot_round 표기**: 도해가 1회 생성이므로 프론트매터 `plot_rounds` 는 항상 1.
- Liner 키 발급 후 `run_research_stage.py --only C` 로 카드 품질(스니펫 비율) 확인. 스니펫 비율이 높으면 `ABSTRACT_SOURCES` 에 openalex 추가 검토.

## 9. 폴더 재구성 — `Drafter-main` → `Drafter_0909` (09-09)

사용자 결정: 단계별 폴더(Scope·Research·Write·Review·Finalize), 프롬프트 분리, 중간/최종 산출물 분리, 실행별 `runtime/<시각>/` 채택,
과거 산출물·Colab 관련 파일 폐기. 파일 이동과 함께 import 를 패키지 경로로 재작성하고 죽은 코드를 정리했다. 그래프 토폴로지와 노드 동작은 그대로다.

### 9.1 대응표

| 이전 (`Drafter-main/`) | 지금 (`Drafter_0909/`) |
|---|---|
| `main.py` | `main.py` (API 키는 `.env`, 실행 폴더 생성, 요약에 실행 폴더 표시) |
| `code/config.py` | `code/core/config.py` (튠 값만) + `code/core/paths.py` (폴더 배치 · 실행 폴더 API, 신규) |
| `code/state.py`, `clients.py`, `llm_json.py`, `graph.py`, `output.py` | `code/core/` 동일 이름 (`output._initial_state` → `initial_state`) |
| `code/prompts_loader.py` | `code/core/prompts.py` (하위 폴더 재귀 로드) |
| `code/nodes_scope.py` | `code/scope/nodes.py` (supervisor 제외) |
| `nodes_scope.supervisor` | `code/research/supervisor.py` |
| `code/nodes_collector.py`, `research.py`, `search.py`, `scholar.py` | `code/research/collectors.py`, `cards.py`, `search.py`, `scholar.py` |
| `code/nodes_writer.writer` | `code/write/writer.py` |
| `code/proposal_lint.py`, `lint_loop.py` | `code/write/lint.py`, `lint_loop.py` (`count_changed_lines` 는 lint_loop 로) |
| `code/nodes_reviewer.py` (A·B·Editor) | `code/review/nodes.py` |
| `nodes_reviewer.reporter` | `code/finalize/reporter.py` |
| `nodes_writer.plot_framework` | `code/finalize/diagram.py` |
| `code/diagram_agent.py`, `proposal_cleanup.py`, `references.py`, `export_pdf.py` | `code/finalize/diagram_agent.py`, `cleanup.py`, `references.py`, `export_pdf.py` |
| `Drafter presentation/` (build.py · assets) | `code/finalize/presentation/` (`--build-dir`, 절대경로 입력 지원) |
| `code/prompts/*.md` | `prompts/{scope,research,write,review,finalize}/*.md` |
| `skills/plotting-agent/archify/` | `vendor/archify/` |
| `skills/deepresearch/run_research_stage.py`, `skills/plotting-agent/scripts/run_archify_agent.py` | `scripts/` (+ `preflight.py`, `export_pdf.py` 신규) |
| `skills/deepresearch/agents/*/skill.md`, `skills/plotting-agent/skill.md`, `CHANGES_2026-09.md` | `docs/agents/*.md`, `docs/plotting-agent.md`, `docs/CHANGES_2026-09.md` |
| `workspace/research/`, `workspace/figures/`, `Drafter presentation/{input,build}/` | `runtime/<YYYYMMDD_HHMMSS>/{research,figures,pdf_build}/` |
| 루트의 `research_paper_*.md/.pdf` | `final/research_paper_<실행시각>.md/.pdf` (실행 폴더와 같은 시각) |

### 9.2 제거한 것

- 꺼져 있던 Writer 도해 검토 루프: `writer_plot_review`, `route_after_writer_plot_review`, `PLOT_REVIEW_ENABLED`, `MAX_PLOT_ROUNDS`,
  state `plot_feedback/plot_round/plot_agreed/framework_spec`, `PROMPT_WRITER_PLOT_REVIEW.md`, 프론트매터 `plot_rounds/plot_verdict`.
  도해 파일명은 `framework.{png,svg,html,spec.json}` (실행 폴더가 갈라 주므로 라운드 번호 불필요).
- 미사용: `PROMPT_PLOT_SPEC.md`, `search._is_sufficient_response`, `nodes_scope.BRIEF_KEYS`, 답변 A/B/C 하위 호환(`_LEGACY_LABELS`),
  supervisor 의 옛 마커 파서(JSON 프롬프트라 도달 불가), `export_pdf` 의 "최신 framework_N 추정" 폴백, `diagram_agent`/`export_pdf` 의 `__main__` (scripts/ 로).
- 레거시 스크립트·문서: `skills/plotting-agent/scripts/{render_graphviz,render_matplotlib,render_diagram,paperbanana_render}.py`, `skills/plotting-agent/references/`,
  Colab 셤 `skills/deepresearch/{deepresearch,__init__}.py`, `deepresearch_colab.ipynb`.
- 산출물: 과거 `research_paper_*` 10건(테스트 표본 1건은 `tests/fixtures/sample_proposal.md` 로), `workspace/`, 조판 중간 파일, `proposal.pdf`.

### 9.3 검증

- 일곱 스위트를 새 위치에서 실행해 통과 (`tests/README.md`). 산출물은 `tests/out/<stamp>/` 로 격리.
- 모의 LLM·모의 검색으로 `main.run()` 을 처음부터 끝까지 돌리는 `tests/test_pipeline_smoke.py` 추가 (그래프 연결 · 인터럽트 · 실행 폴더 · 저장 확인).

### 9.4 `.env` 로 키·모델·백엔드 지정 (09-09, 사용자 요청)

- `.env`(`.env.example` 참고)는 `core.config` 가 **임포트 시점**에 `load_env_file()` 로 환경변수에 올린다 (이미 있는 변수는 유지, `ENV_LOADED` 에 개수).
  그래서 config 가 임포트 때 읽는 `SCHOLAR_BACKEND`·`CHROME_PATH`·`ARCHIFY_HOME` 과 실행 때 읽는 `OPENAI_API_KEY`·`OPENAI_MODEL`·`LINER_API_KEY` 가 모두 `.env` 값을 본다.
- **`OPENAI_MODEL`** 로 LLM 모델을 바꾼다. `clients.resolve_llm_model(explicit)` = 인자 → `OPENAI_MODEL` → `config.DEFAULT_LLM_MODEL`(gpt-5.1).
  `init_clients(model=None)` 기본값과 `scripts/*.py --model` 기본값이 이를 따른다. 모든 에이전트가 같은 모델을 쓴다.
- 테스트는 `DRAFTER_SKIP_DOTENV=1` 을 설정해 `.env` 를 읽지 않는다 (실제 키가 있어도 arXiv 경로 등 검증 결과가 바뀌지 않게).

### 9.5 표지 부제·키워드 자동화 — `finalize/cover.py` (신규 노드), `PROMPT_COVER_SUBTITLE` (신규) (09-09, 사용자 요청)

- 발견: `main.py` 의 `PDF_SUBTITLE`/`PDF_KEYWORDS` 와 렌더러 `build.py` 의 `DEFAULT_META` 가 세렌디피티 예시 초록 값으로 하드코딩되어 있어,
  초록을 바꾸면 표지에 옛 부제·키워드가 실릴 수 있었다 (키워드를 비우면 렌더러 기본값이 새어 나옴).
- 그래프: `plot_framework → reporter → cover → END`. cover 노드는 최종본의 연구 요약 **전체를 읽고** LLM 1회로 부제 한 문장을 만들고
  (사용자 지시: 첫 문장 발췌가 아니라 요약을 읽고 생성; 실패 시 첫 문장으로 대체), 키워드는 브리프 JSON 의 새 항목 `keywords_ko` 에서 가져온다
  (`PROMPT_RESEARCH_BRIEF` 에 항목 추가, `normalize_brief` 반영, 추가 LLM 호출 없음).
- state `cover_subtitle`·`cover_keywords` → 프론트매터 `subtitle`·`keywords` → `export_pdf` 가 인자(main `PDF_*`) → 프론트매터 → 요약 첫 문장 순으로 사용.
- `main.py`: `PDF_SUBTITLE = ""`, `PDF_KEYWORDS = []` (비우면 자동, 직접 정할 때만 채움). 사용자가 고치는 것은 `ABSTRACT`·`REQUESTS`·`PDF_AUTHOR`.
  `build.py` `DEFAULT_META` 의 부제·키워드·작성자 예시 값은 빈 값으로. Run Summary 에 Cover subtitle/keywords 줄 추가.
- 테스트: `test_finalize_stage` 6절(cover 노드: 요약 전체 입력, 키워드 정리, 실패 폴백), `test_scope_stage`(keywords_ko 정규화), `test_write_stage` 8절(그래프 꼬리),
  `test_pipeline_smoke`(프론트매터 subtitle/keywords).
- 수정: `export_pdf(work_dir=...)` 에 상대경로를 주면 `build.py`(자기 폴더에서 실행) 가 meta.json 을 못 찾던 문제. 절대경로로 바꿔 넘긴다 (test_diagram_agent E 가 상대경로로 검증).

### 9.6 첫 실제 실행(gpt-4o-mini)에서 드러난 문제 수정 (09-09)

실제 실행 결과: PDF "변환 실패" 보고 · 그림 "삽입 위치를 찾지 못함" · 양식 오류 8건 미해결 · 참고문헌 0건 · 심사 미통과. 원인과 조치:

- **렌더러 콘솔 인코딩**: `build.py` 가 PDF 를 다 쓴 뒤 완료 메시지의 "✓" 를 cp949 콘솔에 출력하다 `UnicodeEncodeError` 로 죽어 종료 코드 1 → 부모가 실패로 보고.
  조치: `build.py` 가 stdout 을 UTF-8 로 재설정하고 완료 메시지를 ASCII 로; `export_pdf` 는 자식 프로세스에 `PYTHONIOENCODING=utf-8` 을 넘기고,
  종료 코드가 0 이 아니어도 PDF 파일이 새로 생겼으면 성공으로 처리(경고만). pdfplumber 의 FontBBox 경고는 억제.
- **경량 모델의 양식 베끼기**: gpt-4o-mini 가 `## 1. 연구 배경 — 770자`, `  ● 연구 주제(문제 정의) — 350자`, `2) 모듈 1:` 처럼 작성양식의 기호·분량 표시를
  그대로 출력하고 웹 카드 ID(`[A-06, A-07]`)를 인용. 검사기는 이를 "양식 밖 섹션 4 + 섹션 누락 4" 로만 보고해 수정 프롬프트가 고치지 못함(8 → 8 → 8).
  조치: (1) `lint._norm_key` 가 번호("3.2")·주석("— 770자")·끝 괄호를 떼어 섹션을 인식하고, 새 검사 `heading_annotation`(제목 주석)·`template_marker`(■/● 줄)·
  `module_structure`("N) 모듈 N" 줄)·`card_id_citation`(카드 ID) 이 고칠 방법을 그대로 지목한다. (2) `PROMPT_WRITER` 에 **[최종 출력 구조]** 제목 골격을 넣고
  "■/●/분량 표시는 설명이며 출력하지 않는다, 모듈은 #### 소제목, 카드 ID 금지" 를 명시. `PROMPT_WRITER_REVIEW`·`PROMPT_WRITER_LINT_FIX` 에도 같은 규칙.
  (3) Reporter 표기 정리가 카드 ID 표기를 기계적으로 제거. (4) `.env.example`·README 에 경량 모델 주의 문구.
- **그림 삽입 폴백**: `### 제안 방법` 을 번호·덧말이 붙어도 찾고, 소제목이 전혀 없으면 `## 연구 방법론` 절 머리에 넣는다.
- 테스트: `test_write_stage` 3절에 세 규칙 추가 + `_norm_key` 관용성, `test_finalize_stage` 1절(카드 ID 제거)·7절(그림 삽입 폴백).

### 9.7 도해 폴백: showcase 실패 시 standard 품질 (09-09)

- 실제 실행(16:38)에서 Archify showcase 검증이 `composition/ambiguous-corridor`(무관한 엣지 두 개가 같은 통로) 로 실패, LLM 수리 3회로도 미해결 →
  그림 없이 조판됨. 같은 스펙은 `--quality standard` 로는 9/9 통과·렌더 가능했다.
- 조치: 서브그래프에 `downgrade` 노드 추가 (`validate` 한도 도달 → standard 로 재검증 → 통과 시 deliver, 실패 시 error). `DiagramConfig.fallback_quality`,
  `config.DIAGRAM_FALLBACK_QUALITY="standard"`. `checks_passed` 에 `(standard)` 표시, `note` 로 사유 전달, deliver 캐시 키에 품질 포함.
- 안내 문구 수정: 그림이 없을 때 "캡션만 표기됨" 이라 했으나 실제로는 그림 불릿을 넣지 않으므로 캡션도 없다 → "그림 없이 조판" 으로.
- 테스트: 실패 스펙을 `tests/fixtures/corridor_conflict.workflow.json` 으로 보존, `test_diagram_agent` F 절(폴백 렌더, LLM 추가 호출 0).

### 9.8 양식 단일 원본 — `code/write/spec.py` (신규) (09-09)

**문제**: 계획서 양식의 숫자가 두 곳에 있었다 — `write/lint.py` 의 `SECTION_SPEC`·`TOTAL_CHARS` 등과
`PROMPT_WRITER`·`PROMPT_WRITER_REVIEW`·`PROMPT_WRITER_LINT_FIX` 의 `[작성양식]`·`[분량 규칙]` 본문(같은 값이 세 벌).
한쪽만 고치면 Writer 는 프롬프트대로 쓰는데 검사기는 다른 기준으로 지적하므로 **고칠 수 없는 위반**이 되고,
수정 루프가 `MAX_LINT_FIX_ROUNDS` 를 다 쓰고 `(unresolved)` 로 끝난다 (LLM 호출 2회 낭비).
실제로 두 개의 잠재 불일치가 있었다: 제안 방법 930 ≠ 개요 160 + 모듈 3×250 = 910, 전체 3,440 vs 검사기가 재는 본문 합 3,400.

**조치**

- `code/write/spec.py` 신규 — 양식의 유일한 출처. 섹션·항목·글자수·불릿 수, 모듈 라벨·분량,
  연구 요약 문장 수, 금지 표현, 인용 규칙(허용 항목·반복 한도), 분량 허용 오차.
  - 상위 항목 글자수는 **하위 항목의 합으로 계산**한다 (부모·자식이 어긋난 목표를 갖는 조합을 없앤다).
  - `BODY_CHARS`(검사기가 재는 본문 = 3,380) 와 `TOTAL_CHARS`(프롬프트가 알리는 전체 = 제목 40 + 본문 = 3,420) 를 구분.
    검사기는 `# 연구명` 줄을 세지 않으므로 종전의 3,440 기준은 약 40자만큼 느슨했다.
  - `_self_check()` 가 임포트 시점에 정합성을 검사한다: 섹션 = 항목 합, 제안 방법 = 개요 + 모듈,
    모듈 = 하위 3항목 합, **세부 목표 불릿 = 모듈 수 = 학술적 기여 불릿**(프롬프트 [섹션 간 정합성 제약] 1·2 가 요구),
    인용 허용 항목이 양식에 실재. 어긋나면 임포트가 실패한다.
  - `prompt_vars()` / `format_prompt()` / `render_length_rules()` — 프롬프트에 값을 주입한다.
- `write/lint.py` 는 자기 사본을 버리고 `spec` 에서 임포트(하류 `finalize/cleanup.py`·`references.py` 용으로 재수출).
  하드코딩되어 있던 메시지 문구(`40자 내외`, `지정 5문장`, `모듈 1·2·3`, `연구 필요성에만 허용`, 모듈 라벨)도 spec 에서 만든다.
- 프롬프트 세 개는 숫자를 지우고 자리표시자로 바꿨다: `{chars[연구 주제]}` `{bullets[연구 주제]}` `{per_bullet[세부 목표]}`
  `{module_headings}` `{module_labels_arrow}` `{summary_sentences}` `{length_tolerance_pct}` `{forbidden_emphasis}` `{length_rules}` 등.
  `PROMPT_WRITER_REVIEW` 의 `[분량 규칙]` 목록은 `render_length_rules()` 가 통째로 만든다.
  자리표시자가 빠지면 `KeyError` 로 즉시 실패한다 — 어긋난 프롬프트가 조용히 LLM 에 나가지 않는다.
- 호출 지점: `write/writer.py`(초안·재작성), `write/lint_loop.py`(위반 수정) → `spec.format_prompt(...)`.
  프롬프트를 직접 포맷하던 테스트 3곳(`test_scope_stage`·`test_research`·`test_scholar`)도 같이 바꿨다.
- 테스트: `test_write_stage` 0절 신규 —
  (1) `lint` 의 상수가 `spec` 과 동일, (2) `.md` 에 숫자가 아니라 자리표시자가 있음, (3) 세 프롬프트가 빠짐없이 렌더됨,
  (4) `[작성양식]` 에 산문으로 남긴 세부 배분(100+180+70 …)의 합이 항목 목표와 일치,
  (5) **spec 값만 읽어 만든 문서가 오류·분량경고 0** — 프롬프트가 요구하는 대로 쓰면 검사기를 통과한다는 뜻.
  `spec` 을 고치면 (5)의 문서도 함께 바뀌므로, 양식 변경이 검사기와 어긋나면 이 절이 실패한다.

**확인**: 오프라인 7개 스위트 전부 통과. `학술적 기여` 230 → 250 으로 한 줄만 고쳤을 때
섹션 합(350→370)·본문(3,380→3,400)·전체(3,420→3,440)·프롬프트의 `각 75자 → 각 80자` 가 모두 따라오고 테스트도 그대로 통과함을 확인.
`MODULE_COUNT`·`PROPOSAL_CHARS`·`SUMMARY_SENTENCES` 를 어긋나게 두면 `_self_check()` 가 `AssertionError` 로 막는 것도 확인.

