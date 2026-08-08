#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

from Xlib import X, XK, display
from Xlib.ext import xtest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--key", default="z")
    arguments = parser.parse_args()

    if arguments.count <= 0 or arguments.delay < 0.2:
        raise ValueError("count는 양수, delay는 0.2 이상이어야 합니다.")

    arguments.output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["wmctrl", "-ia", arguments.window],
        check=True,
    )
    connection = display.Display()
    keycode = connection.keysym_to_keycode(
        XK.string_to_keysym(arguments.key)
    )

    if keycode == 0:
        raise ValueError(f"X11 키를 찾지 못했습니다: {arguments.key}")

    for index in range(1, arguments.count + 1):
        xtest.fake_input(connection, X.KeyPress, keycode)
        connection.sync()
        time.sleep(0.08)
        xtest.fake_input(connection, X.KeyRelease, keycode)
        connection.sync()
        time.sleep(arguments.delay)
        subprocess.run(
            [
                "gnome-screenshot",
                "-w",
                "-f",
                str(arguments.output / f"frame_{index:03d}.png"),
            ],
            check=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
