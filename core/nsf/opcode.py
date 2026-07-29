COMMANDS = {

    0x43:
        "CONTROL",

    0x44:
        "VALUE",

    0x01:
        "ARG",

}



def decode_command(chunk):

    op = chunk[0]


    name = COMMANDS.get(
        op,
        "DATA"
    )


    return {

        "opcode":
            f"0x{op:02X}",

        "command":
            name,

        "args":
            [
                f"0x{x:02X}"
                for x in chunk[1:]
            ],

        "raw":
            chunk.hex(" ")

    }



def split_commands(data):

    result = []

    i = 0


    while i < len(data):

        op = data[i]


        if op in (
            0x43,
            0x44,
            0x01
        ):

            size = 4

        else:

            size = 1


        chunk = data[
            i:i+size
        ]


        result.append(
            decode_command(chunk)
        )


        i += size


    return result
