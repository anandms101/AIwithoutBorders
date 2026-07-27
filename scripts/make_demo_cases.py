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
    # --- Spare cases, held back for live drag-and-drop on stage. ---
    # Dropping case-0426 during the demo grows the cluster from 3 to 4, which
    # re-raises the alert and shows the system reacting to new evidence rather
    # than replaying something prepared earlier.
    (
        "case-0426",
        "sector-4",
        "Adult male, same settlement as recent presentations. Watery stools "
        "since dawn, five episodes, no blood. Vomited once. Very thirsty, "
        "reduced skin turgor. Reports the household draws water from the "
        "shallow well at the north edge.",
        True,
    ),
    (
        "case-0427",
        "sector-4",
        "Elderly female. Profuse watery stools overnight, unable to keep "
        "fluids down. Markedly sunken eyes, weak pulse, minimal urine output. "
        "No blood in the stool. Same water source as neighbouring shelters.",
        True,
    ),
    # Other syndromes in other catchments — the graph holds more than one
    # story at a time, and none of these disturb the sector-4 cluster.
    (
        "case-0428",
        "sector-7",
        "Adult with cough for over three weeks, coughing blood on two "
        "occasions. Drenching night sweats and unintended weight loss over "
        "the past month. Persistent chest pain. Chest film requested.",
        False,
    ),
    (
        "case-0429",
        "sector-2",
        "Child with fever for two days and a generalised rash that began on "
        "the face and spread downwards. Red eyes, runny nose and a harsh "
        "cough. No diarrhoea.",
        False,
    ),
    (
        "case-0430",
        "sector-1",
        "Adult presenting with yellowing of the eyes noticed three days ago. "
        "Dark urine and pale stools. Loss of appetite, nausea and discomfort "
        "in the right upper abdomen. Profound fatigue.",
        False,
    ),
)

# Held back from the scripted drop so they can be dragged in live on stage.
SPARE_CASES = ("case-0426", "case-0427", "case-0428", "case-0429", "case-0430")


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
        if case_id in SPARE_CASES:
            marker = "spare  "
        else:
            marker = "cluster" if trips else "decoy  "
        print(f"  {marker}  {path.name}  [{catchment}]")

    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    scripted = [c for c in DEMO_CASES if c[0] not in SPARE_CASES]
    cluster = sum(1 for _, _, _, trips in scripted if trips)
    print(f"\nWrote {len(DEMO_CASES)} case notes to {outdir}/")
    print(f"  {cluster} designed to trip the threshold (sector-4)")
    print(f"  {len(scripted) - cluster} decoys that must not fire")
    print(f"  {len(SPARE_CASES)} spares held back for live drag-and-drop")
    print(f"  catchment manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
