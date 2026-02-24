import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, FastAPI, Query

app = FastAPI(title="Service C")
INSTANCE = os.getenv("HOSTNAME", "svc_c")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/hello")
async def hello(clientId: int = Query(...), traceId: str | None = Query(default=None)):
    return {
        "service": "C",
        "clientId": clientId,
        "traceId": traceId,
        "message": "Hello from service C",
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
        "service": "C",
        "clientId": clientId,
        "traceId": traceId,
        "echo": payload,
        "message": "Echo from service C",
        "timestamp": now_iso(),
    }
