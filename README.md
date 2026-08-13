# 프리니 1·2 비공식 한국어 패치

프리니 1 `ULJS00150`과 프리니 2 `NPJH50211`의 한국어 패치를 한곳에서 제공합니다

게임 ISO는 포함하지 않으며 정품에서 직접 추출한 무수정 일본판 ISO에 xdelta를 적용해야 합니다

## 지원 환경

- PSP CFW ISO 로더
- PS Vita 6.61 Adrenaline
- PPSSPP

## 원본 검증값

| 게임 | 게임 ID | 원본 크기 | 원본 SHA-256 |
|---|---|---:|---|
| 프리니 1 | `ULJS00150` | 500,465,664 | `af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03` |
| 프리니 2 | `NPJH50211` | 822,214,656 | `4c509ba4d8d2dfcd2635228526fa2955e25ccbb511878861ed31ecfcf2829087` |

## 게임별 릴리스

- [프리니 1 한국어 패치 v1.0](https://github.com/sizz1214-lang/prinnyk/releases/tag/v1.0)
- [프리니 2 한국어 패치 v1.0](https://github.com/sizz1214-lang/prinnyk/releases/tag/prinny2-v1.0)

두 게임은 같은 저장소에서 관리하지만 릴리스 게시물과 xdelta는 각각 분리합니다

## PSP 및 PS Vita 호환 변경

기존 공개본은 번역 실행 파일을 복호화 ELF 상태로 `EBOOT.BIN`에 넣어 일부 PSP 로더와 PS Vita Adrenaline에서 `80020148`이 발생할 수 있었습니다

현재 공개본은 다음 두 경로를 함께 제공합니다

- `EBOOT.BIN`: PSP 표준 `~PSP` 서명 실행 파일
- `BOOT.BIN`: 동일한 한국어판 ELF 실행 파일

PS Vita에서 기본 실행이 되지 않으면 Adrenaline Recovery Menu의 `Execute BOOT.BIN in UMD/ISO`를 활성화하십시오

## 프리니 2 최종 수정

- 스테이지 리포트 오른쪽 아래 `クリアランク` 도장을 `클리어 / 랭크`로 수정
- 영상 건너뛰기와 안내 2/4의 남은 일본어 수정
- 튜토리얼 32종과 시설 명칭 및 주요 UI 보정

원본 ISO의 게임 ID와 SHA-256을 반드시 확인한 뒤 xdelta3로 적용하십시오
