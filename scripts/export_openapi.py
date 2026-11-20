"""Export or verify the checked-in FastAPI contract without opening user storage."""

import argparse
import json
from pathlib import Path

from stridelog.api.app import openapi_schema

CONTRACT = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    rendered = json.dumps(openapi_schema(), indent=2, sort_keys=True) + "\n"
    if arguments.check:
        if not CONTRACT.is_file() or CONTRACT.read_text(encoding="utf-8") != rendered:
            parser.error("openapi.json is missing or out of date; regenerate it with this script.")
        return 0
    CONTRACT.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
