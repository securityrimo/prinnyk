import os
import json

from .decoder import decode_entries


def read_u32(data, offset):
    return int.from_bytes(
        data[offset:offset+4],
        "little"
    )


def parse_offsets(data, table, count):

    result = []

    for i in range(count):

        off = read_u32(
            data,
            table + i * 4
        )

        result.append(off)

    return result



def extract_entries(data, blob, offsets):

    result = []

    for i, off in enumerate(offsets):

        start = blob + off


        if i + 1 < len(offsets):
            end = blob + offsets[i+1]
        else:
            end = len(data)


        chunk = data[start:end]


        result.append({

            "index": i,

            "offset": hex(off),

            "hex":
                chunk.hex(" "),

            "size":
                len(chunk)

        })


    return result



def analyze_nsf(path):

    with open(
        path,
        "rb"
    ) as f:

        data = f.read()


    size = len(data)


    blob_size = read_u32(
        data,
        4
    )


    count = read_u32(
        data,
        0x10
    )


    table = 0x20


    blob = size - blob_size


    offsets = parse_offsets(
        data,
        table,
        count
    )


    entries = extract_entries(
        data,
        blob,
        offsets
    )


    decoded = decode_entries(
        entries
    )


    return {

        "file":
            os.path.basename(path),

        "size":
            size,

        "blob":
            hex(blob),

        "blob_size":
            blob_size,

        "count":
            count,

        "entries":
            decoded

    }



def main():

    import sys


    if len(sys.argv) < 2:
        print(
            "usage: parser.py file"
        )
        return


    result = analyze_nsf(
        sys.argv[1]
    )


    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
