import os
import sys

sys.path.append(os.getcwd())

from duo_chat_entertain import (
    load_policy,
    pick_beat,
    pick_cut,
    need_finish,
    load_agree_words,
    contains_agree,
    soften_agree_phrases,
)


def test_pick_beat_default_policy():
    pol = load_policy()
    assert pick_beat(1, pol) == "BANter"
    assert pick_beat(3, pol) == "PIVOT"
    # 6ターンは PIVOT と PAYOFF が衝突するが、"6以降はPAYOFF" を優先
    assert pick_beat(7, pol) == "PAYOFF"


def test_pick_cut_last_turn_tag():
    pol = load_policy()
    assert pick_cut(8, 8, pol) == "TAG"


def test_need_finish_detects_tag():
    assert need_finish("…ここで切る（TAG）。") is True


def test_agree_words_soften_minimal():
    words = load_agree_words()
    text = "要するに 合意 できたという結論として 話を進めよう。"
    # 初期状態では検出される
    assert contains_agree(text, words) is True
    # 弱体化置換後は語が消えていること
    softened = soften_agree_phrases(text)
    assert all(w not in softened for w in words)
