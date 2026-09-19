from pathlib import Path

import pytest

from receipt2yayoi.people import UnknownPerson, resolve


@pytest.mark.parametrize(
    "value,expected",
    [
        ("英之", "hideyuki"),
        ("ひでゆき", "hideyuki"),
        ("hideyuki", "hideyuki"),
        ("Hide", "hideyuki"),
        ("英之用", "hideyuki"),
        (" 英之 ", "hideyuki"),
        ("祐子", "yuko"),
        ("ゆうこ", "yuko"),
        ("yuko", "yuko"),
        ("祐子の分", "yuko"),
    ],
)
def test_accepts_common_ways_of_naming_them(value: str, expected: str):
    assert resolve(value).slug == expected


@pytest.mark.parametrize("value", ["", "   ", "太郎", "ひで子", "unknown"])
def test_refuses_to_guess(value: str):
    """曖昧なら止まる。別人の台帳に入れるより、聞き直すほうがはるかにまし。"""
    with pytest.raises(UnknownPerson):
        resolve(value)


def test_paths_are_separate_per_person():
    hide, yuko = resolve("英之"), resolve("祐子")
    assert hide.ledger_path() != yuko.ledger_path()
    assert hide.out_dir() != yuko.out_dir()
    assert hide.ledger_path() == Path("ledger/hideyuki.json")
    assert yuko.out_dir() == Path("out/yuko")
