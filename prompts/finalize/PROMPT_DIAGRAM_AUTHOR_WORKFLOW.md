아래 연구계획서의 "연구 방법론" 절을 Archify workflow JSON 으로 변환하십시오.
이 다이어그램은 연구계획서의 "제안 방법" 절에 "연구 프레임워크" 그림으로 실립니다.
데이터가 들어와 제안 방법의 모듈들을 거쳐 실험·평가로 이어지는 흐름이 한눈에 보여야 합니다.

## 절대 규칙

1. 원문에 있는 내용만 쓰십시오. 단계·모듈·데이터셋·지표·수치를 발명하지 마십시오.
2. 아래 "허용 필드" 에 없는 필드를 추가하지 마십시오. 정의되지 않은 필드는 즉시 거부됩니다.
3. 좌표·색·폰트를 지정하지 마십시오. 레이아웃 엔진이 소유합니다.
4. edge 에 "route", "via", "labelAt", "channelX", "channelY", "fromSide", "toSide" 를 쓰지 마십시오.
   자동 라우팅이 더 안정적입니다.
5. "meta.locale" 을 쓰지 마십시오. 한국어는 지원값이 아니며 검증 실패합니다.
6. 라벨은 한국어로 씁니다. 데이터셋명·모델명·지표명·도구명은 원문 표기를 유지합니다
   (예: MovieLens, BERT4Rec, nDCG@10, Cronbach α).

## 구조

- lanes: 연구 국면 또는 담당 구성요소. 2~4개. 라벨은 2~6자 (예: 자료, 모델링, 평가, 검증).
  라벨이 길면 다이어그램 전체가 오른쪽으로 밀립니다.
  검증·재작업 성격의 레인에는 "variant": "exception".
- col: 절차 순서. 0~5 정수만. 같은 lane 안에서 col 이 겹치지 않게 하십시오.
- nodes: 6~12개. 12개를 넘기지 마십시오.
  기본 골격: 데이터 출처 → 전처리·구축 → 모듈 1 → 모듈 2 → 모듈 3 → 실험·평가 → 결과.
  계획서의 세 모듈은 반드시 각각 노드로 두고 순서를 지키십시오.
- edges: 모든 노드가 최소 한 edge 에 나타나야 합니다. 고립 노드를 두지 마십시오.
  같은 (from, to) 쌍을 두 번 만들지 마십시오.
- mainPath: 주 경로 노드 id 배열 (2개 이상). col 이 단조 증가해야 합니다.
- 모든 노드에 "width": 136. 한글 라벨 축소를 막습니다.
- phases, groups, semanticChecks 는 선택입니다. 확신이 없으면 생략하십시오.

## type — 의미 슬롯 (색이 아니라 의미를 고르는 것)

  database    → 데이터셋, 로그, 수집 자료, 자료원
  backend     → 연구 단계, 절차, 모델 학습·구축 행위
  messagebus  → 분석 기법, 처리·계산 작업, 지표 산출
  security    → 검증, 타당성·신뢰도 확인, 심의, 기준 판정
  external    → 선행 연구, 기존 베이스라인, 외부 기관, 연구 대상
  frontend    → 연구 산출물, 최종 결과물
  cloud       → 외부 서비스·플랫폼 (드물게)

## variant / role

edge.variant: "default" | "emphasis" | "security" | "dashed"
              emphasis=주 경로, security=검증·판정, dashed=보조·자료 전달
edge.role:    "main" | "branch" | "async" | "return" | "error"
              error=실패 분기, return=반송·재작업
lane.variant: "normal" | "exception"
phase/group.variant: "default" | "emphasis" | "security" | "dashed"

## 범례 — 도메인 언어로 교체

기본값은 소프트웨어 용어("Agent logic", "Tool action")입니다.
사용한 type 에 대해서만 meta.legend.entries 에 한국어 라벨(80자 이내)을 주십시오.

## 허용 필드

최상위: schema_version(=2), diagram_type(="workflow"), meta, lanes, nodes, edges,
        phases, groups, mainPath, semanticChecks
meta:     title, quality_profile(="showcase"), legend
legend:   mode("auto"), entries.<type>.label
lanes[]:  id, label, variant
phases[]: id, label, fromCol, toCol, variant
groups[]: id, label, lane, fromCol, toCol, variant
nodes[]:  id, lane, col, type, label, sublabel, tag, width
edges[]:  id, from, to, label, variant, role, bias
id 형식:  영문자로 시작, 영문·숫자·_·- 만 (^[a-zA-Z][a-zA-Z0-9_-]*$). 한글 id 불가.

## 라벨

- meta.title: 그림 제목. 4~10자 (예: 연구 프레임워크).
- node.label: 4~8자 한글 명사구. 단계·모듈 이름.
- node.sublabel: 데이터 규모·도구명·지표 등 구체값. 원문에 있을 때만. 10자 이내.
- edge.label: 2~6자. 전달되는 것(자료·결과)의 이름. 양 끝 노드만으로 자명하면 생략.
- 한글은 폭 계산에서 2배로 잡힙니다. 짧게 쓰십시오.

## 캡션

"caption_ko": 그림 아래에 붙는 한 줄 설명. 40자 이내 명사구, 구조 / 흐름도 / 개요 로 끝냄, 마침표 없음.
연구가 주장하는 바가 아니라 그림이 보여주는 것을 적습니다. 스펙 안이 아니라 바깥에 둡니다.

## 예시 — 첫 시도에 검증을 통과한 스펙의 골격

형식만 참고하십시오. 레인·노드·라벨 내용은 아래 원문에서 새로 작성합니다.

{{
  "schema_version": 2,
  "diagram_type": "workflow",
  "meta": {{
    "title": "연구 절차",
    "visual_preset": "classic",
    "quality_profile": "showcase",
    "legend": {{
      "mode": "auto",
      "entries": {{
        "external": {{
          "label": "선행 연구"
        }},
        "backend": {{
          "label": "연구 단계"
        }},
        "database": {{
          "label": "수집 자료"
        }},
        "messagebus": {{
          "label": "분석 및 처리"
        }},
        "security": {{
          "label": "타당성 검증"
        }},
        "frontend": {{
          "label": "연구 산출물"
        }}
      }}
    }}
  }},
  "lanes": [
    {{
      "id": "design",
      "label": "설계"
    }},
    {{
      "id": "collect",
      "label": "자료 수집"
    }},
    {{
      "id": "analyze",
      "label": "분석"
    }},
    {{
      "id": "verify",
      "label": "타당성 검증",
      "variant": "exception"
    }}
  ],
  "phases": [
    {{
      "id": "p1",
      "label": "이론 및 설계",
      "fromCol": 0,
      "toCol": 1
    }},
    {{
      "id": "p2",
      "label": "조사 실시",
      "fromCol": 2,
      "toCol": 3,
      "variant": "emphasis"
    }},
    {{
      "id": "p3",
      "label": "분석 및 해석",
      "fromCol": 4,
      "toCol": 5,
      "variant": "dashed"
    }}
  ],
  "mainPath": [
    "lit",
    "model",
    "instrument",
    "survey",
    "coding",
    "findings"
  ],
  "nodes": [
    {{
      "id": "lit",
      "lane": "design",
      "col": 0,
      "type": "external",
      "label": "문헌 검토",
      "sublabel": "선행연구 42편",
      "width": 136
    }},
    {{
      "id": "model",
      "lane": "design",
      "col": 1,
      "type": "backend",
      "label": "연구모형 도출",
      "sublabel": "가설 H1~H3",
      "width": 136
    }},
    {{
      "id": "instrument",
      "lane": "design",
      "col": 2,
      "type": "backend",
      "label": "측정도구 개발",
      "sublabel": "설문 문항 구성",
      "width": 136
    }},
    {{
      "id": "pilot",
      "lane": "collect",
      "col": 2,
      "type": "backend",
      "label": "예비조사",
      "sublabel": "n=30",
      "width": 136
    }},
    {{
      "id": "survey",
      "lane": "collect",
      "col": 3,
      "type": "backend",
      "label": "본조사",
      "sublabel": "n=420",
      "tag": "층화 표집",
      "width": 136
    }},
    {{
      "id": "dataset",
      "lane": "collect",
      "col": 4,
      "type": "database",
      "label": "응답 데이터셋",
      "sublabel": "결측 처리",
      "width": 136
    }},
    {{
      "id": "coding",
      "lane": "analyze",
      "col": 4,
      "type": "messagebus",
      "label": "통계 분석",
      "sublabel": "SPSS · R",
      "width": 136
    }},
    {{
      "id": "findings",
      "lane": "analyze",
      "col": 5,
      "type": "frontend",
      "label": "연구 결과",
      "sublabel": "가설 검정 결과",
      "width": 136
    }},
    {{
      "id": "reliability",
      "lane": "verify",
      "col": 3,
      "type": "security",
      "label": "신뢰도 검증",
      "sublabel": "Cronbach α",
      "width": 136
    }},
    {{
      "id": "validity",
      "lane": "verify",
      "col": 4,
      "type": "security",
      "label": "타당도 검증",
      "sublabel": "확인적 요인분석",
      "width": 136
    }},
    {{
      "id": "revise",
      "lane": "verify",
      "col": 5,
      "type": "messagebus",
      "label": "문항 재구성",
      "sublabel": "기준 미달 시",
      "width": 136
    }}
  ],
  "edges": [
    {{
      "id": "e1",
      "from": "lit",
      "to": "model",
      "label": "이론적 배경",
      "variant": "default"
    }},
    {{
      "id": "e2",
      "from": "model",
      "to": "instrument",
      "label": "구성개념 조작화",
      "variant": "emphasis"
    }},
    {{
      "id": "e3",
      "from": "instrument",
      "to": "pilot",
      "label": "문항 검토",
      "variant": "dashed"
    }},
    {{
      "id": "e4",
      "from": "pilot",
      "to": "reliability",
      "label": "예비 응답 분석",
      "variant": "security"
    }},
    {{
      "id": "e5",
      "from": "reliability",
      "to": "validity",
      "label": "요인구조 확인",
      "variant": "security"
    }},
    {{
      "id": "e6",
      "from": "validity",
      "to": "revise",
      "label": "기준 미달",
      "variant": "security",
      "role": "error"
    }},
    {{
      "id": "e7",
      "from": "revise",
      "to": "instrument",
      "label": "재구성",
      "variant": "dashed",
      "role": "return"
    }},
    {{
      "id": "e8",
      "from": "instrument",
      "to": "survey",
      "label": "확정 문항",
      "variant": "emphasis"
    }},
    {{
      "id": "e9",
      "from": "survey",
      "to": "dataset",
      "label": "응답 수집",
      "variant": "dashed"
    }},
    {{
      "id": "e10",
      "from": "dataset",
      "to": "coding",
      "label": "분석 투입",
      "variant": "dashed"
    }},
    {{
      "id": "e11",
      "from": "survey",
      "to": "coding",
      "label": "본조사 완료",
      "variant": "emphasis"
    }},
    {{
      "id": "e12",
      "from": "coding",
      "to": "findings",
      "label": "결과 도출",
      "variant": "emphasis"
    }}
  ]
}}

{feedback_section}
## 출력

아래 형태의 JSON 객체 하나만. 설명·주석·코드펜스 없이.
{{
  "caption_ko": "...",
  "spec": {{ ...Archify workflow JSON... }}
}}

연구 방법론 절:
<<<
{methodology_text}
>>>
