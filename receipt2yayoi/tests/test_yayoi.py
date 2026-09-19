import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from receipt2yayoi.models import Receipt, ReceiptLine
from receipt2yayoi.yayoi import (
    YAYOI_COLUMNS,
    build_journals,
    write_review_csv,
    write_yayoi_csv,
)


def make_receipt(**kwargs) -> Receipt:
    base = dict(
        source="photos/r1.jpg",
        issue_date=date(2026, 3, 1),
        shop="セブンイレブン東京駅店",
        total=Decimal("1080"),
        lines=[ReceiptLine("コピー用紙", Decimal("550"), 10),
               ReceiptLine("お茶", Decimal("530"), 8)],
        payment="現金",
        invoice_number="T1234567890123",
    )
    base.update(kwargs)
    return Receipt(**base)


def test_splits_by_tax_rate():
    journals = build_journals(make_receipt())
    assert [j.debit_tax for j in journals] == ["課対仕入10%", "課対仕入8%"]
    assert [int(j.amount) for j in journals] == [550, 530]
    # 税込550円の10%消費税は50円（切り捨て）
    assert int(journals[0].tax_amount) == 50
    assert int(journals[1].tax_amount) == 39


def test_no_invoice_number_uses_transitional_category():
    journals = build_journals(make_receipt(invoice_number=None))
    assert journals[0].debit_tax == "課対仕入10%区分80"


def test_credit_account_follows_payment_method():
    journals = build_journals(make_receipt(payment="クレジットカード"))
    assert journals[0].credit_account == "未払金"


def test_unknown_shop_is_flagged_for_review():
    journals = build_journals(
        make_receipt(shop="よくわからない店", lines=[], total=Decimal("3000"))
    )
    assert journals[0].debit_account == "雑費"
    assert journals[0].needs_review


def test_missing_date_is_flagged():
    journals = build_journals(make_receipt(issue_date=None, lines=[]))
    assert journals[0].needs_review
    assert journals[0].entry_date is None


def test_yayoi_csv_shape(tmp_path: Path):
    journals = build_journals(make_receipt())
    out = write_yayoi_csv(journals, tmp_path / "yayoi_import.csv")
    with out.open(encoding="cp932", newline="") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2
    for row in rows:
        assert len(row) == YAYOI_COLUMNS
        assert row[0] == "2000"
        assert row[3] == "2026/03/01"
        assert row[8] == row[14]  # 借方金額と貸方金額は一致する


def test_review_csv_is_excel_readable(tmp_path: Path):
    journals = build_journals(make_receipt())
    out = write_review_csv(journals, tmp_path / "review.csv")
    text = out.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("要確認,")
    assert "セブンイレブン東京駅店" in text


def test_receipt_without_lines_falls_back_to_total():
    journals = build_journals(make_receipt(lines=[], total=Decimal("2200")))
    assert len(journals) == 1
    assert int(journals[0].amount) == 2200
    assert int(journals[0].tax_amount) == 200
