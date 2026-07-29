from pathlib import Path
import struct


FILE = Path(
    "workspace/unpack/SCRIPT/G9system.nsf"
)


data = FILE.read_bytes()


count = struct.unpack_from(
    "<I",
    data,
    0x08
)[0]


print(
    "COUNT:",
    count
)


offsets=[]


for i in range(count):

    pos=0x20+i*8

    ptr, val = struct.unpack_from(
        "<II",
        data,
        pos
    )

    offsets.append(val)



print(
    "LAST OFFSET:",
    hex(max(offsets))
)


candidates=[]


for start in range(
    0x400,
    len(data)-2746,
    4
):

    score=0

    for off in offsets[:20]:

        p=start+off

        if p >= len(data):
            break


        b=data[p]


        # SJIS 가능 영역
        if (
            b>=0x81
            and b<=0xEF
        ):
            score+=1


        # ASCII 가능
        elif (
            0x20 <= b <=0x7E
        ):
            score+=1



    candidates.append(
        (
            score,
            start
        )
    )



candidates.sort(
    reverse=True
)


print(
    "TOP candidates"
)


for x in candidates[:20]:

    print(
        hex(x[1]),
        x[0]
    )
