# final/

최종 연구계획서가 실행 시각 이름으로 쌓인다.

- `research_paper_<YYYYMMDD_HHMMSS>.md` — 프론트매터(실행 기록) + 본문 + 참고문헌
- `research_paper_<YYYYMMDD_HHMMSS>.pdf` — 표지·목차·본문·그림이 들어간 조판본

같은 시각의 중간 산출물은 `runtime/<시각>/` 에 있다. 재조판: `python scripts/export_pdf.py [파일]`.
