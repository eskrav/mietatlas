import pandas as pd

from pipeline import equal_interval_breaks


def test_equal_steps_over_full_range():
    values = pd.Series(range(0, 101))
    assert equal_interval_breaks(values, n_classes=6, trim=(0, 100)) == [0, 25, 50, 75, 100]


def test_trimmed_range_leaves_open_end_classes():
    values = pd.Series(range(0, 101))
    assert equal_interval_breaks(values, n_classes=6, trim=(10, 90)) == [10, 30, 50, 70, 90]
