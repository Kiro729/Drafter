# runtime/

실행마다 `runtime/<YYYYMMDD_HHMMSS>/` 가 만들어지고 그 안에 중간 산출물이 남는다.

| 하위 폴더 | 내용 |
|---|---|
| `research/` | `brief.md`(내부용 브리프), `cards_{A,B,C}.json`(수집 카드 전체), `evidence_{A,B,C}.md`(Writer 에 넘긴 증거) |
| `figures/` | `framework.spec.json` · `framework.validate.json` · `framework.html` · `framework.svg` · `framework.png` |
| `pdf_build/` | 조판 입력(`proposal.md`, `figure1.png`, `meta.json`)과 중간 PDF |

같은 시각의 최종본은 `final/research_paper_<시각>.md / .pdf`. 이 폴더는 지워도 파이프라인에 영향이 없다.
