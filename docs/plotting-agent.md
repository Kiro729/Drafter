---
name: plotting-agent
description: Drafter 파이프라인의 연구 프레임워크 다이어그램 생성 스킬 (Archify 기반). Writer 가 쓴 연구계획서의 "연구 방법론" 절을 입력받아 LLM 이 Archify workflow JSON 스펙을 작성하고, Archify 검증 게이트(9개 검사)를 통과할 때까지 진단 기반으로 수리한 뒤, HTML 을 렌더해 SVG/PNG 를 추출한다. graph.py 의 plot_framework 노드가 호출하며, PNG 는 조판 단계에서 [그림 1] 로 삽입된다.
---

# Plotting Agent (Archify 기반)

## 왜 Archify 인가

이전 구현은 Graphviz(dot) 였다. 두 가지가 문제였다.

- **한글 라벨 불가.** 기본 폰트 Helvetica 에 한글 글리프가 없어 라벨을 영어로 강제했다.
  한국어 계획서에 영어 그림이 실렸다.
- **레이아웃 검증 없음.** 엣지 겹침, 라벨 충돌, 잘림이 그대로 통과했다.

Archify(`tt-a1i/archify`, MIT, v2.17) 는 JSON 스펙을 받아 검증 게이트를 통과한 것만 렌더한다.
엣지 겹침·라벨 충돌·뷰포트 초과가 **좌표와 수리 지침이 붙은 JSON 진단**으로 반려되고,
그 진단을 LLM 에 다시 넘겨 최소 수정하는 루프가 사람 없이 돈다. 한글 라벨도 지원한다.

## 구성

| 파일 | 역할 |
|---|---|
| `code/finalize/diagram_agent.py` | LangGraph 서브그래프. select_type → author → validate ⇄ repair → deliver → export → finalize |
| `code/finalize/diagram.py` `plot_framework` | 계획서에서 `## 3. 연구 방법론` 절을 잘라 `run_diagram_agent()` 호출, state 갱신 |
| `prompts/PROMPT_DIAGRAM_SELECT_TYPE.md` | 타입 선택. 지원 타입이 하나(workflow)뿐인 현재는 LLM 을 부르지 않고 통과 |
| `prompts/PROMPT_DIAGRAM_AUTHOR_WORKFLOW.md` | 스펙 작성 + `caption_ko`. 첫 시도에 9/9 통과한 스펙을 few-shot 으로 포함 |
| `prompts/PROMPT_DIAGRAM_REPAIR.md` | Archify 진단(`diagnostics[]`, `supportedFixes`) 기반 최소 수정 |
| `code/core/config.py` | `ARCHIFY_HOME`, `CHROME_PATH`, `MAX_DIAGRAM_REPAIR_ROUNDS`, `DIAGRAM_EXPORT_FORMATS` |
| `vendor/archify/` | Archify 패키지 사본 (Node CLI, 의존성 없음, 7.5MB). `ARCHIFY_HOME` 환경변수로 다른 위치 지정 가능 |
| `scripts/run_archify_agent.py` | 방법론 텍스트 파일 하나로 에이전트를 단독 실행 (API 키 필요) |

## 흐름

```
writer ──> reviewer_a ──> reviewer_b ──> editor ─┬─ REVISE ──> writer (재작성, ≤ MAX_REVIEW_ROUNDS)
                                                 └─ PASS/한도 ─> plot_framework ──> reporter ──> cover ──> END
                                                                    │
                                                                    │  run_diagram_agent(methodology_text, figure_id)
                                                                    ▼
                                     select_type → author → validate ─┬─ ok ──> deliver → export → finalize
                                                              ▲       └─ fail ─> repair ─┘  (≤ MAX_DIAGRAM_REPAIR_ROUNDS = 3)
                                                              └──────────────────┘
```

- 도해는 **심사가 끝난 본문**의 연구 방법론 절로 **한 번** 그린다 (2026-09-08 변경). 심사 전에 그리면 재작성마다
  다시 그려야 했고, Archify 검증 게이트가 형식을 보장하므로 Writer 가 스펙을 보고 다시 그리게 할 필요가 없어졌다.
- 안쪽 루프(validate ⇄ repair)가 **형식과 레이아웃**을 본다: 스키마, 겹침, 간격, 뷰포트.
- showcase 검증이 수리 3회 뒤에도 실패하면 **standard 품질로 한 번 더 검증·렌더**한다 (`DIAGRAM_FALLBACK_QUALITY`). standard 는 기본 검사 9개는
  그대로 하고 무관한 엣지의 통로 공유 같은 마감 검사만 빼므로, 그림이 빠지는 대신 마감이 덜 된 그림이 실린다. 결과에 `(standard)` 가 표시된다.
- Archify·Node·브라우저가 없으면 preflight 가 원인을 로그에 남기고 **그림 없이 파이프라인을 계속**한다.
  조판 단계는 그림이 없으면 캡션만 표기한다.

## 산출물 (`runtime/<실행시각>/figures/`)

| 파일 | 내용 |
|---|---|
| `framework.spec.json` | 검증을 통과한 Archify 스펙 (수리 중에는 마지막 시도본) |
| `framework.validate.json` | 마지막 `validate --json` 리포트. 실패 원인 추적용 |
| `framework.html` | `deliver` 결과. 자기완결형 인터랙티브 뷰어. 브라우저로 열어 확인 가능 |
| `framework.png` | 라이트 테마 고정, 약 4700×2700px (뷰포트 1600×1000 @2x). **PDF 조판에 삽입** |
| `framework.svg` | 듀얼테마(prefers-color-scheme 내장) 벡터. 보관·재사용용 |
| `framework.sha` | deliver 캐시 키. 같은 스펙이면 재렌더를 건너뛴다 |

state 로는 `framework_figure_path`(PNG), `framework_svg_path`, `framework_caption`,
`diagram_checks`("9/9"), `diagram_repair_rounds` 가 올라가고, 마크다운 프론트매터와 Run Summary 에 찍힌다.

## 런타임 요구

| 계층 | 요구 | 확인 |
|---|---|---|
| Archify CLI | Node.js >= 18 | `node --version` |
| SVG/PNG 추출 | Python `playwright` + Chromium | `pip install playwright && playwright install chromium` |
| 시스템 Chrome 사용 (선택) | `CHROME_PATH` 환경변수 | |

```bash
python scripts/preflight.py            # preflight: node · archify doctor · playwright
```

## 스펙 규칙 — 실측으로 확인된 것 (프롬프트에 반영됨)

- `meta.locale` **생략.** 허용값이 `en`, `zh-CN` 뿐이라 `ko` 는 검증 실패. 뷰어 UI 는 영어로 폴백되지만 정적 이미지엔 무관.
- 모든 노드에 `"width": 136`. 기본 92px 에 한글을 넣으면 글자가 축소된다.
- CJK 는 폭 계산에서 2단위. 레인 라벨 2~6자, 노드 라벨 4~8자, 엣지 라벨 2~6자.
- 노드 6~12개, `col` 0..5, `mainPath` 는 col 단조 증가.
- `route` 프리셋은 쓰지 않는다(간격 제약에 자주 걸린다). 코리도 충돌은 `bias` 0.25 부터.
- 범례는 `meta.legend.entries.<type>.label` 로 연구 어휘(수집 자료·연구 단계·분석 및 처리·검증·산출물)로 교체.
- `validate` 는 **실패해도 exit 0**. `ok` 필드로 판정한다. `diagnostics[].supportedFixes` 가 수리 루프의 입력이다.
- 수리 상한 3회. 3회로 안 되면 스펙이 과밀하다는 신호이므로 상한을 늘리지 않는다.
- `sanitize_spec()` 이 LLM 출력에서 `locale`, 라우팅 프리셋을 제거하고 `schema_version 2`, `quality_profile showcase`, `width 136` 을 보정한다.

## 단독 실행 (API 키 필요)

```bash
python scripts/run_archify_agent.py methodology.md
```

`methodology.md` 는 연구계획서의 `## 3. 연구 방법론` 절 텍스트다. 결과 파일은 `runtime/<실행시각>/figures/` 에 생긴다.

## 참고

- 설계 문서와 실측 기록: `../DiagramAgent/DiagramAgent.md`, `../DiagramAgent/prompt_diagram.md` (Drafter-main-0728 폴더)
- Archify 스키마·예제·규칙: `vendor/archify/schemas/workflow.schema.json`, `vendor/archify/examples/*.workflow.json`,
  `vendor/archify/references/authoring-contract.md`, `vendor/archify/SKILL.md`
