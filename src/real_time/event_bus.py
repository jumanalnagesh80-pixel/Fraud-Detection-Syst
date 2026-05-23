"""
In-process pub/sub event bus for live dashboard updates.

Producers (the API and banking routes) call ``publish``. Consumers (the
SSE endpoint) call ``subscribe`` to get a thread-safe ``Queue`` they can
drain. Each subscriber gets its own queue, so slow clients don't block
others or the producer.

This is intentionally simple — single-process. For multi-worker
deployments, swap this for Redis Pub/Sub or NATS without changing the
public ``publish``/``subscribe`` API.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


log = logging.getLogger(__name__)


class EventBus:
    """Thread-safe broadcast bus with a queue per subscriber."""

    def __init__(self, max_queue_size: int = 200) -> None:
        self._subscribers: List[queue.Queue] = []
        self._lock = threading.Lock()
        self._max_queue_size = max_queue_size

    def subscribe(self) -> queue.Queue:
        """Register a new subscriber and return its queue."""
        q: queue.Queue = queue.Queue(maxsize=self._max_queue_size)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def publish(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """Broadcast an event to every subscriber.

        ``event_type`` becomes the SSE ``event:`` field. ``payload`` is
        JSON-encoded into the ``data:`` field.
        """
        message = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": payload or {},
        }
        try:
            encoded = json.dumps(message, default=str)
        except (TypeError, ValueError) as e:
            log.warning("Failed to serialize event %s: %s", event_type, e)
            return

        with self._lock:
            dead: List[queue.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(encoded)
                except queue.Full:
                    # subscriber is too slow — drop it so we don't pile up memory
                    dead.append(q)
            for q in dead:
                try:
                    self._subscribers.remove(q)
                except ValueError:
                    pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)
