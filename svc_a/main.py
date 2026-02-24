import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, FastAPI, Query

app = FastAPI(title="Service A")
INSTANCE = os.getenv("HOSTNAME", "svc_a")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/hello")
async def hello(clientId: int = Query(...), traceId: str | None = Query(default=None)):
    return {
        "service": "A",
        "clientId": clientId,
        "traceId": traceId,
        "message": "Hello from service A",
        "instance": INSTANCE,
        "timestamp": now_iso(),
    }


@app.post("/echo")
async def echo(
    clientId: int = Query(...),
    traceId: str | None = Query(default=None),
    payload: dict[str, Any] = Body(...),
):
    return {
        "service": "A",
        "clientId": clientId,
        "traceId": traceId,
        "echo": payload,
        "message": "Echo from service A",
        "timestamp": now_iso(),
    }
