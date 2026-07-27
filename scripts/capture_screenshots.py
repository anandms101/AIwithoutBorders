#!/usr/bin/env python
"""Capture the README screenshots from a live run.

The images in `docs/public/` are evidence, so they must come from the running
system rather than a mockup. This script drives a headless Chromium through the
same states a judge sees.

Requires the demo to be running with an alert pending:

    make demo
    make drop            # wait ~2 min for ASR, or use --notes-only
    .venv/bin/python scripts/capture_screenshots.py

It approves the pending alert to capture the post-egress state, so run it on a
demo instance rather than one you are about to present from — or just re-run
`make demo` afterwards.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT = Path("docs/public")


def approve_pending(web: str) -> bool:
    from outpost.db import connect

    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM alerts WHERE status = 'pending' LIMIT 1"
        ).fetchone()
    if row is None:
        return False

    request = urllib.request.Request(
        f"{web}/alerts/{row['id']}/approve", method="POST"
    )
    try:
        urllib.request.urlopen(request, timeout=30)
    except Exception:
        # A 303 redirect to a page we don't follow still counts as success.
        pass
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", default="http://127.0.0.1:8081")
    parser.add_argument("--receiver", default="http://127.0.0.1:9000")
    parser.add_argument("--case", default="case-0421")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed. Run:", file=sys.stderr)
        print("  uv pip install playwright && .venv/bin/playwright install chromium",
              file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def shot(url: str, path: Path, *, width: int, height: int,
                 full: bool = True, clip: dict | None = None,
                 settle: int = 3000) -> None:
            page = browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=2
            )
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(settle)
            if clip:
                page.screenshot(path=str(path), clip=clip)
            else:
                page.screenshot(path=str(path), full_page=full)
            page.close()
            print(f"  {path}  ({path.stat().st_size // 1024} KB)")

        print("Capturing pending-alert state")
        shot(f"{args.web}/", OUT / "dashboard.png", width=1600, height=1200)
        shot(f"{args.web}/case/{args.case}", OUT / "case-detail.png",
             width=1600, height=1100)

        print("Approving the pending alert")
        if not approve_pending(args.web):
            print("  no pending alert — post-egress shots will show zeros")

        print("Capturing post-egress state")
        shot(f"{args.web}/", OUT / "approved.png", width=1600, height=900,
             clip={"x": 0, "y": 0, "width": 1600, "height": 700})
        shot(f"{args.receiver}/reports", OUT / "receiver.png",
             width=1200, height=160, settle=1200,
             clip={"x": 0, "y": 0, "width": 1200, "height": 110})

        browser.close()

    print("\nDone. Re-run `make demo` to reset the alert state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
