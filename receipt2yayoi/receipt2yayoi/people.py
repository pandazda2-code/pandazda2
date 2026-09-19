"""台帳を使う人。

英之と祐子で申告が別なので、台帳もCSVも完全に分ける。
混ざると申告をやり直すことになるため、誰の分か分からないまま
記録することは許さない（推測もしない）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Person:
    slug: str       # ファイル名に使う英字
    name: str       # 表示名
    aliases: tuple[str, ...]  # 呼び方のゆれ

    def ledger_path(self, root: Path = Path("ledger")) -> Path:
        return root / f"{self.slug}.json"

    def out_dir(self, root: Path = Path("out")) -> Path:
        return root / self.slug


PEOPLE: tuple[Person, ...] = (
    Person(
        slug="hideyuki",
        name="英之",
        aliases=("英之", "ひでゆき", "ヒデユキ", "hideyuki", "hide", "英之さん", "英之用"),
    ),
    Person(
        slug="yuko",
        name="祐子",
        aliases=("祐子", "ゆうこ", "ユウコ", "yuko", "yuuko", "祐子さん", "祐子用"),
    ),
)


class UnknownPerson(ValueError):
    """誰の分か特定できなかった。"""


def resolve(value: str) -> Person:
    """呼び方から人を特定する。曖昧なら例外にして、推測はしない。"""
    key = (value or "").strip().lower().removesuffix("の分").removesuffix("用")
    if not key:
        raise UnknownPerson("誰の分か指定されていません。")
    for person in PEOPLE:
        if key == person.slug or key in {a.lower() for a in person.aliases}:
            return person
    names = " / ".join(p.name for p in PEOPLE)
    raise UnknownPerson(f"「{value}」が誰か分かりません。{names} のどちらかを指定してください。")


def names() -> str:
    return " / ".join(p.name for p in PEOPLE)
