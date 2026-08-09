# 프리니 한국어 패치 v1.0

`프리니 ~제가 주인공이여도 되겠슴까?~`(ULJS00150)용 한국어 패치입니다.
이 저장소는 게임 ISO가 아닌 xdelta 차이 패치만 배포합니다.

## 다운로드

[GitHub Releases의 v1.0](https://github.com/sizz1214-lang/prinnyk/releases/tag/v1.0)에서 다음 중 하나를 받으세요.

- `Prinny_ULJS00150_KR_v1.0.zip`: 안내문과 검증 정보를 포함한 권장 묶음
- `Prinny_ULJS00150_KR_v1.0.xdelta`: 패치 파일만 필요한 경우

다운로드한 파일은 다음 SHA-256으로 확인할 수 있습니다.

| 파일 | SHA-256 |
|---|---|
| `Prinny_ULJS00150_KR_v1.0.zip` | `77ea21b5e0236bdb95db500d5091581c56a443bb593816cbc795185bd63922a2` |
| `Prinny_ULJS00150_KR_v1.0.xdelta` | `bc28e65bd33f1a36ace79aa5bef82813e4c74c7c15a3864750e1082ab263fd91` |

## 필요한 원본

직접 준비한 원본 ISO가 다음 값과 정확히 일치해야 합니다.

| 항목 | 값 |
|---|---|
| 게임 ID | `ULJS00150` |
| 파일 크기 | `500,465,664`바이트 |
| SHA-256 | `af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03` |

해시가 다르면 패치를 강제로 적용하지 마세요. 다른 판본이나 변형 ISO는 지원하지 않습니다.

## 적용 방법

원본 ISO를 `game.iso`라는 이름으로 두었다고 가정합니다.

Windows:

```text
xdelta3.exe -d -s game.iso Prinny_ULJS00150_KR_v1.0.xdelta Prinny_ULJS00150_KR_v1.0.iso
```

Linux:

```bash
xdelta3 -d -s game.iso Prinny_ULJS00150_KR_v1.0.xdelta Prinny_ULJS00150_KR_v1.0.iso
```

완성 ISO의 SHA-256은 다음 값이어야 합니다.

```text
bce03d90f75f8ea197a449ff411b5c64aebb55865595e361fd69acfcf1901ee5
```

## v1.0 특징

- 게임 내부 텍스트, 대사, 제목과 주요 UI 이미지의 한국어화
- 제한시간 중앙 안내와 우하단 HUD를 내부 `ANIME.DAT` 자원으로 한국어화
- 제한시간 숫자 스프라이트와 패널 구조 보존
- PPSSPP 외부 텍스처 교체 기능 불필요
- 원본 ISO의 파일 경로, extent LBA와 LBA 정렬 순서 보존
- PPSSPP 1.20.4 격리 환경에서 사용자 런타임 확인 완료

자세한 빌드·검증 기록은 [기술 로그](TECHNICAL_LOG.md)를 확인하세요.

## 배포 범위

이 배포본에는 원본 또는 완성 ISO, 추출한 게임 파일, 런타임 캡처, 세이브 파일이 포함되지 않습니다.
게임과 관련 상표·저작물의 권리는 각 권리자에게 있습니다. 정당하게 보유한 원본에서 개인적으로 패치를 적용하세요.
