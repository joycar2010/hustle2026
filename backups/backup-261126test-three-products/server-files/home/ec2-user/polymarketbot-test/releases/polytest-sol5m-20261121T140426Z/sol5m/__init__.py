"""Isolated SOL Up/Down 5-minute Paper release.

The release keeps the upstream ``btc5m`` engine as an implementation detail,
but exposes SOL-specific entry points and storage names.  It is intended to
run from its own checkout/virtualenv so no BTC worker state is shared.
"""

__version__ = "sol5m-paper-1.0"

