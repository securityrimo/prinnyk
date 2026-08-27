# 디스가이아 인피니트 한국어 패치 V1.0 정적 QA

- 정적 판정: **PASS**
- 상태: **정적 QA 완료**
- 최종 ISO: `234e9f3bfac930e88cabf779ccc33abe343b4061896634b960c3d3b8deb07f86` (220889088 bytes)
- 원본 ISO: `32de3247bed3c78fdb66a9fe6d6a973ac808982d2472f569a90809135df9cce5`
- 런타임: 별도 최종 스모크 검증 PASS (`RUNTIME_QA_v1.0.md`)

## 강제 계약

- START/DATA: 87/171개, 11,981,840/17,011,728바이트, 재배치 없음
- START.LZS: 원본 템플릿 헤더 플래그 보존, 비중첩 back-reference, 5,066,752바이트 슬롯 이내, 압축 해제 exact readback
- 최종 ISO story.dat: 레코드/명령/텍스트 mod-4 정렬 및 동적 00 00 패딩 위반 0
- 최종 ISO: 220,889,088바이트 및 START.LZS/DATA.DAT/PARAM.SFO/ICON0.PNG/PIC0.PNG/EBOOT.BIN 6개 멤버만 변경
- START/DATA 전 멤버 및 ISO 6개 멤버의 exact hash readback
- TXP 마스크 밖 픽셀 변경 0, ANM 허용 범위 밖 바이트 변경 0
- XMB/GThumb/저장 아이콘 결정론적 기대 해시 일치

## 계층별 판정

| 계층 | 판정 |
|---|---|
| input_reports | PASS |
| TXP/ANM 범위 | PASS |
| NISPACK/LZS | PASS |
| 결정론적 에셋 | PASS |
| EBOOT | PASS |
| RC9 화면/대사 계약 | PASS |
| 최종 ISO readback | PASS |
| runtime | 별도 스모크 PASS |

## 변경 범위

- 원본 대비 변경 바이트: 6428310
- 허용 멤버 밖 변경: 0
- 실제 변경 멤버: DATA.DAT, EBOOT.BIN, ICON0.PNG, PARAM.SFO, PIC0.PNG, START.LZS

## 제한

- 이 표의 61개 항목은 정적/바이너리/readback QA 범위다. 별도 PPSSPP 스모크 검증은 자동저장 안내와 시작 선택 화면까지 수행했으며, 전체 게임 완주 검수는 수행하지 않았다.
