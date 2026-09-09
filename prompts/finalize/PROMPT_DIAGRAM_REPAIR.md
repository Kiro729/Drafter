Archify 검증이 실패했습니다. 아래 진단을 보고 스펙을 최소한으로 수정하십시오.

## 규칙

1. 진단이 지목한 요소(subject)만 수정하십시오. 나머지는 그대로 두십시오.
2. "supportedFixes" 의 수정을 우선 적용하십시오.
   검증기가 실제로 통과 가능한 후보를 계산해 알려준 것입니다.
3. 노드나 엣지를 삭제해 문제를 회피하지 마십시오. 정보가 사라집니다.
4. 라벨을 삭제해 간격을 확보하지 마십시오. 라벨은 의미를 담고 있습니다.
   줄여야 하면 뜻이 남는 범위에서 짧게 고치십시오.
5. 허용되지 않은 필드를 새로 추가하지 마십시오. "meta.locale" 은 쓰지 마십시오.

## 진단 코드별 대응

composition/ambiguous-corridor
  두 엣지가 같은 통로를 공유해 하나로 보입니다.
  지목된 엣지에 "bias" 추가 (0.0~1.0). 0.25 부터 시도. 0.15 는 부족했고 0.25 에서 통과한 사례가 있습니다.

workflow/route-preset-conflict
  명시한 "route" 가 간격 제약을 만족할 수 없습니다. "route" 필드를 제거하십시오.

label_route_clearance / relationship_crossings
  라벨이나 엣지가 겹칩니다. 라벨을 짧게 하거나 "bias" 로 경로를 옮기십시오.
  진단이 "labelAt" 좌표를 제시했다면 추정하지 말고 그 값을 그대로 쓰십시오.

뷰포트 / containment
  다이어그램이 뷰포트를 넘습니다. sublabel 을 생략하거나 노드를 합치십시오.
  레인 라벨을 짧게 하면 폭이 줄어듭니다.

텍스트 폭 (minimum text width)
  라벨이 노드에 안 들어갑니다. "width" 를 키우거나(136→160) 라벨을 줄이십시오.
  한글은 글자당 2단위로 계산됩니다.

스키마 오류 (must NOT have additional properties, must be equal to one of the allowed values 등)
  지목된 필드를 제거하거나 허용값으로 바꾸십시오. 노드 type 은
  frontend / backend / database / cloud / security / messagebus / external 만 허용됩니다.
  col 은 0~5 정수, id 는 영문자로 시작하는 영문·숫자·_·- 만 허용됩니다.

## 시도 회차

{repair_round} / {max_rounds}

## 진단

{diagnostics_json}

## 수정 대상 스펙

{spec_json}

## 출력

수정된 전체 스펙 JSON 객체 하나만. 설명·코드펜스 없이. "caption_ko" 같은 스펙 외 필드를 넣지 마십시오.
