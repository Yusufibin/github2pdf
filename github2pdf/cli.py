import argparse
import re
import sys
from pathlib import Path

from . import __version__
from .models import ConversionError, Options
from .render import write_pdf
from .source import load_source


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if result < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Turn a GitHub repository or local folder into a source-code PDF."
    )
    parser.add_argument("source", help="GitHub URL, owner/repo, or local folder")
    parser.add_argument("--version", action="version", version=f"github2pdf {__version__}")
    parser.add_argument(
        "--ref",
        "--branch-or-tag",
        "--branch_or_tag",
        dest="ref",
        help="Branch, tag or commit (default: repository default branch)",
    )
    parser.add_argument("-o", "--output", type=Path, help="Output PDF path")
    parser.add_argument("--page-size", "--page_size", choices=["A4", "letter"], default="A4")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="GLOB",
        help="Include matching paths or filenames; repeatable",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        nargs="+",
        default=[],
        metavar="GLOB",
        help="Exclude matching paths or filenames; repeatable",
    )
    parser.add_argument("--lang", help="Only one file extension, e.g. py or rs")
    parser.add_argument("--min-lines", "--min_lines", type=positive_int, default=1)
    parser.add_argument("--max-files", type=positive_int, default=500)
    parser.add_argument("--max-file-bytes", type=positive_int, default=256_000)
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="List every skipped file and its reason"
    )
    args = parser.parse_args(argv)
    try:
        options = Options(
            include=tuple(args.include),
            exclude=tuple(p for group in args.exclude for p in group),
            language=args.lang,
            min_lines=args.min_lines,
            max_files=args.max_files,
            max_file_bytes=args.max_file_bytes,
        )
        document = load_source(args.source, args.ref, options)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", document.title).strip(".-") or "source"
        output = args.output or Path(f"{slug}-source.pdf")
        write_pdf(document, output, args.page_size)
    except ConversionError as error:
        print(f"github2pdf: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("github2pdf: cancelled.", file=sys.stderr)
        return 130
    print(
        f"Created {output} | {len(document.files)} files | {sum(f.lines for f in document.files):,} lines | {len(document.skipped)} skipped"
    )
    if args.verbose:
        for path, reason in document.skipped:
            print(f"  skipped {path}: {reason}")
    return 0
