#!/usr/bin/env python3
"""Project-specific recommendations and observations, separate from runtime gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
import tram
import harness_observation as observation


def main(argv=None):
    parser = tram.JsonParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True, parser_class=tram.JsonParser)
    sub.add_parser("contract")
    for action in ("configure", "recommend", "search", "record", "show", "evaluate"):
        command = sub.add_parser(action)
        command.add_argument("--project", required=True)
        if action in ("recommend", "record", "show"):
            command.add_argument("--slug", required=True)
        if action in ("configure", "record", "evaluate"):
            command.add_argument("--file", required=True)
        if action in ("configure", "record"):
            command.add_argument("--expected-digest", required=True)
        if action == "configure":
            command.add_argument("--expected-revision", required=True, type=int)
        if action in ("recommend", "show"):
            command.add_argument("--request", required=action == "recommend")
        if action in ("recommend", "search", "show"):
            command.add_argument("--path", action="append")
        if action == "recommend":
            command.add_argument("--omit", action="append")
        if action == "search":
            command.add_argument("--query", required=True)
    try:
        args = vars(parser.parse_args(argv))
        action = args.pop("action")
        result = getattr(observation, action)(**args)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, sort_keys=True))
        return 0
    except tram.TramError as error:
        print(json.dumps({"ok": False, "errorCode": error.code, "message": str(error), **error.details}, ensure_ascii=False))
        return 2
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "errorCode": "INVALID_JSON" if isinstance(error, ValueError) else "IO_ERROR", "message": type(error).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
