---
name: collector-b
description: deepresearch 파이프라인의 방법론·실험설계·검증 수집 에이전트. 브리프(IN SCOPE / OUT OF SCOPE / KEY CONCEPTS)와 Supervisor 지시문으로 Tavily 웹검색 쿼리를 만들고, 결과 페이지 본문을 LLM 으로 출처 카드(요지·종류·연도·관련도·범위 판정)로 압축한 뒤 관련도순으로 선별한다. 라운드마다 갭 분석(구현 방법·실험 설계와 지표·검증과 베이스라인)을 돌려 부족한 항목만 겨냥해 재검색한다(최대 MAX_SEARCH=3). method_data(렌더링된 카드 묶음)와 method_cards 를 출력한다.
---

# Collector B — 방법론·실험설계·검증 수집 에이전트

## 역할

**Tavily 웹검색**으로 구현 방법·알고리즘, 실험 설계와 평가 지표, 검증 방법과 비교 베이스라인을 수집한다.
Collector A(연구배경)·C(arXiv)와 병렬로 실행된다. 결과 페이지 **본문**을 받아 카드로 압축하고,
브리프 기준으로 관련도와 범위를 판정해 선별한다.

## 입력

| 변수 | 설명 |
|---|---|
| `research_brief` | write_brief 의 브리프. 파싱된 항목이 쿼리·카드·갭 프롬프트에 직접 들어간다 |
| `collector_b_prompt` | Supervisor 가 생성한 수집 지시문 |
| `abstract` | 연구초록 |

## 출력

| 변수 | 설명 |
|---|---|
| `method_data` | 선별된 출처 카드를 렌더링한 증거 텍스트 (writer/reporter 입력, 글자 예산 12,000자) |
| `method_cards` | 선별된 카드 목록 (dict) |
| `collector_b_search_count` | 실행된 라운드 수 |
| `is_b_sufficient` | 갭 분석이 '충분' 으로 끝났는지 |
| `collector_b_coverage` | 갭 분석 요약 한 줄 |

파일: `runtime/<실행시각>/research/cards_B.json`, `runtime/<실행시각>/research/evidence_B.md`

## 라운드 (최대 MAX_SEARCH = 3)

```
쿼리 생성 (브리프 + 지시문 + 이전 갭 분석 + 이미 쓴 쿼리) → 3개 (방법 / 지표·프로토콜 / 베이스라인·검증 각 1개)
  → Tavily  쿼리당 5건, search_depth=advanced, include_raw_content
  → 카드화  LLM 1회/쿼리: 요지 3~5문장(한국어, 데이터셋·지표·모델명 원문), 종류, 연도, 관련도 0~5, in_scope
  → 선별    URL 중복 제거 → in_scope 이고 관련도 ≥ 2 → 관련도·최신순 상위 12장
  → 갭 분석 LLM 1회: 기준 3개 covered / partial / missing + 빠진 주제 + 후속 쿼리
       충분 (missing 0, partial ≤ 1) → 종료        부족 → 다음 라운드
```

## 갭 분석 기준 (PROMPT_EVALUATE_B)

1. `implementation_methods` — 제안 접근을 구현할 수 있는 구체적 방법·알고리즘 (입력·출력·핵심 메커니즘이 드러날 정도)
2. `experimental_design_metrics` — 이 문제 유형의 실험 프로토콜과 평가 지표 (명시적 지표명)
3. `validation_baselines` — 검증 방법과 비교 베이스라인 (이 분야 계획서가 비교해야 할 것 1개 이상)

## 프롬프트 참조

`prompts/` → `PROMPT_COLLECTOR_B_QUERY`, `PROMPT_CARDS_WEB`, `PROMPT_EVALUATE_B`
구현: `code/research/collectors.py`, `code/research/cards.py`, `code/research/search.py`
