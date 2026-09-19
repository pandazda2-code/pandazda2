"""レシートと仕訳のデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class ReceiptLine:
    """レシートの明細1行。"""

    name: str
    amount: Decimal
    tax_rate: int = 10  # 10 or 8（軽減税率）


@dataclass
class Receipt:
    """1枚のレシートから読み取った内容。"""

    source: str  # 元画像のパス
    issue_date: date | None
    shop: str
    total: Decimal
    lines: list[ReceiptLine] = field(default_factory=list)
    payment: str = "現金"  # 現金 / クレジットカード / 電子マネー など
    invoice_number: str | None = None  # インボイス登録番号（T+13桁）
    note: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def subtotal_by_rate(self) -> dict[int, Decimal]:
        """税率ごとの税込合計。明細がなければ全額を10%として扱う。"""
        if not self.lines:
            return {10: self.total}
        totals: dict[int, Decimal] = {}
        for line in self.lines:
            totals[line.tax_rate] = totals.get(line.tax_rate, Decimal(0)) + line.amount
        return totals


@dataclass
class Journal:
    """弥生にインポートする仕訳1行（借方＝費用、貸方＝支払手段）。"""

    entry_date: date
    debit_account: str
    debit_sub: str = ""
    debit_tax: str = "課対仕入10%"
    credit_account: str = "現金"
    credit_sub: str = ""
    credit_tax: str = "対象外"
    amount: Decimal = Decimal(0)
    tax_amount: Decimal = Decimal(0)
    summary: str = ""
    memo: str = ""
    needs_review: bool = False
    source: str = ""
