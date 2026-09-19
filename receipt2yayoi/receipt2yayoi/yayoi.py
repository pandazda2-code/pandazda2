"""Receipt → 仕訳 → 弥生インポートCSV。"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from receipt2yayoi import rules
from receipt2yayoi.models import Journal, Receipt

# 弥生会計「仕訳日記帳」インポート形式の25項目。
# 先頭の識別フラグは 2000 = 仕訳データ。
YAYOI_COLUMNS = 25
YAYOI_ENCODING = "cp932"  # 弥生は Shift_JIS(CP932)


def build_journals(receipt: Receipt) -> list[Journal]:
    """レシート1枚から仕訳（税率ごとに1行）を組み立てる。"""
    item_names = [line.name for line in receipt.lines]
    account, needs_review = rules.guess_account(receipt.shop, item_names)
    credit_account = rules.guess_payment_account(receipt.payment)

    if receipt.issue_date is None or receipt.total <= 0:
        needs_review = True
    if receipt.warnings:
        needs_review = True

    journals: list[Journal] = []
    for rate, amount in sorted(receipt.subtotal_by_rate.items(), reverse=True):
        if amount <= 0:
            continue
        summary = receipt.shop or "（店名不明）"
        if len(receipt.subtotal_by_rate) > 1:
            summary = f"{summary} ({rate}%)"
        journals.append(
            Journal(
                entry_date=receipt.issue_date,
                debit_account=account,
                debit_tax=rules.tax_category(rate, receipt.invoice_number),
                credit_account=credit_account,
                amount=amount,
                tax_amount=rules.tax_amount(amount, rate),
                summary=summary,
                memo=_memo(receipt),
                needs_review=needs_review,
                source=receipt.source,
            )
        )
    return journals


def _memo(receipt: Receipt) -> str:
    parts = [Path(receipt.source).name]
    if receipt.invoice_number:
        parts.append(receipt.invoice_number)
    else:
        parts.append("インボイス番号なし")
    return " / ".join(parts)


def _row(journal: Journal) -> list[str]:
    """弥生の仕訳インポート1行（25列）に変換する。"""
    date_str = journal.entry_date.strftime("%Y/%m/%d") if journal.entry_date else ""
    amount = str(int(journal.amount))
    return [
        "2000",                    # 1  識別フラグ
        "",                        # 2  伝票No（弥生に採番させる）
        "",                        # 3  決算
        date_str,                  # 4  取引日付
        journal.debit_account,     # 5  借方勘定科目
        journal.debit_sub,         # 6  借方補助科目
        "",                        # 7  借方部門
        journal.debit_tax,         # 8  借方税区分
        amount,                    # 9  借方金額
        str(int(journal.tax_amount)),  # 10 借方税金額
        journal.credit_account,    # 11 貸方勘定科目
        journal.credit_sub,        # 12 貸方補助科目
        "",                        # 13 貸方部門
        journal.credit_tax,        # 14 貸方税区分
        amount,                    # 15 貸方金額
        "0",                       # 16 貸方税金額
        journal.summary,           # 17 摘要
        "",                        # 18 番号
        "",                        # 19 期日
        "3",                       # 20 タイプ
        "",                        # 21 生成元
        journal.memo,              # 22 仕訳メモ
        "0" if not journal.needs_review else "1",  # 23 付箋1（要確認に色を付ける）
        "0",                       # 24 付箋2
        "no",                      # 25 調整
    ]


def write_yayoi_csv(journals: list[Journal], out_path: Path) -> Path:
    """弥生会計の仕訳インポート用CSVを書き出す（Shift_JIS）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding=YAYOI_ENCODING, newline="", errors="replace") as f:
        writer = csv.writer(f, lineterminator="\r\n")
        for journal in journals:
            row = _row(journal)
            assert len(row) == YAYOI_COLUMNS
            writer.writerow(row)
    return out_path


REVIEW_HEADER = [
    "要確認",
    "日付",
    "借方勘定科目",
    "税区分",
    "金額",
    "うち消費税",
    "貸方勘定科目",
    "摘要",
    "元画像",
    "備考",
]


def write_review_csv(journals: list[Journal], out_path: Path) -> Path:
    """人間が目でチェックするための一覧（Excelで開けるUTF-8 BOM）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(REVIEW_HEADER)
        for j in journals:
            writer.writerow([
                "要確認" if j.needs_review else "",
                j.entry_date.strftime("%Y/%m/%d") if j.entry_date else "",
                j.debit_account,
                j.debit_tax,
                str(int(j.amount)),
                str(int(j.tax_amount)),
                j.credit_account,
                j.summary,
                j.source,
                j.memo,
            ])
    return out_path


def total_amount(journals: list[Journal]) -> Decimal:
    return sum((j.amount for j in journals), Decimal(0))
