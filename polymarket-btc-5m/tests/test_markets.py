from __future__ import annotations

from btc5m.markets import window_start_ts


def test_window_alignment():
    assert window_start_ts(1_794_595_574) == 1_794_595_500
    assert window_start_ts(1_794_595_500) == 1_794_595_500
    assert window_start_ts(1_794_595_799) == 1_794_595_500
