from datetime import date
from decimal import Decimal
from pathlib import Path

from receipt2yayoi.ledger import Ledger, image_id
from receipt2yayoi.models import Receipt, ReceiptLine


def make_receipt(day: int = 1, shop: str = "ファミリーマート") -> Receipt:
    return Receipt(
        source=f"photos/r{day}.jpg",
        issue_date=date(2026, 3, day),
        shop=shop,
        total=Decimal("918"),
        lines=[ReceiptLine("コピー用紙", Decimal("918"), 10)],
        payment="現金",
        invoice_number="T1234567890123",
    )


def test_roundtrip_preserves_values(tmp_path: Path):
    path = tmp_path / "ledger.json"
    ledger = Ledger(path)
    ledger.add("abc", make_receipt())
    ledger.save()

    reloaded = Ledger(path).receipts()
    assert len(reloaded) == 1
    assert reloaded[0].total == Decimal("918")
    assert reloaded[0].issue_date == date(2026, 3, 1)
    assert reloaded[0].lines[0].amount == Decimal("918")


def test_same_photo_gets_same_id(tmp_path: Path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "別名.jpg"
    a.write_bytes(b"\xff\xd8fake-jpeg")
    b.write_bytes(b"\xff\xd8fake-jpeg")
    assert image_id(a) == image_id(b)


def test_different_photos_get_different_ids(tmp_path: Path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    assert image_id(a) != image_id(b)


def test_receipts_are_sorted_by_date_with_unknown_first(tmp_path: Path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.add("k2", make_receipt(day=5, shop="B"))
    ledger.add("k1", make_receipt(day=2, shop="A"))
    undated = make_receipt(shop="C")
    undated.issue_date = None
    ledger.add("k3", undated)

    assert [r.shop for r in ledger.receipts()] == ["C", "A", "B"]


def test_year_filter_keeps_undated_receipts(tmp_path: Path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.add("k1", make_receipt(day=2, shop="今年"))
    old = make_receipt(shop="去年")
    old.issue_date = date(2025, 12, 31)
    ledger.add("k2", old)
    undated = make_receipt(shop="不明")
    undated.issue_date = None
    ledger.add("k3", undated)

    shops = {r.shop for r in ledger.receipts(year=2026)}
    assert shops == {"今年", "不明"}  # 日付不明は取りこぼさず人間に見せる


def test_remove_returns_what_it_deleted(tmp_path: Path):
    ledger = Ledger(tmp_path / "l.json")
    ledger.add("k1", make_receipt(shop="JR東海"))
    removed = ledger.remove("k1")
    assert removed is not None and removed.shop == "JR東海"
    assert len(ledger) == 0


def test_remove_missing_key_is_harmless(tmp_path: Path):
    ledger = Ledger(tmp_path / "l.json")
    assert ledger.remove("ない") is None


def test_find_matches_how_people_actually_refer_to_a_receipt(tmp_path: Path):
    ledger = Ledger(tmp_path / "l.json")
    ledger.add("k1", make_receipt(day=19, shop="JR東海 EX予約 豊橋→品川"))
    ledger.add("k2", make_receipt(day=3, shop="ヨドバシカメラ"))

    assert [r.shop for _, r in ledger.find("JR")] == ["JR東海 EX予約 豊橋→品川"]
    assert [r.shop for _, r in ledger.find("2026-03-19")] == ["JR東海 EX予約 豊橋→品川"]
    assert len(ledger.find("918")) == 2  # 金額が同じなら両方あたる
    assert ledger.find("存在しない") == []
