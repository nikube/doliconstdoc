import hashlib
import json


def content_bundle(
    name: str,
    type_: str | None,
    default_value: str | None,
    module: str | None,
    occurrences: list[tuple[str, int, str, str]],
) -> str:
    """Build deterministic bundle for hashing.

    occurrences: list of (file, line, usage_type, context) already sorted.
    """
    payload = {
        "n": name,
        "t": type_ or "",
        "d": default_value if default_value is not None else "",
        "m": module or "",
        "o": [
            {"f": f, "l": l, "u": u, "c": c}
            for (f, l, u, c) in sorted(occurrences, key=lambda x: (x[0], x[1]))
        ],
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def content_hash(bundle: str) -> str:
    return hashlib.sha256(bundle.encode("utf-8")).hexdigest()
