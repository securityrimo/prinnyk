# 프리니 1·2 비공식 한국어 패치 V1.3

프리니 1 `ULJS00150`과 프리니 2 `NPJH50211`의 최종 한국어 패치입니다.
게임 ISO와 원본 DLC는 포함하지 않습니다. 정품에서 직접 추출한 무수정 일본판
ISO와 원본 DLC에 xdelta 패치를 적용하십시오.

다운로드: https://github.com/sizz1214-lang/prinnyk/releases/tag/v1.3

## 구성

- `Prinny1_ULJS00150_KR_v1.3_BASE.xdelta` — 프리니 1 본편
- `Prinny1_ULJS00150_DLC_ALL_KO_v1.3.xdelta` — 프리니 1 DLC 3종 일괄
- `Prinny2_NPJH50211_KR_v1.3_BASE.xdelta` — 프리니 2 본편
- `Prinny2_NPJH50211_DLC_ALL_KO_v1.3.xdelta` — 프리니 2 DLC 전체 일괄

## 본편 적용

```bash
xdelta3 -d -s "원본.iso" "V1.3.xdelta" "한글판.iso"
```

| 게임 | 원본 SHA-256 | 패치 결과 SHA-256 |
|---|---|---|
| 프리니 1 | `af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03` | `c88e5ade8e114b560da23da32fa908c4b1c2713e1ab051d6cb90a225058e7397` |
| 프리니 2 | `4c509ba4d8d2dfcd2635228526fa2955e25ccbb511878861ed31ecfcf2829087` | `d1ba19409596efc4866095ba433a2e945d68e5b30f1d2b34bccf2e013f2c69a4` |

## DLC 설치

DLC xdelta에는 원본 DLC ZIP을 소스로 지정하고 결과 파일명을 `DLC_KO_INSTALL.zip`으로
지정합니다. 결과 ZIP을 풀어 나온 `PSP` 폴더를 메모리스틱 루트에 복사합니다.

- 프리니 1: `ms0:/PSP/GAME/ULJS00150/`
- 프리니 2: `ms0:/PSP/GAME/NPJH50211/`

PPSSPP에서는 설정의 메모리스틱 삽입이 켜져 있어야 합니다. 외부 텍스처 교체는
필요하지 않으며 사용하지 않습니다.
