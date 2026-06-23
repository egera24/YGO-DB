"""One-off consistency check for data/catalog Cardmarket artifacts."""
import json
from collections import Counter, defaultdict
from pathlib import Path

CAT = Path(__file__).resolve().parents[1] / "data" / "catalog"


def load(name):
    p = CAT / name
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    exp_list = load("cardmarket_expansion_list.json")
    card_list = load("cardmarket_card_list.json")
    empty = load("cardmarket_empty_expansions.json") or []
    rejected = load("cardmarket_rejected_expansions.json") or []
    cp = load("cardmarket_card_list_checkpoint.json")
    idx = cp["last_expansion_idx"]

    exp_ids_in_list = {c["expansion_id"] for c in card_list}
    empty_ids = {e["expansion_id"] for e in empty}
    rejected_ids = {e["expansion_id"] for e in rejected}

    print("=== SNAPSHOT ===")
    print(f"  expansion_list: {len(exp_list)}")
    print(f"  card_list: {len(card_list)} cards, {len(exp_ids_in_list)} expansions")
    print(f"  empty: {len(empty_ids)}, rejected: {len(rejected_ids)}")
    print(f"  checkpoint last_expansion_idx: {idx}")

    last_e = exp_list[idx]
    print(
        f"  last completed: idx={idx} id={last_e['expansion_id']} "
        f"name={last_e['expansion_name']!r}"
    )
    if idx + 1 < len(exp_list):
        next_e = exp_list[idx + 1]
        print(
            f"  next pending:   idx={idx + 1} id={next_e['expansion_id']} "
            f"name={next_e['expansion_name']!r}"
        )

    for i, e in enumerate(exp_list):
        if e["expansion_id"] == 6154:
            n = sum(1 for c in card_list if c["expansion_id"] == 6154)
            rel = "before/equal" if i <= idx else "after"
            print(f"  expansion 6154: idx={i}, cards={n}, {rel} checkpoint")

    cats = defaultdict(list)
    for i in range(idx + 1):
        e = exp_list[i]
        eid = e["expansion_id"]
        if eid in exp_ids_in_list:
            cats["has_cards"].append(i)
        elif eid in empty_ids:
            cats["empty"].append(i)
        elif eid in rejected_ids:
            cats["rejected"].append(i)
        else:
            cats["unaccounted"].append(
                (i, eid, e["expansion_name"], e.get("total_number_of_cards"))
            )

    print(f"\n=== PROCESSED idx 0..{idx} ===")
    for k in ("has_cards", "empty", "rejected", "unaccounted"):
        print(f"  {k}: {len(cats[k])}")

    print("\n=== UNACCOUNTED ===")
    for row in cats["unaccounted"][:25]:
        print(f"  idx={row[0]} id={row[1]} total={row[3]} name={row[2]!r}")
    if len(cats["unaccounted"]) > 25:
        print(f"  ... and {len(cats['unaccounted']) - 25} more")

    after527 = [u for u in cats["unaccounted"] if u[0] > 527]
    print(f"\n  unaccounted after idx 527: {len(after527)}")
    for u in after527:
        print(f"    idx={u[0]} id={u[1]} total={u[3]} name={u[2]!r}")

    print("\n=== IDX 528-538 (post-6154 batch) ===")
    for i in range(528, min(539, len(exp_list))):
        e = exp_list[i]
        eid = e["expansion_id"]
        n = sum(1 for c in card_list if c["expansion_id"] == eid)
        if eid in exp_ids_in_list:
            st = "HAS_CARDS"
        elif eid in empty_ids:
            st = "EMPTY"
        elif eid in rejected_ids:
            st = "REJECTED"
        else:
            st = "UNACCOUNTED"
        print(
            f"  idx={i} id={eid} cards={n} status={st} "
            f"total_field={e.get('total_number_of_cards', 'MISSING')}"
        )

    after = exp_list[idx + 1 :]
    after_ids = {e["expansion_id"] for e in after}
    after_in_cards = after_ids & exp_ids_in_list
    print(f"\n=== AFTER CHECKPOINT ({len(after)} remaining) ===")
    print(f"  with cards already in card_list: {len(after_in_cards)}")

    dups = [cid for cid, n in Counter(c["card_id"] for c in card_list).items() if n > 1]
    print(f"\n  duplicate card_ids: {len(dups)}")

    print("\n=== REJECTED vs CHECKPOINT INDEX ===")
    for r in rejected:
        eid = r["expansion_id"]
        for i, e in enumerate(exp_list):
            if e["expansion_id"] == eid:
                rel = "processed" if i <= idx else "AFTER checkpoint"
                print(
                    f"  id={eid} idx={i} ({rel}) name={e['expansion_name']!r} "
                    f"attempts={r.get('total_attempts')}"
                )
                break

    print("\n=== PROGRESS vs PREVIOUS CHECK (538 -> 596) ===")
    print("  card_list: 25043 -> 29065 cards (+4022)")
    print("  expansions with cards: 327 -> 394 (+67)")
    print("  unaccounted in processed range: 197 -> %d" % len(cats["unaccounted"]))

    print("\n=== CARD DETAILS FILES ===")
    for fn in (
        "cardmarket_card_details.json",
        "cardmarket_card_details_checkpoint.json",
        "cardmarket_card_details_rejection.json",
    ):
        p = CAT / fn
        print(f"  {fn}: {'EXISTS' if p.exists() else 'MISSING'}")


if __name__ == "__main__":
    main()
