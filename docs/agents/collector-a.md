---
name: collector-a
description: deepresearch 파이프라인의 연구배경 수집 에이전트. 브리프(IN SCOPE / OUT OF SCOPE / KEY CONCEPTS)와 Supervisor 지시문으로 Tavily 웹검색 쿼리를 만들고, 결과 페이지 본문을 LLM 으로 출처 카드(요지·종류·연도·관련도·범위 판정)로 압축한 뒤 관련도순으로 선별한다. 라운드마다 갭 분석(기준별 covered/partial/missing, 빠진 주제, 후속 쿼리)을 돌려 부족한 항목만 겨냥해 재검색한다(최대 MAX_SEARCH=3). background_data(렌더링된 카드 묶음)와 background_cards 를 출력한다.
---

# Collector A — 연구배경 수집 에이전트

## 역할

**Tavily 웹검색**으로 연구 배경과 맥락, 기존 접근의 한계, 선행연구·기술 동향을 수집한다.
결과 페이지의 **본문**을 받아 LLM 이 출처 카드로 압축하고, 브리프 기준으로 관련도와 범위를 판정해 선별한다.
writer 는 원문이 아니라 이 카드 묶음만 본다.

## 입력

| 변수 | 설명 |
|---|---|
| `research_brief` | write_brief 의 브리프. RESEARCH QUESTION / IN SCOPE / OUT OF SCOPE / KEY CONCEPTS 를 파싱해 쿼리·카드·갭 프롬프트에 **직접** 넣는다 |
| `collector_a_prompt` | Supervisor 가 생성한 수집 지시문 |
| `abstract` | 연구초록 |

## 출력

| 변수 | 설명 |
|---|---|
| `background_data` | 선별된 출처 카드를 렌더링한 증거 텍스트 (writer/reporter 입력, 글자 예산 12,000자) |
| `background_cards` | 선별된 카드 목록 (dict: id, title, url, year, kind, summary, relevance, in_scope, query, round …) |
| `collector_a_search_count` | 실행된 라운드 수 |
| `is_a_sufficient` | 갭 분석이 '충분' 으로 끝났는지 |
| `collector_a_coverage` | 갭 분석 요약 한 줄 (covered/partial/missing 수와 미해결 항목) |

파일: `runtime/<실행시각>/research/cards_A.json` (전체 카드·라운드별 쿼리·갭 분석), `runtime/<실행시각>/research/evidence_A.md` (writer 에게 넘긴 텍스트)

## 라운드 (최대 MAX_SEARCH = 3)

```
쿼리 생성 (브리프 + 지시문 + 이전 라운드 갭 분석 + 이미 쓴 쿼리) → 3개
  → Tavily  쿼리당 5건, search_depth=advanced, include_raw_content (본문 6,000자까지)
  → 카드화  LLM 1회/쿼리: 요지 3~5문장(한국어, 고유명사 원문), 종류, 연도, 관련도 0~5, in_scope
  → 선별    URL 정규화 중복 제거 → in_scope 이고 관련도 ≥ 2 → 관련도·최신순 상위 12장
  → 갭 분석 LLM 1회: 기준 3개 각각 covered / partial / missing + 빠진 주제 + 후속 쿼리
       충분 (missing 0, partial ≤ 1) → 종료        부족 → 다음 라운드 (갭이 쿼리 생성에 주입됨)
```

LLM 호출은 라운드당 쿼리 1 + 카드 3 + 갭 1 = 5회. 카드화가 실패하면 원문 발췌로 카드를 만들어 라운드를 살리고,
갭 분석이 실패하면 '부족' 으로 간주한다.

## 갭 분석 기준 (PROMPT_EVALUATE_A)

1. `background_context` — 이 연구를 필요하게 만든 도메인 현황과 최근 변화
2. `existing_limitations` — 기존 접근의 구체적 한계 또는 미해결 문제
3. `prior_work_trends` — 선행연구 계열 또는 기술 동향 (출처 2개 이상)

## 프롬프트 참조

`prompts/` → `PROMPT_COLLECTOR_A_QUERY`, `PROMPT_CARDS_WEB`, `PROMPT_EVALUATE_A`
구현: `code/research/collectors.py`, `code/research/cards.py`, `code/research/search.py`
