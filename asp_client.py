"""Minimal, thread-safe ASP v0.1 client (Python standard library only).

One AspClient sends events for one agentId on behalf of one source
("self", "guardrail", "operator", ...). The reference status server orders
events per agent and per source, so each (agentId, source) pair keeps its own
seq counter.
"""

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ASP_VERSION = "0.1"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AspClient:
    def __init__(self, server, agent_id, token=None, source="self", seq_start=0, verbose=False):
        self.server = server.rstrip("/")
        self.agent_id = agent_id
        self.token = token
        self.source = source
        self.seq = seq_start
        self.verbose = verbose
        self._lock = threading.Lock()

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def send(self, event_type, **fields):
        """Send one event. Returns the HTTP status, or None if the server is unreachable.

        Never raises: losing the status server must not break the agent.
        """
        # The lock covers the HTTP call too: events must reach the server in seq
        # order, otherwise the server drops the late ones as out-of-order.
        with self._lock:
            self.seq += 1
            event = {
                "aspVersion": ASP_VERSION,
                "type": event_type,
                "agentId": self.agent_id,
                "eventId": str(uuid.uuid4()),
                "seq": self.seq,
                "ts": now_iso(),
                **fields,
            }
            if self.source != "self":
                event["source"] = self.source
            request = Request(f"{self.server}/v1/events", data=json.dumps(event).encode(),
                              headers=self._headers(), method="POST")
            try:
                with urlopen(request, timeout=3) as response:
                    if self.verbose:
                        label = " ".join(str(fields.get(k, "")) for k in ("dimension", "to")).strip()
                        print(f"  [asp] {self.source}:{event_type} {label} -> {response.status}")
                    return response.status
            except HTTPError as err:
                print(f"  [asp] server rejected {event_type}: {err.code} {err.read().decode()}")
                return err.code
            except (URLError, TimeoutError, OSError) as err:
                if self.verbose:
                    print(f"  [asp] status server not reachable: {err}")
                return None

    def state_change(self, dimension, from_state, to_state, reason=None, **extra):
        fields = {"dimension": dimension, "from": from_state, "to": to_state, **extra}
        if reason:
            fields["reason"] = reason[:256]
        return self.send("state_change", **fields)

    def snapshot(self):
        """Return the server's current view of this agent, or None."""
        url = f"{self.server}/v1/agents/{quote(self.agent_id, safe=':')}"
        try:
            with urlopen(Request(url, headers=self._headers()), timeout=2) as response:
                return json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None


def unique_seq_start():
    """Seq start for short-lived senders (e.g. a one-shot operator CLI), higher than any earlier run."""
    return int(time.time() * 1000)
