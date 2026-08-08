#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import time

from Xlib import X, XK, display
from Xlib.ext import xtest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    arguments = parser.parse_args()

    if not 1.0 <= arguments.duration <= 55.0:
        raise ValueError("duration은 1~55초여야 합니다.")

    subprocess.run(["wmctrl", "-ia", arguments.window], check=True)
    connection = display.Display()

    def keycode(name: str) -> int:
        value = connection.keysym_to_keycode(XK.string_to_keysym(name))
        if value == 0:
            raise ValueError(f"X11 키를 찾지 못했습니다: {name}")
        return value

    right = keycode("Right")
    jump = keycode("z")
    attack = keycode("a")

    def tap(code: int, hold: float = 0.06) -> None:
        xtest.fake_input(connection, X.KeyPress, code)
        connection.sync()
        time.sleep(hold)
        xtest.fake_input(connection, X.KeyRelease, code)
        connection.sync()

    xtest.fake_input(connection, X.KeyPress, right)
    connection.sync()
    started = time.monotonic()
    iteration = 0

    try:
        while time.monotonic() - started < arguments.duration:
            tap(attack)
            if iteration % 3 == 0:
                tap(jump, 0.12)
            iteration += 1
            time.sleep(0.14)
    finally:
        xtest.fake_input(connection, X.KeyRelease, right)
        connection.sync()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
