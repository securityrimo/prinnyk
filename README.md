# 프리니 1·2 비공식 한국어 패치 V1.5

프리니 1 `ULJS00150`과 프리니 2 `NPJH50211`의 한국어 패치입니다.
게임 ISO와 원본 DLC 바이너리는 포함하지 않습니다. 정품에서 직접 추출한 무수정
일본판 ISO와 본인이 보유한 원본 DLC 폴더에 패치를 적용하십시오. 프리니 2 DLC는
유럽판 원본 DLC 폴더를 일본판 `NPJH50211` 설치 구조로 변환하는 xdelta 폴더 패치로
제공합니다.

다운로드: https://github.com/sizz1214-lang/prinnyk/releases/tag/v1.5

## 구성

- `Prinny1_ULJS00150_KR_v1.5_BASE.xdelta` — 프리니 1 본편
- `Prinny1_ULJS00150_DLC_ALL_KO_v1.5.xdelta` — 프리니 1 DLC 3종 폴더 패치
- `Prinny2_NPJH50211_KR_v1.5_BASE.xdelta` — 프리니 2 본편
- `Prinny2_NPJH50211_DLC_ALL_KO_v1.5.xdelta` — 프리니 2 DLC 전체 폴더 패치
- `Prinny_DLC_Folder_Patcher_v1.5.zip` — DLC xdelta 2개와 폴더 적용기
- `Prinny_1_2_Korean_Final_v1.5_ALL.zip` — 본편·DLC 패치와 문서 전체 묶음

## 본편 적용

```bash
xdelta3 -d -s "프리니1_원본.iso" "Prinny1_ULJS00150_KR_v1.5_BASE.xdelta" "Prinny1_ULJS00150_KR_v1.5.iso"
xdelta3 -d -s "프리니2_원본.iso" "Prinny2_NPJH50211_KR_v1.5_BASE.xdelta" "Prinny2_NPJH50211_KR_v1.5.iso"
```

| 게임 | 원본 SHA-256 | 패치 결과 SHA-256 |
|---|---|---|
| 프리니 1 | `af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03` | `9d91eced0ae84434557a34a20965d3c0991b7fddd54f2aa4bb301c2a4166c914` |
| 프리니 2 | `4c509ba4d8d2dfcd2635228526fa2955e25ccbb511878861ed31ecfcf2829087` | `4fa2532edd97ed131bc7ca35d1eb52e40c9d1308c9fd72ff3c1d35d14f94cc83` |

## DLC 설치

DLC ZIP 자체에는 xdelta를 적용하지 않습니다. `Prinny_DLC_Folder_Patcher_v1.5.zip`을
풀고 게임별 실행 파일을 사용해 원본 DLC 압축 해제 폴더를 지정합니다. 적용기는
파일별 SHA-256을 확인한 뒤 새 `patched_output/PSP/GAME` 구조를 만듭니다.
원본 폴더는 수정하지 않습니다.

- Windows: `apply_prinny1_dlc.bat` 또는 `apply_prinny2_dlc.bat`
- Linux/macOS: `sh apply_prinny1_dlc.sh` 또는 `sh apply_prinny2_dlc.sh`

프리니 1은 `ULJS00150` 폴더를 지정하십시오. 프리니 2는 정식 유럽판 DLC의
세 `NPEH00101` 폴더가 함께 들어 있는 공통 상위 폴더를 지정하면 됩니다. 상위 폴더
이름은 아무거나 가능하며, 입력을 `NPJH50211`로 미리 변환하거나 이름을 바꿀 필요가
없습니다. 적용 결과가 `patched_output/PSP/GAME/NPJH50211`에 생성됩니다. 자세한
내용은 `DLC_INSTALL_v1.5.md`를 참조하십시오.

PPSSPP에서는 메모리스틱 삽입이 켜져 있어야 합니다. 외부 텍스처 교체는 필요하지
않으며 사용하지 않습니다.
