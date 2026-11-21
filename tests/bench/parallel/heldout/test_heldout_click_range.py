import click
from click.testing import CliRunner


def _help(t):
    @click.command()
    @click.option("--v", type=t)
    def f(v):
        pass

    return CliRunner().invoke(f, ["--help"]).output


def test_min_only_closed_and_open():
    assert "x>=1" in _help(click.IntRange(min=1))
    assert "x>1" in _help(click.IntRange(min=1, min_open=True))
    assert "x>=0" in _help(click.FloatRange(min=0))
    assert "x>0" in _help(click.FloatRange(min=0, min_open=True))


def test_max_only_and_both_unchanged():
    assert "x<=5" in _help(click.IntRange(max=5))
    assert "x<5" in _help(click.IntRange(max=5, max_open=True))
    assert "1<=x<=5" in _help(click.IntRange(1, 5))
    assert "1<x<5" in _help(click.FloatRange(1, 5, min_open=True, max_open=True))
