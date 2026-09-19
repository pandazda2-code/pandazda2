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


def run_for(person: str, *args: str) -> int:
    """人を指定してCLIを叩く。--person は必須なので毎回付ける。"""
    return cli.main([*args, "--person", person])


def test_add_writes_ledger_and_csv(tmp_path: Path, photo: Path, fake_extract):
    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"

    assert run(["add", str(photo), "--ledger", str(ledger_path), "-o", str(out), "--person", "英之"]) == 0

    assert len(Ledger(ledger_path)) == 1
    with (out / "yayoi_import.csv").open(encoding="cp932", newline="") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 1
    assert rows[0][3] == "2026/03/01"


def test_same_photo_is_not_counted_twice(tmp_path: Path, photo: Path, fake_extract):
    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    args = ["add", str(photo), "--ledger", str(ledger_path), "-o", str(out), "--person", "英之"]

    assert run(args) == 0
    assert run(args) == 0  # 同じ写真をもう一度送っても増えない

    assert len(Ledger(ledger_path)) == 1
    assert len(fake_extract) == 1  # 2回目はAPIを呼ばない＝費用もかからない


def test_second_photo_is_appended_not_replaced(tmp_path: Path, photo: Path, fake_extract):
    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    other = tmp_path / "IMG_0002.jpg"
    other.write_bytes(b"\xff\xd8fake-jpeg-2")

    run(["add", str(photo), "--ledger", str(ledger_path), "-o", str(out), "--person", "英之"])
    run(["add", str(other), "--ledger", str(ledger_path), "-o", str(out), "--person", "英之"])

    assert len(Ledger(ledger_path)) == 2
    with (out / "yayoi_import.csv").open(encoding="cp932", newline="") as f:
        assert len(list(csv.reader(f))) == 2  # 1枚目も残っている


def test_build_regenerates_csv_from_ledger(tmp_path: Path, photo: Path, fake_extract):
    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    run(["add", str(photo), "--ledger", str(ledger_path), "-o", str(out), "--person", "英之"])

    (out / "yayoi_import.csv").unlink()
    assert run(["build", "--ledger", str(ledger_path), "-o", str(out), "--person", "英之"]) == 0
    assert (out / "yayoi_import.csv").exists()


def test_year_option_names_the_files(tmp_path: Path, photo: Path, fake_extract):
    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    run(["add", str(photo), "--ledger", str(ledger_path), "-o", str(out), "--year", "2026", "--person", "英之"])
    assert (out / "yayoi_import_2026.csv").exists()


def test_build_on_empty_ledger_fails_clearly(tmp_path: Path):
    assert run(["build", "--ledger", str(tmp_path / "none.json"), "-o", str(tmp_path), "--person", "英之"]) == 1


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
    assert run(["record", "--image", str(photo), "--ledger", str(ledger_path), "-o", str(out), "--person", "英之"]) == 0

    receipts = Ledger(ledger_path).receipts()
    assert len(receipts) == 1
    assert receipts[0].shop == "スターバックス 渋谷店"
    assert receipts[0].total == Decimal("1100")


def test_record_refuses_duplicate_photo(tmp_path, photo, monkeypatch):
    import io

    out = tmp_path / "out"
    ledger_path = tmp_path / "ledger.json"
    args = ["record", "--image", str(photo), "--ledger", str(ledger_path), "-o", str(out), "--person", "英之"]

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
        "--person", "英之",
    ]) == 1


def test_each_person_gets_their_own_ledger_and_csv(tmp_path, photo, fake_extract, monkeypatch):
    """英之と祐子の経費は絶対に混ざってはいけない。"""
    monkeypatch.chdir(tmp_path)

    run_for("英之", "add", str(photo))
    run_for("祐子", "add", str(photo))  # 同じ写真でも別台帳なら別々に入る

    assert len(Ledger(Path("ledger/hideyuki.json"))) == 1
    assert len(Ledger(Path("ledger/yuko.json"))) == 1
    assert (tmp_path / "out/hideyuki/yayoi_import.csv").exists()
    assert (tmp_path / "out/yuko/yayoi_import.csv").exists()


def test_one_persons_receipt_never_appears_in_the_others_csv(
    tmp_path, photo, fake_extract, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    other = tmp_path / "IMG_0002.jpg"
    other.write_bytes(b"\xff\xd8fake-jpeg-2")

    run_for("英之", "add", str(photo))
    run_for("祐子", "add", str(other))

    with Path("out/hideyuki/yayoi_import.csv").open(encoding="cp932", newline="") as f:
        assert len(list(csv.reader(f))) == 1
    with Path("out/yuko/yayoi_import.csv").open(encoding="cp932", newline="") as f:
        assert len(list(csv.reader(f))) == 1


def test_missing_person_is_rejected(tmp_path, photo, fake_extract):
    with pytest.raises(SystemExit) as exc:
        run(["add", str(photo)])  # --person なし
    assert exc.value.code == 2


def test_unknown_person_is_rejected_without_writing_anything(tmp_path, photo, fake_extract):
    assert run(["add", str(photo), "--person", "太郎"]) == 2
    assert not (tmp_path / "ledger").exists()
    assert len(fake_extract) == 0  # 読み取りにも進まない
