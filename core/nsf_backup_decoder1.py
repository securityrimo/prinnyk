#!/usr/bin/env python3

import sys
import os
import json


def sjis_char(data,i):

    if i+1 >= len(data):
        return None,1

    a=data[i]
    b=data[i+1]

    if (
        (0x81<=a<=0x9F or 0xE0<=a<=0xFC)
        and
        (
            0x40<=b<=0x7E
            or
            0x80<=b<=0xFC
        )
    ):
        try:
            return bytes([a,b]).decode(
                "shift_jis"
            ),2
        except:
            pass

    return None,1



def decode_script(raw):

    text=[]
    cmds=[]

    i=0


    while i<len(raw):

        b=raw[i]


        # known NIS commands
        if b in (
            0x43, # C
            0x44, # D
            0x32, # 2
            0x01,
            0xFF
        ):

            size=1

            # command parameter
            if i+3<len(raw):
                chunk=raw[i:i+4]
                cmds.append(
                    chunk.hex(" ")
                )
                i+=4
                continue


        ch,n=sjis_char(raw,i)


        if ch:

            text.append(ch)
            i+=n
            continue


        # printable ascii
        if 0x20<=b<=0x7e:
            text.append(chr(b))


        i+=1


    return "".join(text),cmds




def parse(path):

    with open(path,"rb") as f:
        data=f.read()


    size=len(data)

    blob_size=int.from_bytes(
        data[4:8],
        "little"
    )

    count=int.from_bytes(
        data[8:12],
        "little"
    )


    table=0x20

    blob=size-blob_size


    print(
        "blob:",
        hex(blob)
    )

    print(
        "count:",
        count
    )


    result=[]


    for idx in range(count):

        ent=table+idx*8

        ptr=int.from_bytes(
            data[ent:ent+4],
            "little"
        )

        off=int.from_bytes(
            data[ent+4:ent+8],
            "little"
        )


        pos=blob+off


        if idx+1<count:

            noff=int.from_bytes(
                data[ent+12:ent+16],
                "little"
            )

            end=blob+noff

        else:
            end=size


        raw=data[pos:min(end,size)]


        text,cmds=decode_script(raw)


        item={
            "id":idx,
            "ptr":hex(ptr),
            "offset":hex(off),
            "file_pos":hex(pos),
            "raw":raw.hex(),
            "commands":cmds,
            "text":text
        }


        result.append(item)


        if idx<20:

            print(
                f"[{idx:03}]",
                hex(off)
            )

            print(
                "CMD:",
                cmds[:3]
            )

            print(
                "TEXT:",
                repr(text)
            )



    out="workspace/nsf/G9system_script.json"

    os.makedirs(
        "workspace/nsf",
        exist_ok=True
    )


    with open(out,"w",encoding="utf-8") as f:

        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
        )


    print(
        "Saved:",
        out
    )



if __name__=="__main__":

    parse(sys.argv[1])
