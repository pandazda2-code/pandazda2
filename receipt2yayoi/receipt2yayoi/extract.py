"""レシート画像をClaudeのvisionで読み取って構造化する。"""

from __future__ import annotations

import base64
import json
import mimetypes
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import anthropic

from receipt2yayoi.models import Receipt, ReceiptLine

MODEL = "claude-opus-5"

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}

SYSTEM = """あなたは日本の個人事業主の経理担当者です。
渡されたレシート・領収書の画像を読み取り、record_receipt ツールで内容を報告してください。

守ること:
- 金額は税込。カンマや「¥」は除き、半角数字のみで返す。
- 日付は和暦なら西暦に直し YYYY-MM-DD 形式にする。年が印字されていなければ null。
- 軽減税率（※印や「軽」マーク、食品・テイクアウト飲食料品）は tax_rate を 8 にする。
- インボイス登録番号（Tで始まる13桁）があれば必ず拾う。なければ null。
- 読み取れない項目は推測せず null または空にし、不確かな点は warnings に日本語で書く。
- 合計金額が明細の合算と合わない場合も、合計はレシートに印字された値を優先し warnings に書く。"""

RECEIPT_TOOL: dict = {
    "name": "record_receipt",
    "description": "レシート1枚から読み取った内容を記録する。",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "issue_date": {
                "type": ["string", "null"],
                "description": "発行日 YYYY-MM-DD。読めなければ null。",
            },
            "shop": {"type": "string", "description": "店名・発行者名"},
            "total": {"type": "string", "description": "税込合計金額（半角数字のみ）"},
            "payment": {
                "type": "string",
                "enum": [
                    "現金",
                    "クレジットカード",
                    "電子マネー",
                    "QRコード決済",
                    "デビット",
                    "不明",
                ],
            },
            "invoice_number": {
                "type": ["string", "null"],
                "description": "インボイス登録番号（T+13桁）。なければ null。",
            },
            "lines": {
                "type": "array",
                "description": "明細。読み取れなければ空配列でよい。",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "amount": {"type": "string"},
                        "tax_rate": {"type": "integer", "enum": [8, 10]},
                    },
                    "required": ["name", "amount", "tax_rate"],
                },
            },
            "warnings": {
                "type": "array",
                "description": "読み取りに自信がない点（日本語）",
                "items": {"type": "string"},
            },
        },
        "required": [
            "issue_date",
            "shop",
            "total",
            "payment",
            "invoice_number",
            "lines",
            "warnings",
        ],
    },
}


def _encode_image(path: Path) -> dict:
    media_type, _ = mimetypes.guess_type(path.name)
    if media_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
        # HEIC等はPillowでJPEGに変換してから送る
        media_type, data = _convert_to_jpeg(path)
    else:
        data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def _convert_to_jpeg(path: Path) -> tuple[str, str]:
    from io import BytesIO

    from PIL import Image

    with Image.open(path) as img:
        img = img.convert("RGB")
        # 長辺1600pxあれば日本のレシートは十分読める。無駄にトークンを使わない。
        img.thumbnail((1600, 1600))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _to_decimal(value: str | None) -> Decimal:
    if not value:
        return Decimal(0)
    cleaned = str(value).replace(",", "").replace("¥", "").replace("円", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal(0)


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def extract_receipt(path: Path, client: anthropic.Anthropic | None = None) -> Receipt:
    """レシート画像1枚を読み取って Receipt にする。"""
    client = client or anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        tools=[RECEIPT_TOOL],
        tool_choice={"type": "tool", "name": "record_receipt"},
        messages=[
            {
                "role": "user",
                "content": [
                    _encode_image(path),
                    {"type": "text", "text": "このレシートを読み取ってください。"},
                ],
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"{path.name}: モデルが応答を拒否しました")

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_receipt":
            # strict:true でもツール入力は必ず json として扱う（生文字列比較はしない）
            data = block.input
            if isinstance(data, str):
                data = json.loads(data)
            return _build_receipt(path, data)

    raise RuntimeError(f"{path.name}: レシートを読み取れませんでした")


def _build_receipt(path: Path, data: dict) -> Receipt:
    lines = [
        ReceiptLine(
            name=item.get("name", ""),
            amount=_to_decimal(item.get("amount")),
            tax_rate=int(item.get("tax_rate", 10)),
        )
        for item in data.get("lines", [])
    ]
    warnings = list(data.get("warnings") or [])
    issue_date = _to_date(data.get("issue_date"))
    if issue_date is None:
        warnings.append("発行日を読み取れませんでした。手入力してください。")
    total = _to_decimal(data.get("total"))
    if total <= 0:
        warnings.append("合計金額を読み取れませんでした。手入力してください。")

    return Receipt(
        source=str(path),
        issue_date=issue_date,
        shop=data.get("shop") or "",
        total=total,
        lines=lines,
        payment=data.get("payment") or "現金",
        invoice_number=data.get("invoice_number"),
        warnings=warnings,
    )


def iter_images(target: Path) -> list[Path]:
    """ファイルまたはディレクトリから対象画像を集める。"""
    if target.is_file():
        return [target]
    return sorted(
        p for p in target.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES
    )
