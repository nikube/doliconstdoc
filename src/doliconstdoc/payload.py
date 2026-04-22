"""Build enrichment payloads for LLM agents from the DB.

Payload shape (per constant):
    ===== NAME =====
    TYPE: ... | DEFAULT: ... | MODULE: ...
    HIDDEN_GUESS: 0 | ADMIN_UI: <files>
    CONF_PHP_WIRING: $dolibarr_main_foo (conf.php) -> $conf->global->FOO   # optional
    OCC: N
    <top ranked occurrences with extended context>
    COMMENTS:
      path/file.php:123  // authoritative comment about FOO
      ...

Comments are authoritative because Dolibarr devs frequently drop explanatory
`//` comments near the setting handlers (e.g. `// FOO may be defined or not
(-1=forbidden, 0 or undefined=no limit)`). Including them verbatim prevents
the LLM from extrapolating usage semantics.
"""

from __future__ import annotations

import sqlite3
from .enrich import format_occurrences


def build_payload(conn: sqlite3.Connection, name: str, occ_cap: int = 8,
                  comment_cap: int = 6) -> str:
    row = conn.execute(
        "SELECT type, default_value, module, hidden_setting_guess, "
        "admin_ui_files, conf_php_wiring FROM constants WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        return f"===== {name} =====\n(not found)"
    type_, default_value, module, hidden_guess, admin_ui, wiring = row
    occs = [
        (o[0], o[1], o[2], o[3])
        for o in conn.execute(
            "SELECT file, line, usage_type, context FROM occurrences "
            "WHERE const_name = ?",
            (name,),
        )
    ]
    comments = list(conn.execute(
        "SELECT file, line, text FROM comments WHERE const_name = ? "
        "ORDER BY line LIMIT ?",
        (name, comment_cap),
    ))

    lines = [f"===== {name} ====="]
    lines.append(f"TYPE: {type_} | DEFAULT: {default_value!r} | MODULE: {module}")
    lines.append(
        f"HIDDEN_GUESS: {hidden_guess} | ADMIN_UI: {(admin_ui or '')[:180]}"
    )
    if wiring:
        lines.append(f"CONF_PHP_WIRING: {wiring}")
    lines.append(f"OCC: {len(occs)}")
    lines.append(format_occurrences(occs, cap=occ_cap))
    if comments:
        lines.append("COMMENTS:")
        for f, ln, txt in comments:
            lines.append(f"  {f}:{ln}  {txt[:260]}")
    return "\n".join(lines)
