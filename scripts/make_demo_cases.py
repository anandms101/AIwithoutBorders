#!/usr/bin/env python
"""Generate the synthetic demo case files.

Three cases designed to trip the threshold (PRD §8): same syndrome, same
catchment, inside the window. Plus two decoys that deliberately must NOT fire —
same syndrome in a different catchment, and a different syndrome in the same
catchment. The negative cases are worth as much as the positive one on stage:
they show the thresholds are real rather than a hardcoded trigger.

All content is self-authored (DATASETS.md §7). No licence encumbrance.

    .venv/bin/python scripts/make_demo_cases.py [--outdir demo_cases]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# (case_id, catchment, note text, should_trip)
DEMO_CASES: tuple[tuple[str, str, str, bool], ...] = (
    (
        "case-0421",
        "sector-4",
        "Female, adult. Presents with profuse watery stools since yesterday "
        "evening, at least eight episodes overnight. Vomiting twice this "
        "morning. Reports intense thirst. On examination the eyes appear sunken "
        "and skin turgor is reduced. No visible blood in the stool. No fever "
        "recorded. Drew water from the shallow well near the north edge of the "
        "settlement.",
        True,
    ),
    (
        "case-0422",
        "sector-4",
        "Male, adult. Sudden onset of watery diarrhoea beginning this morning, "
        "described as rice-water in appearance. Six episodes so far. Weak and "
        "unsteady on standing. Dry mouth, reduced urine output. No blood in the "
        "stool, no abdominal guarding. Household shares a water source with "
        "neighbouring shelters.",
        True,
    ),
    (
        "case-0423",
        "sector-4",
        "Child brought by guardian. Loose watery stools through the night, "
        "guardian counted more than ten. Vomited after being offered fluids. "
        "Lethargic, drinks eagerly when offered oral rehydration solution. Eyes "
        "sunken. No rash, no cough, no blood in the stool.",
        True,
    ),
    # Decoy 1: same syndrome, different catchment -> must NOT contribute.
    (
        "case-0424",
        "sector-9",
        "Adult with watery stools since this morning, three episodes, "
        "tolerating fluids well. Mild thirst, no sunken eyes, skin turgor "
        "normal. No vomiting and no blood in the stool.",
        False,
    ),
    # Decoy 2: different syndrome, same catchment -> must NOT contribute.
    (
        "case-0425",
        "sector-4",
        "Adult with productive cough for four days and shortness of breath on "
        "exertion. Reports fever and night sweats. No diarrhoea and no "
        "vomiting. Chest film requested.",
        False,
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default="demo_cases")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # The catchment has to reach the pipeline somehow. Encoding it in the
    # filename keeps the note itself free-text-only, which matters: the note is
    # what the model reads, and nothing the model reads may decide a catchment.
    manifest = outdir / "catchments.tsv"
    lines = []

    for case_id, catchment, note, trips in DEMO_CASES:
        path = outdir / f"{case_id}.txt"
        path.write_text(note + "\n", encoding="utf-8")
        lines.append(f"{case_id}\t{catchment}")
        marker = "cluster" if trips else "decoy  "
        print(f"  {marker}  {path.name}  [{catchment}]")

    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cluster = sum(1 for _, _, _, trips in DEMO_CASES if trips)
    print(f"\nWrote {len(DEMO_CASES)} case notes to {outdir}/")
    print(f"  {cluster} designed to trip the threshold (sector-4)")
    print(f"  {len(DEMO_CASES) - cluster} decoys that must not fire")
    print(f"  catchment manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
