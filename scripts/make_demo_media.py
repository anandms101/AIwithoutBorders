#!/usr/bin/env python
"""Build the demo media so every dashboard feature has something to show.

Produces, per case:

* a **French consultation recording** (`.wav`) — exercises F-02 ASR + translation
  and fills the side-by-side transcript panel (F-11);
* a **chest radiograph** (`.jpg`) — exercises F-03 and fills the imaging panel;
* the **note** (`.txt`) — exercises F-04 case-definition retrieval.

Audio is synthesised locally with Piper (`fr_FR-siwis-medium`), so it is
self-authored and needs no clearance, and no network at demo time.

Radiographs are fetched once and cached under `demo_media/`. They are real
films, which matters — a synthetic gradient does not demonstrate that MedGemma
reads radiographs. Swap in TBX11K / COVID-19 Radiography from the USB drive for
the recorded video; see docs/DATASETS.md §7 before anything goes on camera.

    .venv/bin/python scripts/make_demo_media.py
    .venv/bin/python scripts/make_demo_media.py --skip-audio
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VOICE = "fr_FR-siwis-medium"
VOICE_DIR = Path(".voices")

# Small, directly-fetchable chest radiographs used for local development.
XRAY_BASE = "https://huggingface.co/datasets/Rcronshaw/chestxrays/resolve/main"
XRAY_FILES = ("IM-0001-0001.jpeg", "IM-0003-0001.jpeg", "IM-0005-0001.jpeg")

# Written without accents on the vowels Piper mispronounces in isolation; the
# clinical vocabulary is what matters for the demo.
CONSULTATIONS: dict[str, str] = {
    "case-0421": (
        "Patiente adulte, secteur quatre. Elle presente des selles liquides "
        "abondantes depuis hier soir, au moins huit episodes pendant la nuit. "
        "Elle a vomi deux fois ce matin. Elle signale une soif intense. "
        "A l examen, les yeux sont enfonces et le pli cutane est persistant. "
        "Pas de sang visible dans les selles. Pas de fievre mesuree. "
        "Elle puise l eau au puits peu profond au nord du campement."
    ),
    "case-0422": (
        "Patient adulte, secteur quatre. Diarrhee aqueuse d apparition brutale "
        "ce matin, aspect eau de riz. Six episodes jusqu a present. "
        "Il est faible et instable debout. Bouche seche, diurese reduite. "
        "Pas de sang dans les selles, pas de defense abdominale. "
        "Le foyer partage un point d eau avec les abris voisins."
    ),
    "case-0423": (
        "Enfant amene par son tuteur, secteur quatre. Selles liquides toute la "
        "nuit, le tuteur en a compte plus de dix. A vomi apres avoir bu. "
        "Enfant lethargique, boit avidement la solution de rehydratation orale. "
        "Les yeux sont enfonces. Pas d eruption cutanee, pas de toux, "
        "pas de sang dans les selles."
    ),
    "case-0425": (
        "Patient adulte, secteur quatre. Toux productive depuis quatre jours et "
        "essoufflement a l effort. Il rapporte de la fievre et des sueurs "
        "nocturnes. Pas de diarrhee et pas de vomissement. "
        "Radiographie thoracique demandee."
    ),
}

# Which cases get a film. case-0425 is the respiratory decoy, so its film is
# the one that makes the imaging panel meaningful.
FILMS = {"case-0425": 0, "case-0421": 1}


def synth_audio(outdir: Path) -> int:
    try:
        from piper import PiperVoice
    except ImportError:
        print("  piper-tts not installed — skipping audio")
        print("    .venv/bin/pip install piper-tts")
        return 0

    model = VOICE_DIR / f"{VOICE}.onnx"
    if not model.is_file():
        print(f"  downloading voice {VOICE}")
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        import subprocess

        subprocess.run(
            [sys.executable, "-m", "piper.download_voices", VOICE,
             "--data-dir", str(VOICE_DIR)],
            check=True, capture_output=True,
        )

    voice = PiperVoice.load(str(model))
    written = 0
    for case_id, text in CONSULTATIONS.items():
        path = outdir / f"{case_id}.wav"
        with wave.open(str(path), "wb") as handle:
            voice.synthesize_wav(text, handle)
        print(f"  audio  {path.name}  {path.stat().st_size // 1024} KB")
        written += 1
    return written


def fetch_films(outdir: Path) -> int:
    cache = Path("demo_media")
    cache.mkdir(parents=True, exist_ok=True)
    written = 0

    for case_id, index in FILMS.items():
        source = cache / XRAY_FILES[index]
        if not source.is_file():
            url = f"{XRAY_BASE}/{XRAY_FILES[index]}"
            print(f"  fetching {XRAY_FILES[index]}")
            try:
                with urllib.request.urlopen(url, timeout=120) as response:
                    source.write_bytes(response.read())
            except (urllib.error.URLError, TimeoutError) as exc:
                print(f"    FAILED ({exc}) — imaging panel will be empty")
                continue

        target = outdir / f"{case_id}.jpg"
        shutil.copyfile(source, target)
        print(f"  film   {target.name}  {target.stat().st_size // 1024} KB")
        written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default="demo_cases")
    parser.add_argument("--skip-audio", action="store_true")
    parser.add_argument("--skip-films", action="store_true")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    if not outdir.is_dir():
        print(f"{outdir}/ does not exist — run scripts/make_demo_cases.py first")
        return 1

    audio = films = 0
    if not args.skip_audio:
        print("Synthesising French consultation audio (F-02, F-11)")
        audio = synth_audio(outdir)
    if not args.skip_films:
        print("Preparing chest radiographs (F-03)")
        films = fetch_films(outdir)

    print(f"\n{audio} audio file(s), {films} film(s) in {outdir}/")
    if audio or films:
        print("The dashboard will now show transcripts and imaging alongside notes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
