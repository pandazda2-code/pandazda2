"""勘定科目・税区分の推定ルール。

LLMに全部任せず、まずここのキーワード表で決める。
確定申告は毎年同じ店が繰り返し出てくるので、ルールで当たる率が高く、
かつ「去年と同じ科目になる」という一貫性が保てる。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

# 店名・品目キーワード → 勘定科目。上から順に最初に一致したものを使う。
KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("jr", "スイカ", "suica", "pasmo", "icoca", "タクシー", "交通", "鉄道", "バス",
      "ana", "jal", "高速", "etc", "駐車"), "旅費交通費"),
    (("郵便", "ゆうパック", "切手", "レターパック", "クロネコ", "ヤマト", "佐川",
      "宅急便", "日本郵便"), "通信費"),
    (("ドコモ", "docomo", "au", "ソフトバンク", "softbank", "楽天モバイル",
      "nuro", "ocn", "プロバイダ", "インターネット"), "通信費"),
    (("電気", "東京電力", "関西電力", "ガス", "水道"), "水道光熱費"),
    (("amazon", "アマゾン", "ヨドバシ", "ビックカメラ", "ヤマダ電機", "アスクル",
      "モノタロウ", "コーナン", "カインズ", "ダイソー", "文具", "文房具",
      "ロフト", "東急ハンズ"), "消耗品費"),
    (("スターバックス", "スタバ", "ドトール", "タリーズ", "コメダ", "喫茶",
      "カフェ", "居酒屋", "レストラン", "食堂", "寿司", "焼肉"), "会議費"),
    (("セブン", "ファミリーマート", "ローソン", "ミニストップ", "デイリー"),
     "消耗品費"),
    (("aws", "google", "microsoft", "adobe", "github", "openai", "anthropic",
      "notion", "slack", "dropbox", "サブスク", "ライセンス", "クラウド"),
     "通信費"),
    (("書店", "書房", "ブックス", "紀伊國屋", "丸善", "新聞", "雑誌", "図書"),
     "新聞図書費"),
    (("セミナー", "研修", "講座", "スクール"), "研修費"),
    (("印刷", "キンコーズ", "コピー", "名刺"), "印刷製本費"),
    (("保険", "共済"), "保険料"),
    (("家賃", "賃料", "レンタルオフィス", "コワーキング"), "地代家賃"),
]

# 軽減税率(8%)になりやすい品目のヒント
REDUCED_RATE_HINTS = ("弁当", "おにぎり", "飲料", "パン", "牛乳", "食品", "米",
                      "野菜", "菓子", "コーヒー豆", "水")

# 支払手段 → 貸方科目
PAYMENT_ACCOUNTS: dict[str, str] = {
    "現金": "現金",
    "クレジットカード": "未払金",
    "クレジット": "未払金",
    "カード": "未払金",
    "電子マネー": "事業主貸",
    "交通系ic": "事業主貸",
    "qr": "事業主貸",
    "paypay": "事業主貸",
    "デビット": "普通預金",
    "口座振替": "普通預金",
    "銀行振込": "普通預金",
}

DEFAULT_ACCOUNT = "雑費"


def guess_account(shop: str, items: list[str]) -> tuple[str, bool]:
    """勘定科目を推定する。

    Returns:
        (勘定科目, 要確認フラグ)。ルールに当たらなければ雑費＋要確認。
    """
    haystack = " ".join([shop, *items]).lower()
    for keywords, account in KEYWORD_RULES:
        if any(kw.lower() in haystack for kw in keywords):
            return account, False
    return DEFAULT_ACCOUNT, True


def guess_payment_account(payment: str) -> str:
    """支払手段から貸方科目を決める。"""
    key = (payment or "").strip().lower()
    for token, account in PAYMENT_ACCOUNTS.items():
        if token in key:
            return account
    return "現金"


def tax_category(rate: int, invoice_number: str | None) -> str:
    """弥生の税区分文字列を返す。

    インボイス登録番号がないレシートは仕入税額控除が満額使えないため、
    経過措置の区分（80%控除）を当てる。
    """
    base = f"課対仕入{rate}%"
    if not invoice_number:
        return f"{base}区分80"
    return base


def tax_amount(amount: Decimal, rate: int) -> Decimal:
    """税込金額から消費税額を算出（円未満切り捨て）。"""
    return (amount * Decimal(rate) / Decimal(100 + rate)).quantize(
        Decimal("1"), rounding=ROUND_DOWN
    )


def is_reduced_rate(item_name: str) -> bool:
    """品目名から軽減税率対象かを推測する。"""
    return any(hint in item_name for hint in REDUCED_RATE_HINTS)
