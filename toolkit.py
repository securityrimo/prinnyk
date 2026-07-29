#!/usr/bin/env python3

import argparse

from core.pipeline import analyze


def main():

    parser = argparse.ArgumentParser(
        prog="PrinnyReverseToolkit"
    )

    sub = parser.add_subparsers(
        dest="command"
    )


    a = sub.add_parser(
        "analyze"
    )

    a.add_argument(
        "file"
    )


    args = parser.parse_args()


    if args.command == "analyze":

        print("="*60)
        print("PrinnyReverseToolkit")
        print("="*60)

        out = analyze(
            args.file
        )

        print()
        print("SAVED:")
        print(out)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
