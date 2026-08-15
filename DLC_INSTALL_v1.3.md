# DLC V1.3 설치 안내

1. 프리니 1은 원본 `ULJS00150.zip`, 프리니 2는 일본판 원본 `NPJH50211.zip`을 준비합니다.
2. 다음처럼 DLC 전체 xdelta를 적용합니다.

```bash
xdelta3 -d -s "원본_DLC.zip" "DLC_ALL_KO_v1.3.xdelta" "DLC_KO_INSTALL.zip"
```

3. 출력된 `DLC_KO_INSTALL.zip`을 풀고, 안의 `PSP` 폴더를 메모리스틱 루트에 복사합니다.

프리니 1 최종 위치는 `ms0:/PSP/GAME/ULJS00150/`, 프리니 2 최종 위치는
`ms0:/PSP/GAME/NPJH50211/`입니다. DLC는 ISO 내부에 합치지 않습니다.
