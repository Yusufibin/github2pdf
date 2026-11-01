from pathlib import Path

import pytest
from pypdf import PdfReader

from github2pdf.cli import main
from github2pdf.models import ConversionError, Document, SourceFile
from github2pdf.render import write_pdf


@pytest.mark.parametrize("page_size", ["A4", "letter"])
def test_pdf_preserves_long_code_unicode_and_navigation(tmp_path, page_size):
    document = Document(
        "Café & project",
        "Local folder",
        "working tree",
        files=[
            SourceFile(
                "src/a&b.py",
                "# Café <hello>\n" + "x" * 400 + " IMPORTANT_END\n" + "print('page')\n" * 130,
            ),
            SourceFile("README.md", "# Résumé\nThe end.\n"),
        ],
        skipped=[(".env", "sensitive filename")],
    )
    output = write_pdf(document, tmp_path / "source.pdf", page_size)
    reader = PdfReader(output)
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert len(reader.pages) >= 6
    assert "Café" in text and "Résumé" in text
    assert "IMPORTANT_END" in text.replace("\n", "")
    assert "The end." in text
    assert len(reader.outline) == 2
    assert len(reader.pages[1].get("/Annots", [])) >= 2
    assert reader.get_destination_page_number(reader.outline[0]) == 2
    assert "sensitive filename" in text
    expected_width = 595.2756 if page_size == "A4" else 612
    assert float(reader.pages[0].mediabox.width) == pytest.approx(expected_width, abs=0.1)


def test_empty_export_preserves_existing_output(tmp_path):
    output = tmp_path / "source.pdf"
    output.write_bytes(b"existing document")
    with pytest.raises(ConversionError, match="No readable"):
        write_pdf(Document("empty", "local", "working tree"), output)
    assert output.read_bytes() == b"existing document"


def test_render_failure_is_atomic_and_cleans_up(tmp_path, monkeypatch):
    output = tmp_path / "source.pdf"
    output.write_bytes(b"existing")

    def fail(*args):
        raise ValueError("simulated failure")

    monkeypatch.setattr("github2pdf.render._build", fail)
    with pytest.raises(ConversionError, match="preserved"):
        write_pdf(Document("demo", "local", "work", files=[SourceFile("a.py", "ok")]), output)
    assert output.read_bytes() == b"existing"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["source.pdf"]


def test_cli_local_export_legacy_options_and_clean_errors(tmp_path, capsys):
    source = tmp_path / "project"
    source.mkdir()
    (source / "main.py").write_text("print('hello')\n")
    output = tmp_path / "out.pdf"
    assert (
        main([str(source), "--page_size", "letter", "--min_lines", "1", "--output", str(output)])
        == 0
    )
    assert output.exists()
    assert "1 files" in capsys.readouterr().out
    assert main(["https://another-site.example/repo"]) == 1
    error = capsys.readouterr().err
    assert "github2pdf:" in error and "Traceback" not in error
    with pytest.raises(SystemExit) as caught:
        main([str(source), "--max-files", "0"])
    assert caught.value.code == 2


def test_compatibility_launcher_and_installed_entrypoint(tmp_path):
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "github2pdf.py"), "--version"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "0.2.0" in result.stdout
