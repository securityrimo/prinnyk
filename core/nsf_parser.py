import struct
import os


def parse_nsf(filename):

    with open(filename, "rb") as f:
        data = f.read()

    result = {}

    result["file"] = filename
    result["size"] = len(data)


    # header
    blob_size = struct.unpack_from(
        "<I",
        data,
        4
    )[0]

    count = struct.unpack_from(
        "<H",
        data,
        0
    )[0]


    table_offset = 0x20

    offsets=[]

    for i in range(count):
        off = struct.unpack_from(
            "<H",
            data,
            table_offset+i*2
        )[0]

        offsets.append(off)


    blob_start = (
        len(data)
        - blob_size
    )


    entries=[]


    for i,off in enumerate(offsets):

        pos = blob_start + off

        if i+1 < len(offsets):
            end = blob_start + offsets[i+1]
        else:
            end = len(data)


        chunk=data[pos:end]


        entries.append(
            {
                "id":i,
                "offset":hex(off),
                "hex":chunk.hex(" "),
                "size":len(chunk)
            }
        )


    result["blob_start"]=hex(blob_start)
    result["blob_size"]=blob_size
    result["count"]=count
    result["entries"]=entries


    return result
