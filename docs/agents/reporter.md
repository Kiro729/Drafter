---
name: reporter
description: deepresearch 파이프라인의 최종 정리 단계. Editor 의 PASS 판정(또는 최대 심사 라운드 종료)과 도해 생성 뒤 실행된다. 심사를 통과한 research_plan 을 다시 쓰지 않는다. 코드가 표기(그림 표기·허용 위치 밖 인용·반복 인용·카드에 없는 인용·마크다운 강조·참고문헌 섹션)만 정리하고 양식을 검사한다. LLM 은 양식 오류가 남았을 때만 지목된 위반을 고치며, 수정본이 지목 범위를 넘게 바뀌면 코드가 버린다. 참고문헌은 본문 인용을 학술 카드와 대조해 코드가 생성해 붙인다. 결과는 research_paper 로 저장되고 조판 단계가 그림을 삽입한다.
---

# Reporter (Finalize)

## 역할

심사를 통과한 계획서를 **제출본으로 확정**한다. 다시 쓰는 단계가 아니며, 정리 LLM 도 없다.
심사가 끝난 뒤 문서의 의미가 바뀌지 않도록 LLM 은 양식 오류가 남았을 때만 부르고, 그때도 지목된 곳만 고쳤는지 코드가 확인한다.
그림은 본문에 넣지 않는다(프론트매터의 경로·캡션으로 조판 단계가 삽입).

## 처리 순서 (code/finalize/reporter.py `reporter`)

```
research_plan (심사 통과본)
  ──▶ ① 표기 정리 (코드, finalize.cleanup.mechanical_cleanup)
  ──▶ ② 양식 검사 (코드, write.lint.lint)
        └ 오류 있을 때만 ▶ 위반 수정 LLM (PROMPT_WRITER_LINT_FIX, 최대 2회) ▶ 변경 범위 가드 ▶ 재검사
  ──▶ ③ 참고문헌 생성·부착 (코드, references.attach_references)
  ──▶ research_paper
```

1. **표기 정리(코드)**: 독립 `[그림 N]` 불릿·캡션 줄·이미지 삽입 문법 줄 삭제, 연구 필요성 밖의 `[Author et al., Year]` 표기 삭제,
   같은 출처 3회째부터 삭제, 학술 카드에 없는 인용 삭제, `**강조**` 표식 제거, 기존 참고문헌 섹션 제거. 문장은 건드리지 않는다.
   문장 속 그림 언급이나 연도 없는 인용처럼 애매한 것은 남겨 검사기가 지목하게 한다.
2. **양식 검사(코드)**: Writer 와 같은 검사기. 구조·불릿 수·글자수·문체·표기·인용 위치·인용 실재 여부.
   심사 통과본은 Writer 단계에서 같은 검사를 거쳤으므로 대개 오류가 없고, 그러면 LLM 을 부르지 않는다.
   - 오류가 남았을 때만 지목된 위반 목록을 LLM 에 보내 고치게 한다(최대 `MAX_LINT_FIX_ROUNDS`=2회).
   - **변경 범위 가드**(`lint_loop`, `LINT_FIX_MAX_LINES_PER_ISSUE`=4): 수정본을 줄 단위 diff 로 재어
     허용 줄 수(= max(8, 4 × 지목 건수))를 넘으면 지목되지 않은 곳까지 다시 쓴 것으로 보고 버린다. 오류가 늘어난 수정본도 버린다.
3. **참고문헌 생성(코드)**: 본문 인용을 등장 순서로 카드와 대조해 `성 이니셜, 성 이니셜 외 (연도). 제목. 학술지. arXiv:ID 또는 DOI. URL`
   형식으로 만든다. 첫 토큰이 제1저자 성이라 조판기가 본문의 인용 배지를 이 항목에 링크한다. 본문 인용과 목록은 정확히 일대일이다.

## 입력

| 변수 | 설명 |
|---|---|
| `research_plan` | 심사를 통과한 계획서 |
| `arxiv_cards` | Collector C 의 학술 카드 (인용 대조·참고문헌 생성용) |

## 출력

| 변수 | 설명 |
|---|---|
| `research_paper` | 최종 제출본 마크다운 (참고문헌 포함) |
| `lint_reporter` | 검사 요약. 예 `errors 0, warnings 1 (clean)` |
| `reporter_changes` | 심사 통과본 대비 변경 줄. 예 `2/138 lines (cleanup 2, lint-fix 0, llm calls 0, guard rejects 0)` |
| `references_count` | 생성된 참고문헌 수 |

콘솔에는 `[Reporter] 심사 통과본 대비 본문 변경 2/138줄 (표기 정리 2줄, 양식 수정 0줄, LLM 호출 0회, …)` 로 찍히고,
프론트매터 `format_lint`·`reporter_changes`·`references` 와 Run Summary 에 기록된다.

## LLM 호출

| 경우 | 호출 수 |
|---|---|
| 양식 오류 없음 (일반적) | 0 |
| 오류 남음 | 1~2 (위반 수정만) |

## 최종 문서 구조

```
# 연구명
## 연구 요약
## 1. 연구 배경 / ### 연구 주제 / ### 연구 필요성
## 2. 연구 목표 / ### 최종 목표 / ### 세부 목표
## 3. 연구 방법론 / ### 데이터 수집 / ### 제안 방법 (#### 모듈 1~3) / ### 실험 및 평가
## 4. 기대 효과 및 활용 방안 / ### 학술적 기여 / ### 실용적 활용 방안
## 참고문헌   ← 코드 생성
```

## 참조

프롬프트: `prompts/PROMPT_WRITER_LINT_FIX` (정리 전용 프롬프트 `PROMPT_REPORTER` 는 09-09 삭제)
구현: `code/finalize/reporter.py`, `code/finalize/cleanup.py`, `code/write/lint_loop.py`, `code/write/lint.py`, `code/finalize/references.py`
테스트: `tests/test_finalize_stage.py`, `tests/test_write_stage.py` 7절

## 뒤따르는 노드: cover (`code/finalize/cover.py`)

reporter 가 확정한 최종본으로 PDF 표지 메타를 만든다. 본문은 건드리지 않는다.

- **부제**: 완성된 `## 연구 요약` 전체를 읽고 LLM 이 한 문장(60~90자, "~한다.")으로 압축한다 (`PROMPT_COVER_SUBTITLE`, LLM 1회).
  실패하면 요약 첫 문장을 쓴다.
- **키워드**: Scope 단계 브리프의 `keywords_ko`(초록에 맞춰 LLM 이 낸 한국어 핵심어 5~6개). 추가 호출 없음.
- state `cover_subtitle` · `cover_keywords` → 프론트매터 `subtitle` · `keywords`. 조판(`export_pdf`)은 `main.py` 의 `PDF_SUBTITLE`/`PDF_KEYWORDS` 가
  비어 있을 때 이 값을 쓴다. 예시 초록에 맞춰 하드코딩되어 있던 main.py 와 build.py 의 부제·키워드는 제거했다.

