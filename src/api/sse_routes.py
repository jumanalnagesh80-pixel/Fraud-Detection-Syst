"""
Server-Sent Events (SSE) endpoint for live dashboard updates.

Browsers connect to ``/api/stream`` with the standard ``EventSource``
API and receive events as they happen — no polling, sub-second latency.

Event types currently published:
    - transaction.scored : every fraud-engine prediction (api or banking)
    - transaction.alert  : when a high or critical risk alert is raised
    - card.blocked       : when fraud causes the banking layer to block a card
    - banking.payment    : completed banking payment with approve/decline
"""

from __future__ import annotations

import json
import queue
import time
from typing import Iterator

from flask import Blueprint, Response, current_app, stream_with_context

# how long to wait between keep-alive comments when no events flow
KEEPALIVE_SECONDS = 15
# how long a single connection can stay open (browsers auto-reconnect)
MAX_CONNECTION_SECONDS = 30 * 60


def create_sse_blueprint() -> Blueprint:
    bp = Blueprint("sse", __name__, url_prefix="/api")

    @bp.get("/stream")
    def stream():
        """Subscribe to the in-process event bus over SSE."""
        bus = current_app.config.get("EVENT_BUS")
        if bus is None:
            return Response("event bus not configured", status=503)

        sub = bus.subscribe()

        @stream_with_context
        def generate() -> Iterator[str]:
            # initial hello so the client knows the stream is open
            yield _format_event("connected", {"subscribers": bus.subscriber_count})
            started = time.time()
            try:
                while True:
                    if time.time() - started > MAX_CONNECTION_SECONDS:
                        # close cleanly so the browser reconnects on a fresh stream
                        return
                    try:
                        encoded = sub.get(timeout=KEEPALIVE_SECONDS)
                    except queue.Empty:
                        # SSE comment line keeps the connection alive through proxies
                        yield ": keep-alive\n\n"
                        continue

                    try:
                        message = json.loads(encoded)
                    except (TypeError, ValueError):
                        continue
                    yield _format_event(message.get("type", "message"), message)
            finally:
                bus.unsubscribe(sub)

        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        }
        return Response(generate(), headers=headers)

    return bp


def _format_event(event_type: str, payload: dict) -> str:
    """Format a single SSE message: ``event:`` + ``data:`` + blank line."""
    data = json.dumps(payload, default=str)
    return f"event: {event_type}\ndata: {data}\n\n"
