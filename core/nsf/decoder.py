from .opcode import split_commands
from .semantic import convert_commands



def decode_entries(entries):

    result = []


    for entry in entries:

        raw = bytes.fromhex(
            entry["hex"]
        )


        commands = split_commands(
            raw
        )


        result.append({

            "index":
                entry["index"],

            "offset":
                entry["offset"],

            "size":
                entry["size"],

            "commands":
                commands,

            "semantic":
                convert_commands(
                    commands
                )

        })


    return result
