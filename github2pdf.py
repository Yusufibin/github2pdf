#!/usr/bin/env python3
"""Compatibility launcher. Prefer the installed `github2pdf` command."""

from github2pdf.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
