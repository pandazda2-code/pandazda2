"""コマンドラインインターフェース。

写真を台帳に取り込み、台帳まるごとから弥生用CSVを作り直す。

  receipt2yayoi add 写真.jpg              # 1枚追加
  receipt2yayoi add 写真フォルダ/          # まとめて追加
  receipt2yayoi build --year 2026         # CSVだけ作り直す
  receipt2yayoi list                      # 台帳の中身を見る
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from receipt2yayoi.extract import build_receipt, extract_receipt, iter_images
from receipt2yayoi.ledger import DEFAULT_LEDGER, Ledger, image_id
from receipt2yayoi.yayoi import (
    build_journals,
    total_amount,
    write_review_csv,
    write_yayoi_csv,
)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ledger", type=Path, default=DEFAULT_LEDGER, help="台帳ファイル（既定: ledger/receipts.json）"
    )
    parser.add_argument(
        "-o", "--out", type=Path, default=Path("out"), help="CSVの出力先（既定: out）"
    )
    parser.add_argument("--year", type=int, default=None, help="この年の分だけCSVにする")


def cmd_add(args: argparse.Namespace) -> int:
    images: list[Path] = []
    for target in args.targets:
        if not target.exists():
            print(f"見つかりません: {target}", file=sys.stderr)
            return 1
        images.extend(iter_images(target))
    if not images:
        print("対象の画像がありません。", file=sys.stderr)
        return 1

    ledger = Ledger(args.ledger)
    added = skipped = failed = 0

    for image in images:
        key = image_id(image)
        if key in ledger:
            print(f"  ・{image.name} は取り込み済みです（スキップ）")
            skipped += 1
            continue
        print(f"  読み取り中… {image.name}")
        try:
            receipt = extract_receipt(image)
        except Exception as exc:  # 1枚失敗しても残りは続ける
            print(f"  ✗ {image.name}: {exc}", file=sys.stderr)
            failed += 1
            continue
        ledger.add(key, receipt)
        ledger.save()  # 1枚ごとに保存。途中で落ちても読み取り済みの分は残る
        added += 1
        print(f"  ✓ {receipt.issue_date or '日付不明'} {receipt.shop} {int(receipt.total):,}円")

    print(f"\n{added}枚を追加（スキップ {skipped} / 失敗 {failed}）。台帳は合計 {len(ledger)}枚。")
    if added == 0 and skipped == 0:
        return 1
    return _build(ledger, args)


def cmd_record(args: argparse.Namespace) -> int:
    """読み取り済みの内容を台帳に記録する。

    チャットに写真を添付した場合はこちらを使う。画像を見ているのは
    すでにClaudeなので、同じ写真をもう一度APIに送る必要がない。
    """
    if not args.image.exists():
        print(f"見つかりません: {args.image}", file=sys.stderr)
        return 1

    raw = sys.stdin.read() if args.json == "-" else Path(args.json).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"JSONを読めません: {exc}", file=sys.stderr)
        return 1

    ledger = Ledger(args.ledger)
    key = image_id(args.image)
    if key in ledger and not args.force:
        print(f"{args.image.name} は取り込み済みです。上書きするなら --force。")
        return _build(ledger, args)

    receipt = build_receipt(args.image, data)
    ledger.add(key, receipt)
    ledger.save()
    print(f"  ✓ {receipt.issue_date or '日付不明'} {receipt.shop} {int(receipt.total):,}円")
    if receipt.warnings:
        for w in receipt.warnings:
            print(f"    ⚠ {w}")
    print(f"台帳は合計 {len(ledger)}枚。")
    return _build(ledger, args)


def cmd_build(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    if not len(ledger):
        print(f"台帳が空です: {args.ledger}", file=sys.stderr)
        return 1
    return _build(ledger, args)


def _build(ledger: Ledger, args: argparse.Namespace) -> int:
    receipts = ledger.receipts(year=args.year)
    if not receipts:
        print(f"{args.year}年のレシートが台帳にありません。", file=sys.stderr)
        return 1

    journals = [j for r in receipts for j in build_journals(r)]
    suffix = f"_{args.year}" if args.year else ""
    yayoi_path = write_yayoi_csv(journals, args.out / f"yayoi_import{suffix}.csv")
    review_path = write_review_csv(journals, args.out / f"review{suffix}.csv")

    review_count = sum(1 for j in journals if j.needs_review)
    print()
    print(f"レシート {len(receipts)}枚 → 仕訳 {len(journals)}行 / 合計 {int(total_amount(journals)):,}円")
    print(f"  弥生インポート用: {yayoi_path}")
    print(f"  確認用一覧      : {review_path}")
    if review_count:
        print(f"  ⚠ 要確認 {review_count}行。review.csv を直してから取り込んでください。")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    receipts = ledger.receipts(year=args.year)
    if not receipts:
        print("台帳は空です。")
        return 0
    for r in receipts:
        flag = " ⚠" if r.warnings or r.issue_date is None else ""
        date_str = r.issue_date.strftime("%Y/%m/%d") if r.issue_date else "日付不明  "
        print(f"{date_str}  {int(r.total):>8,}円  {r.shop}{flag}")
    print(f"\n合計 {len(receipts)}枚 / {int(sum(r.total for r in receipts)):,}円")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="receipt2yayoi",
        description="レシート写真を台帳にためて、弥生会計の仕訳インポートCSVを作ります。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="写真を台帳に取り込み、CSVを作り直す")
    p_add.add_argument("targets", type=Path, nargs="+", help="画像ファイル、またはフォルダ")
    _add_common(p_add)
    p_add.set_defaults(func=cmd_add)

    p_record = sub.add_parser(
        "record", help="読み取り済みの内容をJSONで台帳に記録する（チャット添付用）"
    )
    p_record.add_argument("--image", type=Path, required=True, help="元のレシート画像")
    p_record.add_argument(
        "--json", default="-", help="レシート内容のJSON。'-' で標準入力（既定）"
    )
    p_record.add_argument("--force", action="store_true", help="取り込み済みでも上書きする")
    _add_common(p_record)
    p_record.set_defaults(func=cmd_record)

    p_build = sub.add_parser("build", help="台帳からCSVだけ作り直す")
    _add_common(p_build)
    p_build.set_defaults(func=cmd_build)

    p_list = sub.add_parser("list", help="台帳の中身を一覧表示する")
    _add_common(p_list)
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
