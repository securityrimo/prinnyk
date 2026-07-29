import struct
import json
from pathlib import Path


class NSFStringExtractor:

    def __init__(self, filename):
        self.filename = Path(filename)
        self.data = self.filename.read_bytes()

        self.count = 0
        self.blob_size = 0
        self.table_offset = 0x20
        self.blob_offset = 0


    def parse_header(self):

        self.blob_size = struct.unpack_from(
            "<I",
            self.data,
            4
        )[0]

        self.count = struct.unpack_from(
            "<I",
            self.data,
            8
        )[0]

        self.blob_offset = (
            self.table_offset +
            self.count * 8
        )


        print(
            f"NSF count : {self.count}"
        )

        print(
            f"헤더 +0x04 blob size : {self.blob_size} bytes"
        )

        print(
            f"문자열 테이블 위치 : 0x{self.table_offset:X}"
        )

        print(
            f"문자열 blob 위치 : 0x{self.blob_offset:X}"
        )

        print(
            f"예상 파일 크기 : {self.blob_offset+self.blob_size}"
        )

        print(
            f"실제 파일 크기 : {len(self.data)}"
        )

        print(
            f"차이 : {len(self.data)-(self.blob_offset+self.blob_size)}"
        )


    def clean_text(self, raw):

    result = bytearray()

    i = 0

    while i < len(raw):

        b = raw[i]


        # command Cx
        if b == 0x43:

            i += 3
            continue


        # command 32
        if b == 0x32:

            i += 3
            continue


        # command 44
        if b == 0x44:

            i += 3
            continue


        # terminator
        if b == 0x00:

            break


        # control
        if b < 0x20:

            i += 1
            continue


        result.append(b)

        i += 1


    try:

        return result.decode(
            "shift_jis"
        )


    except:

        return result.decode(
            "shift_jis",
            errors="replace"
        )

    def extract(self):

        result=[]


        for i in range(self.count):

            ptr, off = struct.unpack_from(
                "<II",
                self.data,
                self.table_offset+i*8
            )


            pos=self.blob_offset+off


            if pos >= len(self.data):
                continue


            chunk=self.data[pos:pos+128]


            text=self.clean_text(chunk)


            result.append(
                {
                    "id":i,
                    "offset":off,
                    "text":text
                }
            )


            if i<20:
                print(
                    f"[{i:03}] "
                    f"0x{off:04X}"
                )

                print(text)


        return result



    def save_json(self, out):

        items=self.extract()

        Path(out).write_text(
            json.dumps(
                items,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        print()
        print(
            f"Saved : {out}"
        )
