"""polyvoice-vocab command line."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from polyvoice.vocab.adapters import generate
from polyvoice.vocab.extract import default_extract_out, extract
from polyvoice.vocab.merge import merge
from polyvoice.vocab.scan import default_scan_out, scan


def main() -> None:
    parser = argparse.ArgumentParser(prog="polyvoice-vocab")
    sub = parser.add_subparsers(dest="cmd", required=True)
    scan_p = sub.add_parser("scan")
    scan_p.add_argument("--root", default="~/.claude/projects")
    scan_p.add_argument("--since")
    scan_p.add_argument("--out", type=Path, default=None)
    extract_p = sub.add_parser("extract")
    extract_p.add_argument("--input", type=Path, required=True)
    extract_p.add_argument("--out", type=Path, default=None)
    extract_p.add_argument("--parallel", type=int, default=5)
    extract_p.add_argument("--model", default="claude-sonnet-4-6")
    sub.add_parser("merge")
    sub.add_parser("gen")
    args = parser.parse_args()

    if args.cmd == "scan":
        del args.since
        out = args.out or default_scan_out()
        print(f"wrote {scan(Path(args.root).expanduser(), out)} rows to {out}")
    elif args.cmd == "extract":
        out = args.out or default_extract_out()
        count = asyncio.run(extract(args.input, out, args.parallel, args.model))
        print(f"wrote {count} phrases to {out}")
    elif args.cmd == "merge":
        print(f"merged {merge()} entries into vocab/master.jsonl")
    elif args.cmd == "gen":
        files = generate()
        for path in files.values():
            print(path)
