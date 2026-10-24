"""RecallGuard entry point (AGENTS.md §9). Owner: C.

  python run.py --input input_examples/example_1.json          # one run, prints RunResult JSON
  python run.py --input input_examples/example_1.json --sample # force SAMPLE_MODE
  python run.py --serve                                        # API on 0.0.0.0:$PORT
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main(argv: list[str] | None = None) -> int:
    load_dotenv(override=False)  # real environment variables win over .env
    parser = argparse.ArgumentParser(description="RecallGuard: recall exposure review (for pharmacist review)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input", type=Path, help="request JSON in the AGENTS.md §7.1 format")
    mode.add_argument("--serve", action="store_true", help="start the HTTP API")
    parser.add_argument("--sample", action="store_true", help="force SAMPLE_MODE=true (no credentials, no network)")
    parser.add_argument("--output", type=Path, help="also write the RunResult JSON to this file")
    args = parser.parse_args(argv)

    if args.sample:
        os.environ["SAMPLE_MODE"] = "true"

    if args.serve:
        import uvicorn

        uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
        return 0

    from app.runner import execute
    from app.schemas import RunRequest

    try:
        request = RunRequest.model_validate_json(args.input.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: input does not match AGENTS.md §7.1: {exc}", file=sys.stderr)
        return 2

    result = execute(request)
    text = result.model_dump_json(indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
