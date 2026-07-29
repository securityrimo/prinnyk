from pathlib import Path
import json
import unicodedata


class StringScanner:

    def __init__(
        self,
        min_length=4,
        max_length=200
    ):
        self.min_length = min_length
        self.max_length = max_length


    # -------------------------------------
    # 파일 스캔
    # -------------------------------------
    def scan_file(self, path):

        path = Path(path)

        data = path.read_bytes()

        results = []

        results += self.scan_sjis(data)
        results += self.scan_ascii(data)

        results.sort(
            key=lambda x: x["offset"]
        )

        return self.remove_duplicate(results)



    # -------------------------------------
    # JSON 저장
    # -------------------------------------
    def save_json(self, output, strings):

        output = Path(output)

        output.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with open(
            output,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                strings,
                f,
                ensure_ascii=False,
                indent=4
            )



    # -------------------------------------
    # ASCII
    # -------------------------------------
    def scan_ascii(self, data):

        results = []

        start = None
        buf = bytearray()


        for i, b in enumerate(data):

            if 0x20 <= b <= 0x7E:

                if start is None:
                    start = i

                buf.append(b)


            else:

                if self.valid_ascii(buf):

                    text = buf.decode(
                        "ascii",
                        errors="ignore"
                    )

                    results.append({

                        "offset": start,
                        "length": len(buf),
                        "encoding": "ascii",
                        "text": text,
                        "translated": ""

                    })


                start = None
                buf = bytearray()


        return results



    # -------------------------------------
    # SHIFT-JIS
    # -------------------------------------
    def scan_sjis(self, data):

        results = []

        i = 0


        while i < len(data):

            start = i

            buf = bytearray()


            while i < len(data):

                b = data[i]


                # ASCII 포함
                if 0x20 <= b <= 0x7E:

                    buf.append(b)

                    i += 1

                    continue


                # SJIS 1바이트
                if (
                    0x81 <= b <= 0x9F
                    or
                    0xE0 <= b <= 0xFC
                ):

                    if i + 1 >= len(data):
                        break


                    b2 = data[i+1]


                    if (
                        0x40 <= b2 <= 0xFC
                        and b2 != 0x7F
                    ):

                        buf.append(b)
                        buf.append(b2)

                        i += 2

                        continue


                break



            if self.valid_sjis(buf):

                try:

                    text = buf.decode(
                        "shift_jis"
                    )

                    if self.is_game_text(text):

                        results.append({

                            "offset": start,
                            "length": len(buf),
                            "encoding": "shift-jis",
                            "text": text,
                            "translated": ""

                        })


                except:

                    pass



            i += 1


        return results



    # -------------------------------------
    # ASCII 필터
    # -------------------------------------
    def valid_ascii(self, buf):

        length = len(buf)

        if length < self.min_length:
            return False


        if length > self.max_length:
            return False


        return True



    # -------------------------------------
    # SJIS 필터
    # -------------------------------------
    def valid_sjis(self, buf):

        length = len(buf)

        if length < self.min_length:
            return False


        if length > self.max_length:
            return False


        return True



    # -------------------------------------
    # 게임 대사 판별
    # -------------------------------------
    def is_game_text(self, text):

        japanese = 0
        normal = 0


        for c in text:

            name = unicodedata.name(
                c,
                ""
            )


            if (
                "HIRAGANA" in name
                or
                "KATAKANA" in name
                or
                "CJK" in name
            ):

                japanese += 1


            elif c.isascii():

                normal += 1



        total = japanese + normal


        if total == 0:
            return False


        ratio = japanese / total


        # 일본어 비율
        if japanese >= 2:
            return True


        return False



    # -------------------------------------
    # 중복 제거
    # -------------------------------------
    def remove_duplicate(self, items):

        result = []

        seen = set()


        for x in items:

            key = (
                x["offset"],
                x["length"]
            )

            if key not in seen:

                seen.add(key)

                result.append(x)


        return result
