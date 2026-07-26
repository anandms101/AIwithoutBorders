#!/usr/bin/env python
"""Seed the WHO syndromic case definitions into the vector table (F-04).

Paraphrased into our own schema per docs/DECISIONS.md D14, with the WHO
adaptation disclaimer carried on every row.

    .venv/bin/python scripts/seed_case_definitions.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from outpost.case_definitions_data import CASE_DEFINITIONS, DISCLAIMER  # noqa: E402
from outpost.config import settings  # noqa: E402
from outpost.db import connect, init_db  # noqa: E402
from outpost.llm import OllamaClient  # noqa: E402
from outpost.workers.casedef import upsert_definition  # noqa: E402


def main() -> int:
    init_db(settings)
    client = OllamaClient(settings)

    if not client.health():
        print(f"ERROR: Ollama unreachable at {settings.ollama_host}", file=sys.stderr)
        return 1

    print(f"Seeding {len(CASE_DEFINITIONS)} case definitions")
    print(f"  model    : {settings.embed_model}")
    print(f"  database : {settings.db_path}")

    started = time.perf_counter()
    with connect(settings) as conn:
        for code, title, definition in CASE_DEFINITIONS:
            upsert_definition(
                code,
                title,
                definition,
                DISCLAIMER,
                client=client,
                connection=conn,
                config=settings,
            )
            print(f"  + {code}")

        count = conn.execute("SELECT COUNT(*) FROM case_definitions").fetchone()[0]

    print(f"Done: {count} definitions in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
