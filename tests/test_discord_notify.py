import random

from src.discord_notify import BOOM_PRAISE_LINE, PRAISE_LINES, choose_praise_line


def test_boom_gets_his_own_line_regardless_of_seed() -> None:
    for seed in range(10):
        assert choose_praise_line("Rirhcceez", rng=random.Random(seed)) == BOOM_PRAISE_LINE


def test_everyone_else_gets_a_generic_praise_line() -> None:
    for seed in range(20):
        line = choose_praise_line("kwank6704", rng=random.Random(seed))
        assert line in PRAISE_LINES
        assert line != BOOM_PRAISE_LINE
