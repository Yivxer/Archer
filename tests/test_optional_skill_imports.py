"""Optional skill backends must not be imported just to register the skill."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_optional_skill_backends_are_not_module_level_imports():
    expectations = {
        "image_ocr.py": "pytesseract",
        "pdf_reader.py": "fitz",
        "rss_reader.py": "feedparser",
    }
    for filename, banned in expectations.items():
        tree = ast.parse((ROOT / "skills" / filename).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            assert banned not in names, filename


def test_optional_skill_run_reports_a_missing_backend_without_hiding_it(monkeypatch, tmp_path):
    import builtins

    from skills import image_ocr, pdf_reader, rss_reader

    image = tmp_path / "page.png"
    image.write_bytes(b"not-a-real-image")
    pdf = tmp_path / "note.pdf"
    pdf.write_bytes(b"%PDF-1.1\n")
    real_import = builtins.__import__

    def blocked(name, globals=None, locals=None, fromlist=(), level=0):
        if name.split(".")[0] in {"pytesseract", "fitz", "feedparser"}:
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert "pytesseract" in image_ocr.run({"path": str(image)})
    assert "pymupdf" in pdf_reader.run({"path": str(pdf)})
    assert "feedparser" in rss_reader.run({"url": "https://example.com/feed.xml"})
