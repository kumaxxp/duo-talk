import os
import sys

sys.path.append(os.getcwd())

from duo_chat_entertain import load_policy, pick_beat, pick_cut, need_finish


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
