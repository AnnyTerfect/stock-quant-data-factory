"""Canonical market-data field names.

Ordered tuples on purpose: several call sites concatenate per-field arrays and
compare the results positionally, so the order has to be reproducible.
"""

MINUTE_FIELDS = ("open", "high", "low", "close", "volume", "amount")
PRICE_FIELDS = ("open", "high", "low", "close")
