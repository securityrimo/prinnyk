# DLC V1.5 설치 안내

## 중요

원본 DLC ZIP 파일을 xdelta의 `-s` 소스로 지정하지 마십시오. V1.5 DLC 패치는
압축을 푼 폴더 안에서 필요한 EDAT의 이름과 내용만 검증하며 ZIP 해시는 사용하지 않습니다.

GitHub 릴리스에서 `Prinny_DLC_Folder_Patcher_v1.5.zip`을 받아 한 폴더에 푸십시오.
이 패키지에는 프리니 1·2 DLC xdelta와 Windows/Linux용 적용기가 함께 들어 있습니다.

## 프리니 1

1. 원본 DLC를 풀어 `DL0000.EDAT`, `DL0001.EDAT`, `DL0002.EDAT`, `PARAM.PBP`가
   들어 있는 `ULJS00150` 폴더를 준비합니다.
2. Windows에서는 `apply_prinny1_dlc.bat`을 실행합니다.
3. 명령줄에서는 다음처럼 실행할 수 있습니다.

```bash
python apply_dlc_folder_v1_5.py prinny1 "원본/ULJS00150" "patched_output"
```

## 프리니 2

1. 정식 유럽판 DLC를 압축 해제하고 다음 세 폴더가 함께 들어 있는 공통 상위 폴더를
   준비합니다. 상위 폴더 이름은 아무거나 가능합니다(예: `Prinny2_Europe_DLC`).
   - `Asagi Wars Premium Special Ticket/NPEH00101`
   - `Netherworld Radish/NPEH00101`
   - `Super Netherworld/NPEH00101`
2. `NPJH50211`로 사전 변환하거나 폴더 이름을 변경하지 마십시오. 적용기가 세 폴더의
   원본 EDAT를 파일명과 SHA-256으로 직접 찾아 판별합니다.
3. Windows에서는 `apply_prinny2_dlc.bat`을 실행합니다.
4. 명령줄에서는 다음처럼 실행할 수 있습니다.

```bash
python apply_dlc_folder_v1_5.py prinny2 "원본/Prinny2_Europe_DLC" "patched_output"
```

완료 후 일본판용 결과가 `patched_output/PSP/GAME/NPJH50211`에 생성됩니다.
`patched_output` 안의 `PSP` 폴더를 메모리스틱 루트에 복사합니다.
적용기는 원본 폴더를 덮어쓰지 않습니다. `xdelta3`와 Python 3이 필요합니다.

완성된 DLC 바이너리는 배포물에 포함되지 않습니다. 반드시 본인이 보유한 원본 DLC를
압축 해제한 폴더에 위 적용기를 사용하십시오.
