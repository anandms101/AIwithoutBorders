"""The single allowlisted egress receiver.

Runs **off-box** (Q4: a teammate's laptop is more convincing on camera than a
second local port). It exists to prove what leaves: it logs every payload with
its byte count and refuses anything that looks like patient data.

    python -m mock_receiver

The refusal path matters more than the accept path. If Outpost ever regressed
and sent an identifier, this would reject it loudly rather than quietly accept.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

MAX_BYTES = 1024
ALLOWED_FIELDS = {
    "syndrome",
    "catchment",
    "count",
    "window_hours",
    "trend",
    "site_id",
}

app = FastAPI(title="Outpost mock receiver")
received: list[dict] = []


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "received": len(received)}


@app.get("/reports")
def reports() -> dict:
    return {"count": len(received), "reports": received}


@app.post("/report")
async def report(request: Request) -> JSONResponse:
    raw = await request.body()
    size = len(raw)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")

    if size > MAX_BYTES:
        print(f"[receiver] {stamp} REJECTED — {size} bytes exceeds {MAX_BYTES}")
        return JSONResponse(
            {"error": f"payload too large: {size} > {MAX_BYTES}"}, status_code=413
        )

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[receiver] {stamp} REJECTED — not JSON")
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    extra = set(payload) - ALLOWED_FIELDS
    if extra:
        # This is the interesting branch: it is the receiver refusing to accept
        # anything that was not agreed in the contract.
        print(f"[receiver] {stamp} REJECTED — unexpected fields: {sorted(extra)}")
        return JSONResponse(
            {"error": f"unexpected fields: {sorted(extra)}"}, status_code=422
        )

    entry = {"received_at": stamp, "bytes": size, "payload": payload}
    received.append(entry)

    print(
        f"[receiver] {stamp} ACCEPTED {size} bytes — "
        f"{payload.get('count')} cases of {payload.get('syndrome')} "
        f"in {payload.get('catchment')} ({payload.get('trend')})"
    )
    return JSONResponse({"status": "accepted", "bytes": size})


def main() -> None:
    import uvicorn

    print("[receiver] listening on 0.0.0.0:9000 — POST /report")
    print(f"[receiver] accepts only: {sorted(ALLOWED_FIELDS)}")
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="warning")


if __name__ == "__main__":
    main()
