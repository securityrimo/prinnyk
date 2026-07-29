def parse_control(cmd):

    args = cmd["args"]

    op = cmd["opcode"]


    if op == "0x43":

        if len(args) >= 3:

            return {

                "type":
                    "POSITION",

                "x":
                    int(args[0],16),

                "y":
                    int(args[2],16)

            }


    if op == "0x44":

        return {

            "type":
                "VALUE",

            "value":
                args

        }


    if op == "0x01":

        return {

            "type":
                "PARAM",

            "value":
                args

        }


    return {

        "type":
            "UNKNOWN",

        "raw":
            cmd["raw"]

    }



def convert_commands(commands):

    result = []


    for cmd in commands:

        result.append(
            parse_control(cmd)
        )


    return result



def convert_entries(entries):

    output = []


    for entry in entries:

        output.append({

            "index":
                entry["index"],

            "offset":
                entry["offset"],

            "script":

                convert_commands(
                    entry["commands"]
                )

        })


    return output
