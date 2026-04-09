"""Selection-expression parsing and selector resolution helpers."""

from __future__ import annotations


def selector_set(
    key: str,
    *,
    all_body_keys: set[str],
    major_planets: set[str],
    all_planets: set[str],
    inner_planets: set[str],
    outer_planets: set[str],
    dwarf_planets: set[str],
) -> set[str]:
    token = "".join(ch for ch in str(key).lower() if ch.isalnum())
    selectors: dict[str, set[str]] = {
        "all": set(all_body_keys),
        "bodies": set(all_body_keys),
        "planets": set(major_planets),
        "allplanets": set(all_planets),
        "majorplanets": set(major_planets),
        "innerplanets": set(inner_planets),
        "outerplanets": set(outer_planets),
        "dwarfplanets": set(dwarf_planets),
    }

    if token in selectors:
        return selectors[token]
    if token in all_body_keys:
        return {token}
    raise ValueError(f"Unknown selection term: {key}")


def evaluate_selection_expression(
    expr: str,
    *,
    all_body_keys: set[str],
    major_planets: set[str],
    all_planets: set[str],
    inner_planets: set[str],
    outer_planets: set[str],
    dwarf_planets: set[str],
) -> set[str]:
    text = str(expr).replace("(", " ").replace(")", " ")
    words = [w for w in text.split() if w]
    if not words:
        return set(all_body_keys)

    operators = {"and", "or", "not", "except"}
    selected: set[str] | None = None
    op = "add"
    i = 0
    while i < len(words):
        w = words[i].lower()
        if w in ("and", "or"):
            op = "add"
            i += 1
            continue
        if w in ("not", "except"):
            op = "sub"
            i += 1
            continue

        start = i
        while i < len(words) and words[i].lower() not in operators:
            i += 1
        term = " ".join(words[start:i])
        term_set = selector_set(
            term,
            all_body_keys=all_body_keys,
            major_planets=major_planets,
            all_planets=all_planets,
            inner_planets=inner_planets,
            outer_planets=outer_planets,
            dwarf_planets=dwarf_planets,
        )

        if selected is None:
            selected = set(term_set)
            if op == "sub":
                selected = set(all_body_keys) - selected
        elif op == "sub":
            selected -= term_set
        else:
            selected |= term_set

    return selected if selected is not None else set(all_body_keys)
