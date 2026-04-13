"""polyvoice-vocab command line."""

from __future__ import annotations

import argparse
from pathlib import Path

from polyvoice.vocab.adapters import generate
from polyvoice.vocab.extract import default_candidates_out, default_review_out, extract
from polyvoice.vocab.heuristic_curate import curate, default_curated_out
from polyvoice.vocab.ime_import import import_ime
from polyvoice.vocab.merge import merge
from polyvoice.vocab.scan import default_scan_out, scan


def main() -> None:
    parser = argparse.ArgumentParser(prog="polyvoice-vocab")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--redact", action="store_true", help="apply stricter snippet redaction")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan_p = sub.add_parser("scan")
    scan_p.add_argument("--root", default="~/.claude/projects")
    scan_p.add_argument("--out", type=Path, default=None)

    candidates_p = sub.add_parser("candidates")
    candidates_p.add_argument("--input", type=Path, required=True)
    candidates_p.add_argument("--out", type=Path, default=default_candidates_out())
    candidates_p.add_argument("--review-out", type=Path, default=default_review_out())
    candidates_p.add_argument("--limit", type=int, default=400)

    extract_p = sub.add_parser("extract", help="legacy alias for candidates")
    extract_p.add_argument("--input", type=Path, required=True)
    extract_p.add_argument("--out", type=Path, default=default_candidates_out())
    extract_p.add_argument("--review-out", type=Path, default=default_review_out())
    extract_p.add_argument("--limit", type=int, default=400)

    ime_p = sub.add_parser("ime-import")
    ime_p.add_argument("--txt", action="append", type=Path, required=True)
    ime_p.add_argument("--out", type=Path, default=default_candidates_out())

    curate_p = sub.add_parser("curate")
    curate_p.add_argument("--mode", choices=["heuristic", "skill", "llm"], default="heuristic")
    curate_p.add_argument("--input", type=Path, default=default_candidates_out())
    curate_p.add_argument("--out", type=Path, default=None)

    merge_p = sub.add_parser("merge")
    merge_p.add_argument("--input", action="append", type=Path, default=None)
    merge_p.add_argument("--vocab-dir", type=Path, default=Path("vocab"))

    gen_p = sub.add_parser("gen")
    gen_p.add_argument("--vocab-dir", type=Path, default=Path("vocab"))

    build_p = sub.add_parser("build")
    build_p.add_argument("--root", default="~/.claude/projects")
    build_p.add_argument("--mode", choices=["heuristic", "skill", "llm"], default="heuristic")
    build_p.add_argument("--limit", type=int, default=400)
    build_p.add_argument("--vocab-dir", type=Path, default=Path("vocab"))

    args = parser.parse_args()
    strict_redact = bool(args.redact)

    if args.cmd == "scan":
        out = args.out or default_scan_out()
        count = scan(Path(args.root).expanduser(), out, strict_redact=strict_redact, dry_run=args.dry_run)
        print(f"{'would write' if args.dry_run else 'wrote'} {count} rows to {out}")
    elif args.cmd in {"candidates", "extract"}:
        count = extract(
            args.input,
            args.out,
            args.review_out,
            limit=args.limit,
            strict_redact=strict_redact,
            dry_run=args.dry_run,
        )
        print(f"{'would write' if args.dry_run else 'wrote'} {count} candidates to {args.out}")
    elif args.cmd == "ime-import":
        count = import_ime(args.txt, args.out, dry_run=args.dry_run)
        print(f"{'would import' if args.dry_run else 'imported'} {count} IME phrases to {args.out}")
    elif args.cmd == "curate":
        out = args.out or default_curated_out()
        _run_curate(args.mode, args.input, out, dry_run=args.dry_run)
    elif args.cmd == "merge":
        count = merge(args.vocab_dir, args.input, dry_run=args.dry_run)
        print(f"{'would merge' if args.dry_run else 'merged'} {count} entries into {args.vocab_dir / 'master.jsonl'}")
    elif args.cmd == "gen":
        files = generate(args.vocab_dir, dry_run=args.dry_run)
        for path in files.values():
            print(path)
    elif args.cmd == "build":
        _build(args, strict_redact=strict_redact)


def _run_curate(mode: str, input_path: Path, out: Path, *, dry_run: bool) -> Path:
    if mode == "heuristic":
        count = curate(input_path, out, dry_run=dry_run)
        print(f"{'would write' if dry_run else 'wrote'} {count} curated entries to {out}")
        return out
    if mode == "skill":
        print("Skill mode uses vocab/curation_prompt.md + vocab/candidates.jsonl.")
        print("Run Claude Code with skills/polyvoice-vocab-curate, then write curated JSONL or master.jsonl.")
        return out
    raise NotImplementedError("llm curation mode is reserved for a later implementation")


def _build(args: argparse.Namespace, *, strict_redact: bool) -> None:
    scan_out = default_scan_out()
    rows = scan(Path(args.root).expanduser(), scan_out, strict_redact=strict_redact, dry_run=args.dry_run)
    print(f"{'would write' if args.dry_run else 'wrote'} {rows} rows to {scan_out}")
    candidates = args.vocab_dir / "candidates.jsonl"
    review = args.vocab_dir / "candidates_review.md"
    count = extract(scan_out, candidates, review, limit=args.limit, strict_redact=strict_redact, dry_run=args.dry_run)
    print(f"{'would write' if args.dry_run else 'wrote'} {count} candidates to {candidates}")
    curated = default_curated_out()
    _run_curate(args.mode, candidates, curated, dry_run=args.dry_run)
    merged = merge(args.vocab_dir, [curated], dry_run=args.dry_run)
    print(f"{'would merge' if args.dry_run else 'merged'} {merged} entries into {args.vocab_dir / 'master.jsonl'}")
    files = generate(args.vocab_dir, dry_run=args.dry_run)
    for path in files.values():
        print(path)
