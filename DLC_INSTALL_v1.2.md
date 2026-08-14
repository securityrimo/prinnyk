# DLC v1.2 설치 안내

각 DLC ZIP은 xdelta 패치, 안전 적용기, 원본·결과 해시 manifest를 포함합니다.

1. 원하는 DLC 패치 ZIP을 별도 폴더에 풉니다.
2. 원본 `ULJS00150.zip` 또는 `NPJH50211.zip`을 준비합니다.
3. `apply.sh` 또는 `apply.bat`에 원본과 출력 경로를 지정합니다.
4. 출력된 `PSP` 폴더를 메모리스틱 루트에 복사합니다.

```bash
./apply.sh "/path/to/ULJS00150.zip" "/path/to/output"
```

프리니1 DLC 3개를 모두 적용할 때는 세 패치팩에 동일한 원본 ZIP과 동일한 출력
폴더를 사용합니다. 적용 순서는 관계없으며 기존 한글 DLC는 보존됩니다.

필요 도구는 Python 3와 xdelta3입니다. Windows에서는 `xdelta3.exe`를 패치팩을
푼 폴더에 놓아도 됩니다.
