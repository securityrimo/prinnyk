import os
import json

from core.nsf import analyze_nsf


def analyze(path):

    result = analyze_nsf(path)


    os.makedirs(
        "workspace/analysis",
        exist_ok=True
    )


    name = os.path.basename(path)

    output = (
        "workspace/analysis/"
        + name
        + ".json"
    )


    with open(
        output,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            result,
            f,
            indent=2,
            ensure_ascii=False
        )


    return output
