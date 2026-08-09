프리니 ~제가 주인공이여도 되겠슴까?~ 한국어 패치 v1.0
==========================================================

이 배포본은 게임 ISO가 아니라 xdelta 차이 패치입니다.
정품에서 직접 추출한 아래 원본 ISO가 필요합니다.

[필수 원본]
파일 크기: 500,465,664 바이트
SHA-256: af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03

[패치 파일]
Prinny_ULJS00150_KR_v1.0.xdelta
파일 크기: 1,125,683 바이트 (약 1.07 MiB)
SHA-256: bc28e65bd33f1a36ace79aa5bef82813e4c74c7c15a3864750e1082ab263fd91

[적용 방법]
1. 원본 ISO의 SHA-256이 위 값과 같은지 확인합니다.
2. 원본 ISO, xdelta 파일, xdelta3 실행 파일을 같은 폴더에 둡니다.
3. 다음 명령을 실행합니다.

   Windows:
   xdelta3.exe -d -s game.iso Prinny_ULJS00150_KR_v1.0.xdelta Prinny_ULJS00150_KR_v1.0.iso

   Linux:
   xdelta3 -d -s game.iso Prinny_ULJS00150_KR_v1.0.xdelta Prinny_ULJS00150_KR_v1.0.iso

[완성 ISO 검증값]
파일 크기: 500,465,664 바이트
SHA-256: bce03d90f75f8ea197a449ff411b5c64aebb55865595e361fd69acfcf1901ee5

[v1.0 기준]
- 사용자 확인을 거친 현재 번역·대사·내부 UI 텍스처 수정 내용을 포함합니다.
- 제한시간 중앙 안내와 우하단 HUD를 게임 내부 ANIME.DAT에 한국어화했습니다.
- 제한시간 숫자는 별도 동적 텍스처로 유지됩니다.
- PPSSPP 외부 텍스처 교체 기능이 필요하지 않습니다.
- 현재 제한시간 글자 명암을 포함한 화면 상태를 사용자가 완성 배포 기준으로 승인했습니다.
- 원본과 완성 ISO의 파일 경로 20개, 모든 LBA, LBA 정렬 순서가 동일함을 검증했습니다.
- ISO를 재배열하지 않고 원본 파일 슬롯에 수정 자원만 덮어쓴 구조입니다.

원본 ISO와 완성 ISO는 이 배포 폴더에 포함하지 않습니다.
