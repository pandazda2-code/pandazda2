"""勘定科目・税区分の推定ルール。

LLMに全部任せず、まずここのキーワード表で決める。
確定申告は毎年同じ店が繰り返し出てくるので、ルールで当たる率が高く、
かつ「去年と同じ科目になる」という一貫性が保てる。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_DOWN

# 店名・品目キーワード → 勘定科目。上から順に最初に一致したものを使う。
KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("jr", "スイカ", "suica", "pasmo", "icoca", "タクシー", "交通", "鉄道", "バス",
      "ana", "jal", "高速", "etc", "駐車",
      # 新幹線（EX予約・スマートEX）。領収書の発行者名は「東海旅客鉄道」で
      # JRの字が入らないため、社名と列車名も拾う
      "東海旅客鉄道", "西日本旅客鉄道", "東日本旅客鉄道",
      "ex予約", "スマートex", "exご利用票", "新幹線",
      "のぞみ", "ひかり", "こだま", "はやぶさ", "さくら"), "旅費交通費"),
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
#
# 既定は「事業主借」。個人のカード・現金で立て替えて払っているため。
# 事業用の口座やカードだと分かっているものだけ、普通預金・未払金にする。
PAYMENT_ACCOUNTS: dict[str, str] = {
    "事業用口座": "普通預金",
    "事業用カード": "未払金",
    "口座振替": "普通預金",
    "銀行振込": "普通預金",
}

DEFAULT_CREDIT_ACCOUNT = "事業主借"

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
    return DEFAULT_CREDIT_ACCOUNT


# インボイス経過措置の控除率が切り替わる日。
# 2023/10/1〜2026/9/30 は80%、2026/10/1〜2029/9/30 は70%。
TRANSITIONAL_70_FROM = date(2026, 10, 1)


def tax_category(
    rate: int, invoice_number: str | None, entry_date: date | None = None
) -> str:
    """弥生の税区分文字列を返す。

    税込金額で記帳するので「内」（内税）を使う。

    インボイス登録番号がないものは仕入税額控除が満額使えない。控除率は
    取引日で変わるため、日付を見て区分を選ぶ。日付が読めないものは
    どちらとも決められないので、不利でない側（80%）にせず新しい側に寄せず、
    呼び出し側で要確認に回している前提で現行の率を当てる。
    """
    base = f"課対仕入内{rate}%" if rate == 10 else f"課対仕入内軽減{rate}%"
    if invoice_number:
        return base
    on = entry_date or TRANSITIONAL_70_FROM
    ratio = 70 if on >= TRANSITIONAL_70_FROM else 80
    return f"{base}区{ratio}%"


def tax_amount(amount: Decimal, rate: int) -> Decimal:
    """税込金額から消費税額を算出（円未満切り捨て）。"""
    return (amount * Decimal(rate) / Decimal(100 + rate)).quantize(
        Decimal("1"), rounding=ROUND_DOWN
    )


def is_reduced_rate(item_name: str) -> bool:
    """品目名から軽減税率対象かを推測する。"""
    return any(hint in item_name for hint in REDUCED_RATE_HINTS)
