import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from receipt2yayoi import cli
from receipt2yayoi.ledger import Ledger
from receipt2yayoi.models import Receipt


@pytest.fixture
def photo(tmp_path: Path) -> Path:
    p = tmp_path / "IMG_0001.jpg"
    p.write_bytes(b"\xff\xd8fake-jpeg-1")
    return p


@pytest.fixture
def fake_extract(monkeypatch):
    """APIを呼ばずに、写真ごとに決まったレシートを返す。"""
    calls = []

    def _extract(path: Path, client=None) -> Receipt:
        calls.append(path)
        return Receipt(
            source=str(path),
            issue_date=date(2026, 3, 1),
            shop="ファミリーマート",
            total=Decimal("918"),
            lines=[],
            payment="現金",
            invoice_number="T1234567890123",
        )

    monkeypatch.setattr(cli, "extract_receipt", _extract)
    return calls


def run(args: list[str]) -> int:
    return cli.main(args)


def test_add_writes_ledger_and_csv(tmp_path: Path, photo: Path, fake_extract):
    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"

    assert run(["add", str(photo), "--ledger", str(ledger_path), "-o", str(out)]) == 0

    assert len(Ledger(ledger_path)) == 1
    with (out / "yayoi_import.csv").open(encoding="cp932", newline="") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 1
    assert rows[0][3] == "2026/03/01"


def test_same_photo_is_not_counted_twice(tmp_path: Path, photo: Path, fake_extract):
    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    args = ["add", str(photo), "--ledger", str(ledger_path), "-o", str(out)]

    assert run(args) == 0
    assert run(args) == 0  # 同じ写真をもう一度送っても増えない

    assert len(Ledger(ledger_path)) == 1
    assert len(fake_extract) == 1  # 2回目はAPIを呼ばない＝費用もかからない


def test_second_photo_is_appended_not_replaced(tmp_path: Path, photo: Path, fake_extract):
    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    other = tmp_path / "IMG_0002.jpg"
    other.write_bytes(b"\xff\xd8fake-jpeg-2")

    run(["add", str(photo), "--ledger", str(ledger_path), "-o", str(out)])
    run(["add", str(other), "--ledger", str(ledger_path), "-o", str(out)])

    assert len(Ledger(ledger_path)) == 2
    with (out / "yayoi_import.csv").open(encoding="cp932", newline="") as f:
        assert len(list(csv.reader(f))) == 2  # 1枚目も残っている


def test_build_regenerates_csv_from_ledger(tmp_path: Path, photo: Path, fake_extract):
    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    run(["add", str(photo), "--ledger", str(ledger_path), "-o", str(out)])

    (out / "yayoi_import.csv").unlink()
    assert run(["build", "--ledger", str(ledger_path), "-o", str(out)]) == 0
    assert (out / "yayoi_import.csv").exists()


def test_year_option_names_the_files(tmp_path: Path, photo: Path, fake_extract):
    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    run(["add", str(photo), "--ledger", str(ledger_path), "-o", str(out), "--year", "2026"])
    assert (out / "yayoi_import_2026.csv").exists()


def test_build_on_empty_ledger_fails_clearly(tmp_path: Path):
    assert run(["build", "--ledger", str(tmp_path / "none.json"), "-o", str(tmp_path)]) == 1


RECORD_JSON = """{
  "issue_date": "2026-04-05",
  "shop": "スターバックス 渋谷店",
  "total": "1100",
  "payment": "クレジットカード",
  "invoice_number": "T9010001000001",
  "lines": [],
  "warnings": []
}"""


def test_record_appends_without_calling_the_api(tmp_path, photo, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("record は画像をAPIに送ってはいけない")

    monkeypatch.setattr(cli, "extract_receipt", boom)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(RECORD_JSON))

    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    assert run(["record", "--image", str(photo), "--ledger", str(ledger_path), "-o", str(out)]) == 0

    receipts = Ledger(ledger_path).receipts()
    assert len(receipts) == 1
    assert receipts[0].shop == "スターバックス 渋谷店"
    assert receipts[0].total == Decimal("1100")


def test_record_refuses_duplicate_photo(tmp_path, photo, monkeypatch):
    import io

    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    args = ["record", "--image", str(photo), "--ledger", str(ledger_path), "-o", str(out)]

    monkeypatch.setattr("sys.stdin", io.StringIO(RECORD_JSON))
    run(args)
    monkeypatch.setattr("sys.stdin", io.StringIO(RECORD_JSON))
    run(args)

    assert len(Ledger(ledger_path)) == 1


def test_record_rejects_broken_json(tmp_path, photo, monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("{これはJSONではない"))
    assert run([
        "record", "--image", str(photo),
        "--ledger", str(tmp_path / "l.json"), "-o", str(tmp_path / "out"),
    ]) == 1
