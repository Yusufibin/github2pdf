import io
import stat
import zipfile

import pytest
import requests

from github2pdf.models import ConversionError, Document, Options
from github2pdf.source import load_source, parse_repository, read_archive, read_github, read_local


def archive(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        for path, content in entries.items():
            zipped.writestr(path, content)
    stream.seek(0)
    return stream


def test_local_keeps_tests_and_docs_but_excludes_secrets_generated_and_binary(tmp_path):
    for path, content in {
        "src/main.py": b"print('Bonjour')\n",
        "README.md": "# Café\n".encode(),
        "tests/test_main.py": b"assert True\n",
        ".env": b"SECRET=not-for-export",
        "credential.key": b"private",
        "image.data": b"\x00binary",
        "node_modules/a.js": b"ignored",
        "Cargo.lock": b"generated",
    }.items():
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    (tmp_path / "outside-link.py").symlink_to(tmp_path / "src/main.py")
    document = read_local(tmp_path, Options())
    assert [f.path for f in document.files] == ["README.md", "src/main.py", "tests/test_main.py"]
    assert "Café" in document.files[0].content
    assert "Local folder" == document.origin
    reasons = dict(document.skipped)
    assert reasons[".env"] == "sensitive filename"
    assert reasons["outside-link.py"] == "symlink or special file"
    assert reasons["image.data"] == "binary content"


def test_filters_and_limits_are_reported_without_truncation(tmp_path):
    for name, content in [
        ("a.py", "first\nlast\n"),
        ("b.py", "x" * 100),
        ("c.py", "later\n"),
        ("d.md", "# Docs"),
    ]:
        (tmp_path / name).write_text(content)
    document = read_local(
        tmp_path, Options(include=("*.py",), exclude=("c.py",), max_file_bytes=30)
    )
    assert [f.path for f in document.files] == ["a.py"]
    assert document.files[0].content.endswith("last\n")
    assert dict(document.skipped)["b.py"] == "file size limit"
    assert dict(document.skipped)["c.py"] == "exclude filter"
    assert dict(document.skipped)["d.md"] == "include filter"
    assert len(read_local(tmp_path, Options(max_files=1)).files) == 1
    assert len(read_local(tmp_path, Options(max_total_bytes=12)).files) == 1


def test_archive_filters_and_rejects_traversal_and_symlinks():
    data = archive(
        {"root/src/a.py": "print('ok')", "root/.env": "SECRET=hidden", "root/a.bin": b"\x00"}
    )
    document = read_archive(data, Document("repo", "GitHub", "main"), Options())
    assert [f.path for f in document.files] == ["src/a.py"]
    for unsafe in ["root/../../escape.py", "/absolute.py", "root/dir\\escape.py"]:
        with pytest.raises(ConversionError, match="unsafe"):
            read_archive(archive({unsafe: "bad"}), Document("repo", "GitHub", "main"), Options())
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zipped:
        info = zipfile.ZipInfo("root/link.py")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(info, "../secret")
    data.seek(0)
    assert read_archive(data, Document("r", "g", "m"), Options()).skipped == [
        ("link.py", "symlink")
    ]


@pytest.mark.parametrize(
    "source",
    [
        "http://github.com/a/b",
        "https://evil.example/a/b",
        "https://github.com/a/b/tree/main",
        "https://github.com/a/b?token=secret",
        "https://user:secret@github.com/a/b",
    ],
)
def test_rejects_unsupported_repository_urls(source):
    with pytest.raises(ConversionError):
        parse_repository(source)


def response(content, status=200):
    import json

    result = requests.Response()
    result.status_code = status
    result._content = content if isinstance(content, bytes) else json.dumps(content).encode()
    result._content_consumed = True
    return result


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.headers = {}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def test_github_resolves_default_branch_and_pins_archive_to_commit(monkeypatch):
    sha = "a" * 40
    fake = FakeSession(
        [
            response({"default_branch": "trunk"}),
            response({"sha": sha}),
            response(archive({"root/a.py": "print('ok')"}).getvalue()),
        ]
    )
    monkeypatch.setattr(requests, "Session", lambda: fake)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-never-rendered")
    document = read_github("owner/repo", None, Options())
    assert document.ref == "trunk" and document.revision == sha
    assert fake.calls[1][0].endswith("/commits/trunk")
    assert fake.calls[2][0].endswith("/zipball/" + sha)
    assert all(call[1]["timeout"] == (10, 60) for call in fake.calls)
    assert "test-token" not in str(document)


def test_github_escapes_refs_and_enforces_download_limit(monkeypatch):
    fake = FakeSession([response({}), response({"sha": "a" * 40}), response(b"a" * 20)])
    monkeypatch.setattr(requests, "Session", lambda: fake)
    with pytest.raises(ConversionError, match="download limit"):
        read_github("owner/repo", "feature/one", Options(max_download_bytes=10))
    assert fake.calls[1][0].endswith("/commits/feature%2Fone")


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_github_http_errors_are_actionable(monkeypatch, status):
    fake = FakeSession([response({}, status)])
    monkeypatch.setattr(requests, "Session", lambda: fake)
    with pytest.raises(ConversionError):
        read_github("owner/repo", None, Options())


def test_invalid_archive_empty_repository_and_local_ref(tmp_path, monkeypatch):
    with pytest.raises(ConversionError, match="invalid or unreadable"):
        read_archive(io.BytesIO(b"bad"), Document("r", "g", "m"), Options())
    fake = FakeSession([response({"default_branch": None})])
    monkeypatch.setattr(requests, "Session", lambda: fake)
    with pytest.raises(ConversionError, match="empty"):
        read_github("owner/repo", None, Options())
    with pytest.raises(ConversionError, match="local folders"):
        load_source(str(tmp_path), "main")


def test_network_timeout_and_invalid_json_have_clean_errors(monkeypatch):
    class TimeoutSession(FakeSession):
        def get(self, *args, **kwargs):
            raise requests.Timeout("internal transport details")

    monkeypatch.setattr(requests, "Session", lambda: TimeoutSession([]))
    with pytest.raises(ConversionError, match="Unable to reach GitHub"):
        read_github("owner/repo", None, Options())
    monkeypatch.setattr(requests, "Session", lambda: FakeSession([response(b"not JSON")]))
    with pytest.raises(ConversionError, match="invalid JSON"):
        read_github("owner/repo", None, Options())


def test_bom_encodings_and_unsupported_bytes_are_handled(tmp_path):
    (tmp_path / "utf16.txt").write_bytes("Données\r\nFin".encode("utf-16"))
    (tmp_path / "utf8.txt").write_bytes("Café".encode("utf-8-sig"))
    (tmp_path / "invalid.txt").write_bytes(b"\xffinvalid")
    document = read_local(tmp_path, Options())
    assert [f.content for f in document.files] == ["Données\nFin", "Café"]
    assert "unsupported encoding" in dict(document.skipped)["invalid.txt"]
