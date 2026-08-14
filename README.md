# 프리니 1·2 비공식 한국어 패치 v1.2

프리니 1 `ULJS00150`과 프리니 2 `NPJH50211`의 최종 한국어 패치와
한글화 DLC를 함께 배포합니다.

게임 ISO와 원본 DLC 파일은 포함하지 않습니다. 정품에서 직접 추출한 무수정
일본판 ISO와 원본 DLC에 xdelta 패치를 적용해야 합니다.

## v1.2 다운로드

모든 파일은 [GitHub v1.2 Release](https://github.com/sizz1214-lang/prinnyk/releases/tag/v1.2)에서 받습니다.

### 기본 게임 ISO 패치

- `Prinny_ULJS00150_KR_v1.2.xdelta`
- `Prinny2_NPJH50211_KR_v1.2.xdelta`

### DLC 통합 패치

- `Prinny1_DLC_Integrated_KO_v1.2_XDELTA.zip` — 프리니 1 DLC 3종 통합
- `Prinny2_DLC_Integrated_JP_EU_to_NPJH50211_KO_v1.2_XDELTA.zip` — 일본판·유럽판 DLC를 모두 지원하는 `NPJH50211`용 통합팩

### 전체 묶음

- `Prinny_1_2_Korean_Final_v1.2_ALL.zip`
- `Prinny2_Korean_Final_v1.2_EASY.zip` — 프리니 2 본편과 DLC를 한 메뉴에서 적용하는 간편판

프리니 2는 간편판 ZIP을 풀고 Windows에서는 `START_PATCH.bat`, Linux에서는
`START_PATCH.sh`를 실행한 뒤 `1. 본편 + DLC 모두 패치`를 고르면 됩니다.

## 기본 게임 패치 적용

```bash
xdelta3 -d -s "원본.iso" "v1.2.xdelta" "한글판.iso"
```

| 게임 | 원본 크기 | 원본 SHA-256 | 패치 후 ISO SHA-256 |
|---|---:|---|---|
| 프리니 1 | 500,465,664 | `af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03` | `c88e5ade8e114b560da23da32fa908c4b1c2713e1ab051d6cb90a225058e7397` |
| 프리니 2 | 822,214,656 | `4c509ba4d8d2dfcd2635228526fa2955e25ccbb511878861ed31ecfcf2829087` | `6d1268e2c4b6443fc734fb206a35a0afdc484063ab543bd56916e917600ec868` |

## DLC 패치 적용

DLC 패치 ZIP을 풀고 원본 DLC ZIP 또는 압축을 푼 원본 폴더를 지정합니다.

Linux:

```bash
./apply.sh "원본 DLC.zip" "출력 폴더"
```

Windows:

```bat
apply.bat "D:\원본\DLC.zip" "D:\DLC_출력"
```

출력된 `PSP` 폴더를 메모리스틱 루트에 복사합니다.

- 프리니 1 최종 위치: `ms0:/PSP/GAME/ULJS00150/`
- 프리니 2 최종 위치: `ms0:/PSP/GAME/NPJH50211/`

DLC는 게임 ISO에 합치지 않습니다. 각 게임은 본편 ISO 패치 한 개와 DLC 통합팩
한 개만 적용합니다. 프리니 2 통합팩은 일본판 `NPJH50211` 또는 유럽판
`NPEH00101` DLC를 자동 판별해, 일본판 본편이 사용하는 `NPJH50211` 설치 폴더
하나로 출력합니다.

## v1.2 변경 사항

- 기존 프리니 1·2 최종 한국어 ISO 패치를 실제 `v1.2` 파일명으로 정리
- 프리니 1 DLC 3종의 스테이지 설명과 전체 이벤트 대사 한글화
- 프리니 2 `초절마계 프라마임` 설명·이벤트 대사 한글화
- 프리니 2 일본판 `NPJH50211`·유럽판 `NPEH00101` DLC를 한 통합팩에서 자동 판별
- 어느 지역 DLC를 입력해도 일본판 본편용 한글 DLC 결과가 같도록 통합
- 프리니 2 세이브·XMB 표기, 배달·통신 메뉴의 잔여 일본어를 한국어로 수정
- 프리니 2 원본과 대조해 튜토리얼 메뉴의 `TIPS` 표기를 복원
- 프리니 2 본편과 DLC를 한 메뉴에서 적용하는 간편 패키지 추가
- 게임별 DLC 통합 xdelta와 안전 적용기 제공
- 원본·패치·결과 SHA-256 검사와 통합 적용·재적용 검증 추가

## 지원 환경

- PSP CFW ISO 로더
- PS Vita 6.61 Adrenaline
- PPSSPP

PS Vita에서 `80020148`이 발생하면 Adrenaline Recovery Menu의
`Execute BOOT.BIN in UMD/ISO`를 활성화하십시오.

기본 게임 패치는 런타임 검증이 완료됐습니다. DLC는 구조·문자표·재파싱·xdelta
적용 검증을 통과했고 PPSSPP에서 인식·로드를 확인했습니다. 전체 DLC 스테이지의
완주와 보상 획득은 기기별 추가 제보를 환영합니다.
