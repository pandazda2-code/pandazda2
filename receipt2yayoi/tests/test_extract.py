from pathlib import Path

import pytest

from receipt2yayoi.extract import SUPPORTED_SUFFIXES, encode_document, iter_images


def test_pdf_is_sent_as_a_document_not_an_image(tmp_path: Path):
    """Web発行の領収書はPDFで来る。画像ブロックに入れるとAPIが受け付けない。"""
    pdf = tmp_path / "receipt.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    block = encode_document(pdf)
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"


def test_jpeg_is_sent_as_an_image(tmp_path: Path):
    jpg = tmp_path / "receipt.jpg"
    jpg.write_bytes(b"\xff\xd8fake")
    block = encode_document(jpg)
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/jpeg"


def test_pdf_is_picked_up_when_scanning_a_folder(tmp_path: Path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    (tmp_path / "b.jpg").write_bytes(b"\xff\xd8")
    (tmp_path / "memo.txt").write_text("関係ないファイル")

    found = {p.name for p in iter_images(tmp_path)}
    assert found == {"a.pdf", "b.jpg"}


@pytest.mark.parametrize("suffix", [".pdf", ".jpg", ".heic", ".png"])
def test_supported_suffixes(suffix: str):
    assert suffix in SUPPORTED_SUFFIXES
