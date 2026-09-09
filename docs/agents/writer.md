---
name: writer
description: deepresearch 파이프라인의 연구개발계획서 작성 에이전트. 세 Collector 가 선별한 출처 카드(background_data, method_data, arxiv_data)와 브리프를 근거로 국내 연구개발계획서 양식(연구 요약 / 1. 연구 배경 / 2. 연구 목표 / 3. 연구 방법론(모듈 1~3) / 4. 기대 효과 및 활용 방안)의 개조식 초안을 쓴다. 초안과 재작성 뒤에는 코드 양식 검사기(write/lint.py)가 구조·불릿 수·글자수·문체·표기·인용을 측정하고, 위반만 고치는 LLM 호출을 최대 2회 돈다. Editor 의 REVISE 판정 후에는 editor_feedback 을 반영해 재작성한다.
---

# Writer Agent

## 역할

출처 카드를 근거로 **국내 연구개발계획서 양식**의 초안을 개조식으로 쓴다. 참고문헌은 쓰지 않는다
(본문 인용을 기준으로 코드가 학술 카드에서 생성한다). 초안 완성 후 plotting-agent 와 다이어그램 검토 루프에 들어간다.

## 호출 시점

| 시점 | 프롬프트 | 입력 | 뒤따르는 처리 |
|---|---|---|---|
| 최초 초안 | `PROMPT_WRITER` | 초록, 요청, 브리프, 카드 3채널 | 양식 검사 → 수정 루프 |
| 심사 후 재작성 | `PROMPT_WRITER_REVIEW` | + 현재 계획서, `editor_feedback` | 양식 검사 → 수정 루프 |
| 양식 수정 | `PROMPT_WRITER_LINT_FIX` | 계획서 + 코드가 측정한 위반 목록 | 재검사 (최대 MAX_LINT_FIX_ROUNDS=2) |

## 출력

- `research_plan`: 계획서 본문 (양식 검사를 거친 본)
- `lint_writer`: 검사 요약. 예 `errors 9 → 2 → 0, warnings 3 (clean)`. `(unresolved)` 면 2회 수정 뒤에도 오류가 남은 것
- `plot_agreed` / `plot_feedback`: 다이어그램 검토 결과

## 양식 검사 (code/write/lint.py) 가 재는 것

| 구분 | 항목 |
|---|---|
| 구조 | 제목, `##` 섹션과 `###` 항목의 존재·순서·명칭, 모듈 1~3 각 상위 불릿 3개(입력과 출력의 정의 → 핵심 메커니즘 → 채택 근거), 양식 밖 소제목 |
| 개수 | 항목별 상위 불릿 수 (연구 주제 3, 연구 필요성 4, 최종 목표 1, 세부 목표 3, 데이터 수집 3, 제안 방법 개요 2, 실험 및 평가 4, 학술적 기여 3, 실용적 활용 2) |
| 분량 | 항목별 글자수(공백 제외) ±15%, 전체 3,440자. 초과는 오류, 부족은 경고(근거 없는 보강 방지) |
| 문체 | 연구 요약 산문 5문장, 그 외 불릿 "~다" 종결 금지, 첫째·둘째 나열 금지 |
| 표기 | 금지 표현, 마크다운 강조, 인라인 수식, 그림 언급 |
| 인용 | 연구 필요성 밖 인용, 연도 없는 인용, 같은 출처 3회 이상, **학술 카드에 없는 인용** (제1저자 성·연도 대조) |

측정값이 그대로 수정 지시가 된다 ("실험 및 평가: 603자 (목표 300, 허용 345)"). Reviewer A 는 이 항목들을 심사하지 않고
근거·논리·정합성·항목 규칙·데이터 구체성만 본다.

## 인용 규칙

- 인용은 연구 필요성의 계열별 유형화에만, 불릿 말미에 `[Author et al., Year]`. 같은 출처 최대 2회.
- 반드시 학술 카드(C-xx)에 있는 논문의 제1저자 성과 연도로 쓴다. 카드에 없는 인용은 검사기가 되돌려 보내고,
  최종 단계까지 남으면 표기만 제거된다.

## 도해와의 관계

```
writer (초안+검사) → reviewer_a → reviewer_b → editor ─ REVISE → writer (재작성+검사)
                                                       └ PASS → plot_framework (심사 통과 본문으로 1회) → reporter
```

도해는 심사가 끝난 뒤 `code/finalize/diagram.py` 가 한 번 그린다. Writer 는 도해에 관여하지 않는다.

## 프롬프트 참조

`prompts/` → `PROMPT_WRITER`, `PROMPT_WRITER_REVIEW`, `PROMPT_WRITER_LINT_FIX`
구현: `code/write/writer.py`, `code/write/lint_loop.py`, `code/write/lint.py`
