"""CLI dispatcher: python -m duly_assurance <generate|verify|impact|prove|prove-equivalent> ...

Subcommand modules are imported lazily so each can be developed and tested
independently.
"""

import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: python -m duly_assurance "
            "<generate|verify|impact|prove|prove-equivalent> [options]"
        )
        return 0 if argv else 2
    command, rest = argv[0], argv[1:]
    if command == "generate":
        from .generate import main as sub
    elif command == "verify":
        from .verify import main as sub
    elif command == "impact":
        from .impact import main as sub
    elif command == "prove":
        from .prove import main as sub
    elif command == "prove-equivalent":
        from .prove import main_equivalent as sub
    else:
        print(f"unknown command: {command}", file=sys.stderr)
        return 2
    return sub(rest)


if __name__ == "__main__":
    sys.exit(main())
