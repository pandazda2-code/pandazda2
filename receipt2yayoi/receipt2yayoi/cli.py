"""コマンドラインインターフェース。

  receipt2yayoi photos/ -o out/
  receipt2yayoi photos/ --dry-run        # APIを叩かずキャッシュ済みだけ処理
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from receipt2yayoi.extract import extract_receipt, iter_images
from receipt2yayoi.models import Receipt, ReceiptLine
from receipt2yayoi.yayoi import (
    build_journals,
    total_amount,
    write_review_csv,
    write_yayoi_csv,
)

CACHE_NAME = ".receipt2yayoi-cache.json"


def _serialize(receipt: Receipt) -> dict:
    data = asdict(receipt)
    data["issue_date"] = receipt.issue_date.isoformat() if receipt.issue_date else None
    data["total"] = str(receipt.total)
    for line in data["lines"]:
        line["amount"] = str(line["amount"])
    return data


def _deserialize(data: dict) -> Receipt:
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
        warnings=data.get("warnings", []),
    )


def _load_cache(path: Path) -> dict[str, dict]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_cache(path: Path, cache: dict[str, dict]) -> None:
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="receipt2yayoi",
        description="レシート写真を弥生会計の仕訳インポートCSVに変換します。",
    )
    parser.add_argument("target", type=Path, help="レシート画像ファイル、またはそれが入ったフォルダ")
    parser.add_argument(
        "-o", "--out", type=Path, default=Path("out"), help="出力先フォルダ（既定: out）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="APIを呼ばず、キャッシュ済みの読み取り結果だけでCSVを作る",
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="キャッシュを使わず毎回読み取り直す"
    )
    args = parser.parse_args(argv)

    if not args.target.exists():
        print(f"見つかりません: {args.target}", file=sys.stderr)
        return 1

    images = iter_images(args.target)
    if not images:
        print("対象の画像がありません。", file=sys.stderr)
        return 1

    cache_path = args.out / CACHE_NAME
    args.out.mkdir(parents=True, exist_ok=True)
    cache = {} if args.no_cache else _load_cache(cache_path)

    receipts: list[Receipt] = []
    for image in images:
        key = str(image)
        if key in cache:
            receipts.append(_deserialize(cache[key]))
            print(f"  (キャッシュ) {image.name}")
            continue
        if args.dry_run:
            print(f"  (スキップ) {image.name}")
            continue
        print(f"  読み取り中… {image.name}")
        try:
            receipt = extract_receipt(image)
        except Exception as exc:  # 1枚失敗しても残りは処理する
            print(f"  ✗ {image.name}: {exc}", file=sys.stderr)
            continue
        receipts.append(receipt)
        cache[key] = _serialize(receipt)
        _save_cache(cache_path, cache)

    if not receipts:
        print("処理できたレシートがありません。", file=sys.stderr)
        return 1

    journals = [j for r in receipts for j in build_journals(r)]
    yayoi_path = write_yayoi_csv(journals, args.out / "yayoi_import.csv")
    review_path = write_review_csv(journals, args.out / "review.csv")

    review_count = sum(1 for j in journals if j.needs_review)
    print()
    print(f"レシート {len(receipts)}枚 → 仕訳 {len(journals)}行 / 合計 {int(total_amount(journals)):,}円")
    print(f"  弥生インポート用: {yayoi_path}")
    print(f"  確認用一覧      : {review_path}")
    if review_count:
        print(f"  ⚠ 要確認 {review_count}行。review.csv を直してから取り込んでください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
