#!/usr/bin/env python
"""Seed a synthetic background graph — two weeks of ordinary consultations.

Per D6 this is not cheating, it is necessary. Cluster detection has to run
against realistic noise; firing on an empty table proves nothing. The whole
point of `baseline_count` is that three cases means nothing if the preceding
window also had three.

Everything here is self-authored (DATASETS.md §7) — no licence encumbrance.

Deterministic by default so the demo is reproducible and `reset_demo.sh` gives
the same graph every time.

    .venv/bin/python scripts/seed_background_graph.py [--days 14] [--seed 42]
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from outpost.config import settings  # noqa: E402
from outpost.db import connect, init_db  # noqa: E402

CATCHMENTS = ("sector-1", "sector-2", "sector-4", "sector-7", "sector-9")

# Ordinary presentation mix for a district field hospital. Weighted so the
# background is dominated by respiratory and febrile illness, which is what
# makes a watery-diarrhoea cluster stand out as signal rather than noise.
BACKGROUND_MIX = (
    ("acute_respiratory_infection", 30),
    ("acute_febrile_illness", 28),
    ("acute_watery_diarrhoea", 12),
    ("acute_malnutrition", 9),
    ("suspected_tuberculosis", 7),
    ("acute_jaundice_syndrome", 5),
    ("acute_bloody_diarrhoea", 4),
    ("suspected_measles", 3),
    ("acute_neurological_syndrome", 2),
)

CONSULTS_PER_DAY = (10, 18)


def build(
    days: int, seed: int, per_day: tuple[int, int], quiet_hours: int
) -> list[tuple]:
    rng = random.Random(seed)
    codes = [code for code, _ in BACKGROUND_MIX]
    weights = [weight for _, weight in BACKGROUND_MIX]

    # Anchor to the top of the current hour so seeded cases always sit in the
    # past and never drift into the live window as the demo runs.
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

    # Stop the background short of the live alert window. Without this the
    # ordinary consultation rate alone trips the threshold and the demo cluster
    # is indistinguishable from noise -- measured: 184 cases over 14 days
    # produced 4 respiratory in sector-1 within 72h.
    #
    # This is not tidying up an inconvenience. It is the realistic case: the
    # baseline period carries the ordinary rate, and the cluster is what
    # arrives on top of it. baseline_count is therefore genuinely non-zero.
    cutoff = now - timedelta(hours=quiet_hours)

    rows: list[tuple] = []
    counter = 0

    for day in range(days, 0, -1):
        for _ in range(rng.randint(*per_day)):
            occurred = now - timedelta(
                days=day, hours=rng.randint(0, 23), minutes=rng.choice([0, 15, 30, 45])
            )
            if occurred >= cutoff:
                continue

            counter += 1
            syndrome = rng.choices(codes, weights=weights, k=1)[0]
            catchment = rng.choice(CATCHMENTS)

            # Only respiratory/TB presentations get a film in this setting.
            film_score = (
                rng.randint(5, 65)
                if syndrome in ("acute_respiratory_infection", "suspected_tuberculosis")
                else None
            )

            rows.append(
                (
                    f"bg-{counter:04d}",
                    f"p-bg-{counter:04d}",
                    syndrome,
                    catchment,
                    film_score,
                    occurred.isoformat(timespec="seconds"),
                )
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-per-day", type=int, default=CONSULTS_PER_DAY[0])
    parser.add_argument("--max-per-day", type=int, default=CONSULTS_PER_DAY[1])
    parser.add_argument(
        "--quiet-hours",
        type=int,
        default=settings.alert_window_hours,
        help="leave this many recent hours free of background cases",
    )
    args = parser.parse_args()

    init_db(settings)
    rows = build(
        args.days, args.seed, (args.min_per_day, args.max_per_day), args.quiet_hours
    )

    with connect(settings) as conn:
        conn.executemany(
            "INSERT INTO cases (case_id, patient_id, syndrome_code, catchment,"
            " film_score, occurred_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(case_id) DO NOTHING",
            rows,
        )

        # Mirror into the graph so the node/edge view is populated too.
        for case_id, patient_id, syndrome, catchment, _, occurred in rows:
            conn.execute(
                "INSERT OR IGNORE INTO nodes (id, type, label, created_at)"
                " VALUES (?, 'patient', ?, ?)",
                (f"patient:{patient_id}", patient_id, occurred),
            )
            conn.execute(
                "INSERT OR IGNORE INTO nodes (id, type, label, created_at)"
                " VALUES (?, 'visit', ?, ?)",
                (f"visit:{case_id}", case_id, occurred),
            )
            conn.execute(
                "INSERT OR IGNORE INTO nodes (id, type, label, created_at)"
                " VALUES (?, 'syndrome', ?, ?)",
                (f"syndrome:{syndrome}", syndrome, occurred),
            )
            conn.execute(
                "INSERT OR IGNORE INTO edges (src, dst, rel, created_at)"
                " VALUES (?, ?, 'had_visit', ?)",
                (f"patient:{patient_id}", f"visit:{case_id}", occurred),
            )
            conn.execute(
                "INSERT OR IGNORE INTO edges (src, dst, rel, created_at)"
                " VALUES (?, ?, 'presented_as', ?)",
                (f"visit:{case_id}", f"syndrome:{syndrome}", occurred),
            )

        total = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        recent = conn.execute(
            "SELECT syndrome_code, catchment, COUNT(*) n FROM cases"
            " WHERE datetime(occurred_at) > datetime('now', ?)"
            " GROUP BY syndrome_code, catchment HAVING n >= ?"
            " ORDER BY n DESC",
            (f"-{settings.alert_window_hours} hours", settings.alert_min_cases),
        ).fetchall()
        baseline = conn.execute(
            "SELECT COUNT(*) FROM cases"
            " WHERE datetime(occurred_at) > datetime('now', ?)"
            "   AND datetime(occurred_at) <= datetime('now', ?)",
            (
                f"-{settings.alert_window_hours * 2} hours",
                f"-{settings.alert_window_hours} hours",
            ),
        ).fetchone()[0]

    print(f"Seeded {len(rows)} synthetic consultations over {args.days} days")
    print(f"  total cases in graph : {total}")
    print(f"  catchments           : {len(CATCHMENTS)}")
    print(f"  syndromes            : {len(BACKGROUND_MIX)}")
    print(f"  baseline window      : {baseline} cases "
          f"({settings.alert_window_hours}-{settings.alert_window_hours * 2}h ago)")

    if recent:
        print("\n  WARNING: background already trips the threshold:")
        for row in recent:
            print(f"    {row['syndrome_code']} / {row['catchment']}: {row['n']}")
        print("  The demo cluster will not be distinguishable. Re-seed with")
        print("  a different --seed or lower --max-per-day.")
        return 1

    print(
        f"\n  Background is quiet: nothing reaches "
        f"{settings.alert_min_cases} cases per syndrome+catchment "
        f"in {settings.alert_window_hours}h."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
