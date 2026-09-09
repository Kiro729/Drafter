---
name: collector-c
description: deepresearch 파이프라인의 학술논문 수집 에이전트. 브리프와 Supervisor 지시문으로 영문 학술 검색 쿼리를 만들고, Liner Scholar Search 로 논문(제목·저자·연도·학술지·인용 수)을 찾은 뒤 초록을 arXiv → OpenAlex → Semantic Scholar 순으로 보강해 LLM 이 논문 카드(요지·접근 계열·관련도·범위 판정)로 압축, 관련도순으로 선별한다. Liner 키가 없으면 arXiv 직접 검색으로 동작한다. 라운드마다 갭 분석(직접 관련성·접근 다양성·최신성)을 돌려 부족한 계열만 겨냥해 재검색한다(최대 MAX_SEARCH=3). arxiv_data(렌더링된 카드 묶음)와 arxiv_cards 를 출력한다.
---

# Collector C — 학술논문 수집 에이전트 (하이브리드: Liner 스콜라 + 초록 보강, 대체 arXiv)

## 역할

연구 질문과 직접 관련된 학술 논문을 수집한다. Collector A·B 와 병렬로 실행된다.
논문의 **전체 초록**(또는 초록을 못 구했을 때는 검색 스니펫)을 근거로 LLM 이 카드를 만들며,
카드에는 접근 계열(approach), 학술지, 인용 수가 붙어 writer 가 "계열별 유형화" 와 대표 논문 선택에 그대로 쓸 수 있다.

## 백엔드 (code/research/scholar.py)

| 모드 | 조건 | 동작 |
|---|---|---|
| Liner 하이브리드 | `LINER_API_KEY` 있음 (또는 `SCHOLAR_BACKEND=liner`) | `POST platform.liner.com/api/v1/tools/search/scholar` 로 쿼리당 15건 발견 → 중복 제거 → 소프트 연도 필터 → arXiv 초록 보강 |
| arXiv 직접 | 키 없음 (또는 `SCHOLAR_BACKEND=arxiv`) | 기존 arXiv 검색: 쿼리당 8편, 전체 초록, 최근 5년 필터 우선 |

**초록 보강 (`config.ABSTRACT_SOURCES`, 기본 `("arxiv",)`)**: URL 이 arXiv 인 논문은 ID 일괄 조회 1회로 초록을 받는다.
그 외 논문은 Liner 스니펫을 요지 근거로 쓰고 카드에 "근거: 검색 스니펫" 을 표시한다.
OpenAlex(DOI 또는 제목 검색, 제목 유사도 70% 미만 거부, 연도 일치 시에만 메타데이터 채움)와 Semantic Scholar(`S2_API_KEY` 필요) 조회 코드는
`code/research/scholar.py` 에 남아 있어 설정에 `"openalex"`, `"semanticscholar"` 를 추가하면 그 순서로 더 시도한다.

**arXiv 요청 관문** (`search.arxiv_call`): 검색·ID 조회·Reviewer 검증 검색을 포함한 모든 arXiv 요청이 한 관문을 지난다.
요청 간 4초 이상 간격, 한 번에 하나만 보낸다. 429 를 받으면 5분을 기다린 뒤 딱 한 번 재시도하고, 재시도도 429 면
이번 실행에서는 arXiv 요청을 더 보내지 않는다. 그 뒤의 쿼리는 "검색 실패: ArxivRateLimited" 로 건너뛰고 파이프라인은 계속 진행한다.
라이브러리 자체 재시도는 꺼 두었다.

Liner 는 2 QPS 제한이며 429 는 `Retry-After` 만큼 기다려 한 번 재시도한다. 401(키 오류)·402(크레딧 부족)은 즉시 실패하고
해당 쿼리를 건너뛴다. 요금은 1,000건당 0.3달러(성공 호출만 과금)라 한 실행에 필요한 9~15회는 1센트 미만이다.

## 입력

| 변수 | 설명 |
|---|---|
| `research_brief` | write_brief 의 브리프. IN/OUT OF SCOPE 와 KEY CONCEPTS 가 쿼리·카드·갭 프롬프트에 직접 들어간다 |
| `collector_c_prompt` | Supervisor 가 생성한 수집 지시문 |
| `abstract` | 연구초록 |

## 출력

| 변수 | 설명 |
|---|---|
| `arxiv_data` | 선별된 논문 카드를 렌더링한 증거 텍스트 (제목·저자·연도·학술지·인용 수·arXiv ID 또는 DOI·접근·URL·요지) |
| `arxiv_cards` | 선별된 카드 목록 (dict). reporter 가 참고문헌의 저자·연도·제목·학술지·식별자·URL 을 여기서 얻는다 |
| `collector_c_search_count` | 실행된 라운드 수 |
| `is_c_sufficient` | 갭 분석이 '충분' 으로 끝났는지 |
| `collector_c_coverage` | 갭 분석 요약 한 줄 |

파일: `runtime/<실행시각>/research/cards_C.json`, `runtime/<실행시각>/research/evidence_C.md`. 프론트매터 `scholar_backend` 에 사용 백엔드가 남는다.

## 라운드 (최대 MAX_SEARCH = 3)

```
쿼리 생성 (브리프 + 지시문 + 이전 갭 분석 + 이미 쓴 쿼리 + 백엔드 안내) → 영문 쿼리 3개
  → 검색     Liner 15건(+초록 보강)  또는  arXiv 8편
  → 카드화   LLM 1회/쿼리 (PROMPT_CARDS_SCHOLAR): 문제·방법·결과·한계 요지(한국어), 접근 계열, 관련도 0~5, in_scope
             초록이 없고 스니펫만 있으면 1~2문장으로 짧게, 추정 금지. 인용 수는 관련도에 반영하지 않음
  → 선별     arXiv ID → DOI → URL 중복 제거 → in_scope 이고 관련도 ≥ 2 → 관련도 → 인용 수 → 최신순 상위 15장
  → 갭 분석  LLM 1회: 기준 3개 covered / partial / missing + 빠진 계열 + 후속 쿼리
       충분 (missing 0, partial ≤ 1) → 종료        부족 → 다음 라운드
```

## 쿼리 제약

- **영문만.** 학술 색인은 영문 기반이다.
- 핵심 모델·기법·태스크 이름을 포함하고, 쿼리마다 다른 접근 계열을 겨냥한다.
- Liner 는 자연어 쿼리를 자동 재작성하므로 개념을 정확히 표현한 영어 구절이 좋고, arXiv 는 키워드 매칭이라 내용어 3~7개가 좋다.
  이 차이는 `scholar_backend_note()` 가 프롬프트에 넣는다.
- 필드 접두어와 AND/OR 연산자는 쓰지 않는다. 날짜 필터는 코드가 처리한다.

## 갭 분석 기준 (PROMPT_EVALUATE_C)

1. `direct_relevance` — 연구 질문 또는 KEY CONCEPT 을 직접 다루는 논문 3편 이상 (관련도 4~5)
2. `approach_diversity` — 서로 다른 접근 계열 2개 이상, 계열마다 영향력 있는 논문(학술지·인용 수) 1편 이상
3. `recency` — 최근 5년 논문 2편 이상

## 프롬프트 참조

`prompts/` → `PROMPT_COLLECTOR_C_QUERY`, `PROMPT_CARDS_SCHOLAR`, `PROMPT_EVALUATE_C`
구현: `code/research/scholar.py` (Liner·보강·디스패처), `code/research/search.py` (arXiv), `code/research/collectors.py`, `code/research/cards.py`
