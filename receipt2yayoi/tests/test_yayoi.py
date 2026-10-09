import pytest

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
    assert [j.debit_tax for j in journals] == ["課対仕入内10%", "課対仕入内軽減8%"]
    assert [int(j.amount) for j in journals] == [550, 530]
    # 税込550円の10%消費税は50円（切り捨て）
    assert int(journals[0].tax_amount) == 50
    assert int(journals[1].tax_amount) == 39


def test_no_invoice_number_uses_transitional_category():
    """インボイス番号がないと控除率が下がる。率は取引日で変わる。"""
    before = build_journals(
        make_receipt(invoice_number=None, issue_date=date(2026, 9, 30))
    )
    assert before[0].debit_tax == "課対仕入内10%区80%"
    assert before[1].debit_tax == "課対仕入内軽減8%区80%"

    after = build_journals(
        make_receipt(invoice_number=None, issue_date=date(2026, 10, 1))
    )
    assert after[0].debit_tax == "課対仕入内10%区70%"
    assert after[1].debit_tax == "課対仕入内軽減8%区70%"


def test_invoice_number_keeps_full_deduction_on_either_side_of_the_boundary():
    for day in (date(2026, 9, 30), date(2026, 10, 1)):
        journals = build_journals(make_receipt(issue_date=day))
        assert journals[0].debit_tax == "課対仕入内10%"


@pytest.mark.parametrize("payment", ["現金", "クレジットカード", "電子マネー", "不明"])
def test_personal_payments_go_to_owners_account(payment: str):
    """個人のカード・現金で立て替えているので、貸方は事業主借。"""
    journals = build_journals(make_receipt(payment=payment))
    assert journals[0].credit_account == "事業主借"


@pytest.mark.parametrize(
    "payment,expected", [("事業用口座", "普通預金"), ("事業用カード", "未払金"), ("口座振替", "普通預金")]
)
def test_business_payments_are_not_treated_as_personal(payment: str, expected: str):
    journals = build_journals(make_receipt(payment=payment))
    assert journals[0].credit_account == expected


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
        assert row[19] == "0"  # タイプ
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


@pytest.mark.parametrize(
    "shop",
    [
        "東海旅客鉄道（スマートEX）豊橋→品川 こだま818号",  # 領収書の発行者名
        "JR東海 スマートEX 東京→豊橋（自由席）",
        "EXご利用票 品川→名古屋",
        "新幹線 のぞみ 東京→新大阪",
    ],
)
def test_shinkansen_is_travel_expense(shop: str):
    """新幹線の証憑は書き方がばらつく。どれでも旅費交通費に落とす。"""
    journals = build_journals(make_receipt(shop=shop, lines=[], total=Decimal("8570")))
    assert journals[0].debit_account == "旅費交通費"
    assert not journals[0].needs_review


def test_long_summary_is_trimmed_to_what_yayoi_shows():
    """摘要が長すぎると弥生で切れる。切れたと分かるようにする。"""
    shop = "東海旅客鉄道株式会社 スマートEX 東京→豊橋 こだま999号 自由席 往路分"
    journals = build_journals(make_receipt(shop=shop, lines=[], total=Decimal("8570")))
    assert len(journals[0].summary) <= 32
    assert journals[0].summary.endswith("…")


def test_tax_amount_matches_the_worked_example():
    """8,570円・10% → 779円（切り捨て）。"""
    journals = build_journals(make_receipt(lines=[], total=Decimal("8570")))
    assert int(journals[0].tax_amount) == 779
