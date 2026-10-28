"""CLI entrypoint. Errors and progress never echo report cell values."""
from __future__ import annotations

import argparse
import glob
from pathlib import Path
import sys

from . import __version__
from .core import Limits, SanitizeError, sanitize


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("Expected a positive integer.") from None
    if value < 1:
        raise argparse.ArgumentTypeError("Expected a positive integer.")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sttm-sanitize",
        description="Offline CSV sanitizer. Only upload UPLOAD_reports.zip; keep glossary.json local.",
        epilog="No pip install, server, account, key or Internet required. See README.md.",
    )
    parser.add_argument("--version", action="version", version=f"sttm-sanitize {__version__}")
    parser.add_argument("--input", nargs="+", required=True, metavar="CSV_OR_DIR",
                        help="CSV files, a folder of CSV files (not recursive), or quoted glob patterns.")
    parser.add_argument("--output", required=True, type=Path, metavar="NEW_DIR",
                        help="New output directory. Existing paths are never overwritten.")
    parser.add_argument("--delimiter", default=",", help="Input delimiter; default comma. Use 'tab' for tabs. Output is always comma CSV.")
    parser.add_argument("--encoding", default="utf-8-sig", help="Input encoding, default UTF-8 with optional BOM. Output is UTF-8.")
    parser.add_argument("--max-files", type=positive_int, default=5)
    parser.add_argument("--max-fields", type=positive_int, default=10)
    parser.add_argument("--max-rows", type=positive_int, default=100, help="Data records per CSV, excluding header (default 100).")
    parser.add_argument("--max-file-bytes", type=positive_int, default=10 * 1024 * 1024)
    parser.add_argument("--max-field-chars", type=positive_int, default=131072)
    return parser


def expand_inputs(items: list[str]) -> list[Path]:
    paths = []
    for item in items:
        path = Path(item)
        if path.is_dir():
            matches = sorted((p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".csv"), key=lambda p: p.name)
            if not matches:
                raise SanitizeError("An input folder contains no CSV files.")
            paths.extend(matches)
        elif glob.has_magic(item):
            matches = sorted(Path(p) for p in glob.glob(item))
            if not matches:
                raise SanitizeError("An input pattern matched no files.")
            paths.extend(matches)
        else:
            paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        limits = Limits(args.max_files, args.max_fields, args.max_rows,
                        args.max_file_bytes, args.max_field_chars)
        result = sanitize(expand_inputs(args.input), args.output,
                          delimiter="\t" if args.delimiter == "tab" else args.delimiter,
                          encoding=args.encoding, limits=limits,
                          progress=lambda message: print(message, file=sys.stderr))
    except SanitizeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("CANCELLED: do not use any incomplete output directory.", file=sys.stderr)
        return 130
    except (OSError, ValueError, OverflowError):
        print("ERROR: local I/O or configuration failure. No cell values were logged. If an output folder exists, treat it as incomplete.", file=sys.stderr)
        return 1
    print(f"PASS: {result.datasets} CSV; {result.rows} rows; {result.cells} cells; {result.unique_values} distinct non-empty values.")
    print(f"UPLOAD ONLY: {result.output / 'UPLOAD_reports.zip'}")
    print(f"KEEP PRIVATE: {result.output / 'glossary.json'}")
    print(f"GUIDE: {result.output / 'HUONG_DAN.txt'}")
    return 0
