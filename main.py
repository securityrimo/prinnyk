def main():

    parser = argparse.ArgumentParser(
        prog="toolkit.py",
        description="Prinny Reverse Toolkit"
    )

    sub = parser.add_subparsers(dest="command")

    #####################################
    # extract
    #####################################

    p = sub.add_parser(
        "extract",
        help="Extract ISO"
    )

    p.add_argument(
        "iso",
        help="ISO file"
    )

    p.set_defaults(func=cmd_extract)

    #####################################
    # analyze
    #####################################

    p = sub.add_parser(
        "analyze",
        help="Analyze extracted files"
    )

    p.set_defaults(func=cmd_analyze)

    #####################################
    # strings
    #####################################

    p = sub.add_parser(
        "strings",
        help="Extract text"
    )

    p.set_defaults(func=cmd_strings)

    #####################################
    # patch
    #####################################

    p = sub.add_parser(
        "patch",
        help="Build patch"
    )

    p.set_defaults(func=cmd_patch)

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
