# DLC V1.3 설치 안내

## 중요

원본 DLC ZIP 파일을 xdelta의 `-s` 소스로 지정하지 마십시오. ZIP은 다시 압축할 때마다
메타데이터와 파일 배치가 바뀔 수 있습니다. V1.3 DLC 패치는 압축을 푼 폴더 안에서
필요한 EDAT의 이름과 내용만 검증하며 ZIP 해시는 사용하지 않습니다.

GitHub 릴리스에서 `Prinny_DLC_Folder_Patcher_v1.3.zip`을 받아 한 폴더에 푸십시오.
이 패키지에는 프리니 1·2 DLC xdelta와 Windows/Linux용 적용기가 함께 들어 있습니다.

## 프리니 1

1. 원본 DLC를 풀어 다음 파일이 든 `ULJS00150` 폴더를 준비합니다.
   `DL0000.EDAT`, `DL0001.EDAT`, `DL0002.EDAT`, `PARAM.PBP`
2. Windows에서는 `apply_prinny1_dlc.bat`을 실행하고 `ULJS00150` 폴더를 지정합니다.
3. 명령줄에서는 다음처럼 실행할 수 있습니다.

```bash
python apply_dlc_folder_v1_3.py prinny1 "원본/ULJS00150" "patched_output"
```

## 프리니 2

1. 다음 세 폴더가 들어 있는 공통 상위 `NPJH50211` 폴더를 준비합니다.
   - `Asagi Wars Premium Special Ticket/NPEH00101`
   - `Netherworld Radish/NPEH00101`
   - `Super Netherworld/NPEH00101`
2. Windows에서는 `apply_prinny2_dlc.bat`을 실행하고 위 `NPJH50211` 폴더를 지정합니다.
3. 명령줄에서는 다음처럼 실행할 수 있습니다.

```bash
python apply_dlc_folder_v1_3.py prinny2 "원본/NPJH50211" "patched_output"
```

## 복사 위치

완료 후 `patched_output` 안의 `PSP` 폴더를 메모리스틱 루트에 복사합니다.

- 프리니 1: `ms0:/PSP/GAME/ULJS00150/`
- 프리니 2: `ms0:/PSP/GAME/NPJH50211/`

적용기는 원본 폴더를 덮어쓰지 않습니다. `xdelta3` 또는 `xdelta3.exe`가 PATH나 패치
폴더에 있어야 하며, Python 3이 필요합니다. DLC는 ISO 내부에 합치지 않습니다.
