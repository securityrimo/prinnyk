# ㅍㄹㄴ 1·2 비공식 한국어 패치 V1.5

ㅍㄹㄴ 1 `ULJS00150`과 ㅍㄹㄴ 2 `NPJH50211`의 한국어 패치입니다.
이 배포본은 ㅍㄹㄴ 1의 PSP 저장 데이터 정보 표시 복구가 통합된 V1.5 교체본입니다.
게임 ISO와 원본 DLC 바이너리는 포함하지 않습니다. 정품에서 직접 추출한 무수정
일본판 ISO와 본인이 보유한 원본 DLC 폴더에 패치를 적용하십시오. ㅍㄹㄴ 2 DLC는
유럽판 원본 DLC 폴더를 일본판 `NPJH50211` 설치 구조로 변환하는 xdelta 폴더 패치로
제공합니다.

다운로드: https://github.com/sizz1214-lang/prinnyk/releases/tag/v1.5

## 구성

- `Prinny1_ULJS00150_KR_v1.5_BASE.xdelta` — ㅍㄹㄴ 1 본편
- `Prinny1_ULJS00150_DLC_ALL_KO_v1.5.xdelta` — ㅍㄹㄴ 1 DLC 3종 폴더 패치
- `Prinny2_NPJH50211_KR_v1.5_BASE.xdelta` — ㅍㄹㄴ 2 본편
- `Prinny2_NPJH50211_DLC_ALL_KO_v1.5.xdelta` — ㅍㄹㄴ 2 DLC 전체 폴더 패치
- `Prinny_DLC_Folder_Patcher_v1.5.zip` — DLC xdelta 2개와 폴더 적용기
- `Prinny_1_2_Korean_Final_v1.5_ALL.zip` — 본편·DLC 패치와 문서 전체 묶음

## 본편 적용

```bash
xdelta3 -d -s "프리니1_원본.iso" "Prinny1_ULJS00150_KR_v1.5_BASE.xdelta" "Prinny1_ULJS00150_KR_v1.5.iso"
xdelta3 -d -s "프리니2_원본.iso" "Prinny2_NPJH50211_KR_v1.5_BASE.xdelta" "Prinny2_NPJH50211_KR_v1.5.iso"
```

| 게임 | 원본 SHA-256 | 패치 결과 SHA-256 |
|---|---|---|
| ㅍㄹㄴ 1 | `af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03` | `3d07c662797be7f0a3d7886384f2b626ddb507fdd1bfa0f090cc8abb7fbc1ae2` |
| ㅍㄹㄴ 2 | `4c509ba4d8d2dfcd2635228526fa2955e25ccbb511878861ed31ecfcf2829087` | `4fa2532edd97ed131bc7ca35d1eb52e40c9d1308c9fd72ff3c1d35d14f94cc83` |

## ㅍㄹㄴ 1 저장 데이터 정보 표시

기존 V1.5에서 PSP/Vita 저장 데이터의 정보란이 `SAVE`로만 표시되던 문제를
수정했습니다. 이제 원본 형식대로 잔여 마계 시간·회차, 남은 프리니 수, 플레이
시간이 저장 시점의 값으로 표시됩니다.

이미 `SAVE`로 기록된 기존 세이브는 패치 교체만으로 정보란이 즉시 바뀌지 않습니다.
교체된 본편으로 기존 세이브를 불러온 뒤 게임 안에서 한 번 다시 저장하십시오.

## DLC 설치

DLC ZIP 자체에는 xdelta를 적용하지 않습니다. `Prinny_DLC_Folder_Patcher_v1.5.zip`을
풀고 게임별 실행 파일을 사용해 원본 DLC 압축 해제 폴더를 지정합니다. 적용기는
파일별 SHA-256을 확인한 뒤 새 `patched_output/PSP/GAME` 구조를 만듭니다.
원본 폴더는 수정하지 않습니다.

- Windows: `apply_prinny1_dlc.bat` 또는 `apply_prinny2_dlc.bat`
- Linux/macOS: `sh apply_prinny1_dlc.sh` 또는 `sh apply_prinny2_dlc.sh`

ㅍㄹㄴ 1은 `ULJS00150` 폴더를 지정하십시오. ㅍㄹㄴ 2는 정식 유럽판 DLC의
세 `NPEH00101` 폴더가 함께 들어 있는 공통 상위 폴더를 지정하면 됩니다. 상위 폴더
이름은 아무거나 가능하며, 입력을 `NPJH50211`로 미리 변환하거나 이름을 바꿀 필요가
없습니다. 적용 결과가 `patched_output/PSP/GAME/NPJH50211`에 생성됩니다. 자세한
내용은 `DLC_INSTALL_v1.5.md`를 참조하십시오.

PPSSPP에서는 메모리스틱 삽입이 켜져 있어야 합니다. 외부 텍스처 교체는 필요하지
않으며 사용하지 않습니다.

## 추가 배포

- [ㄷㅅㄱㅇㅇ ㅇㅍㄴㅌ 비공식 한국어 패치 V1.0](disgaea_infinite_v1.0/README.md)
- 다운로드: https://github.com/sizz1214-lang/prinnyk/releases/tag/disgaea-infinite-v1.0
