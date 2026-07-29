import struct



def pack_u32(v):

    return struct.pack(
        "<I",
        v
    )



def rebuild_nsf(
    original,
    entries,
    output
):

    with open(
        original,
        "rb"
    ) as f:

        src=f.read()


    table_size = 0x20


    header = src[:table_size]


    blob=b""

    offsets=[]


    pos=0


    for data in entries:

        offsets.append(
            pos
        )

        blob += data

        pos += len(data)



    table=b""

    for off in offsets:

        table += pack_u32(
            off
        )


    result = (
        header
        +
        table
        +
        blob
    )


    with open(
        output,
        "wb"
    ) as f:

        f.write(
            result
        )


    print(
        "REBUIlD:",
        output
    )

    print(
        "SIZE:",
        len(result)
    )
