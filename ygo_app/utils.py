def normalize_rarity_code(rarity: str) -> str:
    """DragonShield uses UR; YGOProDeck uses (UR)."""
    r = (rarity or "").strip()
    if not r:
        return r
    if r.startswith("(") and r.endswith(")"):
        return r
    return f"({r})"


def rarity_display(rarity_code: str) -> str:
    r = (rarity_code or "").strip()
    if r.startswith("(") and r.endswith(")"):
        return r[1:-1]
    return r
