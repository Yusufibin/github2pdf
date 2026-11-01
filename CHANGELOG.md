# Changelog

## 0.2.0

- Installable `github2pdf` command and `python -m github2pdf` entry point.
- Local-folder exports and GitHub default-branch detection, pinned to a resolved commit.
- Embedded Noto fonts, cover, clickable contents, bookmarks, syntax highlighting and line numbers.
- Code wrapping and page splitting without silent truncation.
- Explicit glob filters, bounded downloads and reads, skip reporting and atomic output replacement.
- Offline regression tests and CI on Python 3.10 and 3.14.
- Legacy launcher and argument aliases retained. `--exclude` now accepts globs instead of regexes.
- Tests, documentation and small text files are now included by default.
- The former `GithubToPDF` class is replaced by `load_source()` and `write_pdf()`.
