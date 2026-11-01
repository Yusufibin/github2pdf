"""Bounded reads from local folders and GitHub archives; archives are never extracted."""

import fnmatch
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse

import requests

from .models import ConversionError, Document, Options, SourceFile

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "target",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".next",
}
BINARY_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".zip",
    ".gz",
    ".tar",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".mp4",
    ".mp3",
    ".exe",
    ".dll",
    ".so",
    ".pyc",
    ".sqlite",
    ".db",
    ".lock",
}
SENSITIVE_NAMES = {".env", ".npmrc", ".pypirc", ".netrc", "credentials", "id_rsa", "id_ed25519"}


def exclusion_reason(path: str, options: Options) -> str | None:
    parts = PurePosixPath(path).parts
    name = parts[-1]
    if any(part in IGNORED_DIRS or part.endswith(".egg-info") for part in parts):
        return "generated directory"
    if (
        name in SENSITIVE_NAMES
        or name.startswith(".env.")
        or Path(name).suffix.lower() in {".pem", ".key", ".p12", ".pfx"}
    ):
        return "sensitive filename"
    if Path(name).suffix.lower() in BINARY_EXTENSIONS or name in {
        "package-lock.json",
        "pnpm-lock.yaml",
    }:
        return "binary or lock file"
    if (
        options.language
        and options.language != "*"
        and Path(name).suffix.lower() != "." + options.language.lower().lstrip(".")
    ):
        return "language filter"
    if options.include and not any(
        fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(name, p) for p in options.include
    ):
        return "include filter"
    if any(fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(name, p) for p in options.exclude):
        return "exclude filter"
    return None


def add_file(document: Document, path: str, data: bytes, options: Options) -> None:
    if b"\x00" in data and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        document.skipped.append((path, "binary content"))
        return
    try:
        content = data.decode(
            "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        )
    except UnicodeError:
        document.skipped.append((path, "unsupported encoding (use UTF-8 or UTF-16)"))
        return
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if any(ord(char) < 32 and char not in "\n\t\f" for char in content):
        document.skipped.append((path, "binary control characters"))
    elif len([line for line in content.splitlines() if line.strip()]) < options.min_lines:
        document.skipped.append((path, "not enough non-empty lines"))
    else:
        document.files.append(SourceFile(path, content))


def _budget_reason(document: Document, size: int, total: int, options: Options) -> str | None:
    if size > options.max_file_bytes:
        return "file size limit"
    if len(document.files) >= options.max_files:
        return "file count limit"
    if total + size > options.max_total_bytes:
        return "total size limit"
    return None


def read_local(root: Path, options: Options) -> Document:
    root = root.resolve()
    if not root.is_dir():
        raise ConversionError("The local source must be an existing directory.")
    document = Document(root.name, "Local folder", "working tree")
    total = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in IGNORED_DIRS
            and not d.endswith(".egg-info")
            and not (Path(directory) / d).is_symlink()
        )
        for name in sorted(names):
            file = Path(directory) / name
            path = file.relative_to(root).as_posix()
            reason = exclusion_reason(path, options)
            try:
                if file.is_symlink() or not file.is_file():
                    reason = "symlink or special file"
                if reason is None:
                    reason = _budget_reason(document, file.stat().st_size, total, options)
                if reason:
                    document.skipped.append((path, reason))
                    continue
                with file.open("rb") as stream:
                    data = stream.read(options.max_file_bytes + 1)
                if len(data) > options.max_file_bytes:
                    document.skipped.append((path, "file size limit"))
                    continue
                total += len(data)
                add_file(document, path, data, options)
            except OSError:
                document.skipped.append((path, "unreadable file"))
    document.files.sort(key=lambda file: file.path)
    return document


def parse_repository(source: str) -> str:
    parsed = urlparse(source if "://" in source else "https://github.com/" + source)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        raise ConversionError(
            "Use https://github.com/owner/repo, owner/repo, or an existing local folder."
        )
    path = parsed.path.strip("/").removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path) or any(
        p in {".", ".."} for p in path.split("/")
    ):
        raise ConversionError("Use the repository root URL; select a branch or tag with --ref.")
    return path


def _get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    try:
        response = session.get(url, timeout=(10, 60), **kwargs)
        response.raise_for_status()
        return response
    except requests.HTTPError as error:
        status = error.response.status_code
        error.response.close()
        if status in (403, 429):
            message = "GitHub refused the request or its rate limit was reached. Set GITHUB_TOKEN if needed."
        elif status == 404:
            message = "Repository or ref not found. For a private repository, check GITHUB_TOKEN permissions."
        else:
            message = f"GitHub returned HTTP {status}. Please retry later."
        raise ConversionError(message) from None
    except requests.RequestException:
        raise ConversionError("Unable to reach GitHub. Check the connection and retry.") from None


def _json(session: requests.Session, url: str) -> dict:
    with _get(session, url) as response:
        try:
            result = response.json()
        except ValueError:
            raise ConversionError("GitHub returned an invalid JSON response.") from None
        if not isinstance(result, dict):
            raise ConversionError("GitHub returned an unexpected response.")
        return result


def read_github(source: str, ref: str | None, options: Options) -> Document:
    repository = parse_repository(source)
    with requests.Session() as session:
        session.headers.update(
            {"Accept": "application/vnd.github+json", "User-Agent": "github2pdf/0.2"}
        )
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            session.headers["Authorization"] = "Bearer " + token
        endpoint = "https://api.github.com/repos/" + repository
        metadata = _json(session, endpoint)
        selected_ref = ref or metadata.get("default_branch")
        if not isinstance(selected_ref, str) or not selected_ref:
            raise ConversionError("This repository has no default branch or is empty.")
        commit = _json(session, endpoint + "/commits/" + quote(selected_ref, safe=""))
        revision = commit.get("sha", "")
        if not isinstance(revision, str) or not re.fullmatch(r"[a-fA-F0-9]{40,64}", revision):
            raise ConversionError("GitHub did not return a valid commit identifier.")
        document = Document(
            repository.split("/")[-1], "https://github.com/" + repository, selected_ref, revision
        )
        with _get(session, endpoint + "/zipball/" + revision, stream=True) as response:
            with tempfile.TemporaryFile() as archive:
                size = 0
                try:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        size += len(chunk)
                        if size > options.max_download_bytes:
                            raise ConversionError(
                                "Repository archive exceeds the download limit (50 MB by default)."
                            )
                        archive.write(chunk)
                except requests.RequestException:
                    raise ConversionError(
                        "The archive download was interrupted. Please retry."
                    ) from None
                archive.seek(0)
                return read_archive(archive, document, options)


def read_archive(archive, document: Document, options: Options) -> Document:
    try:
        with zipfile.ZipFile(archive) as zipped:
            entries = zipped.infolist()
            if len(entries) > 20_000 or sum(entry.file_size for entry in entries) > 250_000_000:
                raise ConversionError("Archive exceeds the entry or uncompressed size limit.")
            total = 0
            for entry in sorted(entries, key=lambda entry: entry.filename):
                parts = PurePosixPath(entry.filename).parts
                if entry.filename.startswith("/") or ".." in parts or "\\" in entry.filename:
                    raise ConversionError("Archive contains an unsafe filename.")
                if entry.is_dir() or len(parts) < 2:
                    continue
                path = "/".join(parts[1:])
                reason = exclusion_reason(path, options)
                if stat.S_ISLNK(entry.external_attr >> 16):
                    reason = "symlink"
                reason = reason or _budget_reason(document, entry.file_size, total, options)
                if reason:
                    document.skipped.append((path, reason))
                    continue
                with zipped.open(entry) as stream:
                    data = stream.read(options.max_file_bytes + 1)
                total += len(data)
                if len(data) > options.max_file_bytes:
                    document.skipped.append((path, "file size limit"))
                    continue
                add_file(document, path, data, options)
        return document
    except (zipfile.BadZipFile, RuntimeError, OSError):
        raise ConversionError("The GitHub archive is invalid or unreadable.") from None


def load_source(source: str, ref: str | None = None, options: Options | None = None) -> Document:
    options = options or Options()
    if Path(source).exists():
        if ref:
            raise ConversionError(
                "--ref applies to GitHub repositories; local folders use their current files."
            )
        return read_local(Path(source), options)
    return read_github(source, ref, options)
