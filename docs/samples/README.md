# 결과물 예시

2026-09-09 실행(gpt-5.1, Liner 스콜라 검색)의 실제 산출물이다. 초록은 GAN·그래프 오토인코더 기반 추천(G2R)의 생성자 증강 손실 학습.

| 파일 | 내용 |
|---|---|
| `sample_proposal.md` | 최종 연구계획서 마크다운. 프론트매터에 실행 기록(심사 라운드, 양식 검사, 참고문헌 수, 표지 부제·키워드) |
| `sample_proposal.pdf` | 조판본 10쪽 (표지·목차·본문·도해·참고문헌) |
| `sample_framework.png` / `.svg` | Archify 워크플로 도해. showcase 검증 미통과 → standard 품질 폴백으로 렌더된 예 |

본문 2,969자(공백 제외, 양식 목표 3,440자의 86%), 참고문헌 3건, 심사 2라운드 한도 종료. 재조판: `python scripts/export_pdf.py docs/samples/sample_proposal.md`
