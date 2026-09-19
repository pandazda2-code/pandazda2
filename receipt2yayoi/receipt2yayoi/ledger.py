"""レシート台帳。

1枚ずつ送られてくる写真をためていく場所。
CSVはこの台帳から毎回まるごと作り直すので、
「追記のつもりが前の分を消してしまった」という事故が起きない。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from receipt2yayoi.models import Receipt, ReceiptLine

DEFAULT_LEDGER = Path("ledger/receipts.json")


def image_id(path: Path) -> str:
    """画像の中身から一意なIDを作る。

    ファイル名ではなく中身で見るので、同じ写真を名前違いで送っても
    二重計上にならない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def serialize(receipt: Receipt) -> dict:
    data = asdict(receipt)
    data["issue_date"] = receipt.issue_date.isoformat() if receipt.issue_date else None
    data["total"] = str(receipt.total)
    for line in data["lines"]:
        line["amount"] = str(line["amount"])
    return data


def deserialize(data: dict) -> Receipt:
    return Receipt(
        source=data["source"],
        issue_date=date.fromisoformat(data["issue_date"]) if data["issue_date"] else None,
        shop=data["shop"],
        total=Decimal(data["total"]),
        lines=[
            ReceiptLine(name=l["name"], amount=Decimal(l["amount"]), tax_rate=l["tax_rate"])
            for l in data["lines"]
        ],
        payment=data["payment"],
        invoice_number=data.get("invoice_number"),
        note=data.get("note", ""),
        warnings=list(data.get("warnings", [])),
    )


class Ledger:
    """レシートをためておく台帳（JSONファイル1つ）。"""

    def __init__(self, path: Path = DEFAULT_LEDGER):
        self.path = path
        self.entries: dict[str, dict] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.entries = raw.get("receipts", {})

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def __len__(self) -> int:
        return len(self.entries)

    def add(self, key: str, receipt: Receipt) -> None:
        self.entries[key] = {
            **serialize(receipt),
            "imported_at": datetime.now().isoformat(timespec="seconds"),
        }

    def receipts(self, year: int | None = None) -> list[Receipt]:
        """取引日順のレシート一覧。日付不明のものは先頭に出して目立たせる。"""
        items = [deserialize(entry) for entry in self.entries.values()]
        if year is not None:
            items = [
                r for r in items if r.issue_date is None or r.issue_date.year == year
            ]
        return sorted(items, key=lambda r: (r.issue_date is not None, r.issue_date or date.min))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "receipts": self.entries}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
