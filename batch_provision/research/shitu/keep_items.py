"""Items no script may drop or sell (user 2026-11-07: (御)通关钥匙 and (御)温泉消费券 were dropped in the 元素使 line).

They are 杂物 (type 0x1000), so every "drop the junk" / "sell the junk" loop caught them: farm.junk (no `important`
check), r4_util.drop_order (the 温泉消费券 is not marked important), sell_tradable (the tradable 通关钥匙 / 温泉消费券).
Matched by name (with or without the (御) prefix) so a new item id of the same name is covered too.
"""
KEEP_WORDS = ('通关钥匙', '温泉消费券', '温泉消费卷')


def kept(it):
    """True when item `it` (ItemLib entry or None) must never be dropped or sold by a script."""
    return it is not None and any(k in getattr(it, 'name', '') for k in KEEP_WORDS)
