from .opcode import COMMANDS


REVERSE = {
    v:k
    for k,v in COMMANDS.items()
}



def encode_command(cmd):

    opcode = int(
        cmd["opcode"],
        16
    )


    args = bytes(
        int(x,16)
        for x in cmd.get(
            "args",
            []
        )
    )


    return bytes(
        [opcode]
    ) + args



def encode_commands(commands):

    data = b""


    for cmd in commands:

        data += encode_command(
            cmd
        )


    return data



def encode_entries(entries):

    result = []

    for e in entries:

        result.append(

            encode_commands(
                e["commands"]
            )

        )


    return result
