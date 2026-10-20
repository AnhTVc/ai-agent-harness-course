"""In-memory debugger control around the lesson's actual execution engine.

The worker advances the engine only on Step or Continue. Pause/Stop are
cooperative: an in-flight model call is allowed to finish, then no subsequent
boundary runs. Published snapshots remain available during slow provider I/O.
"""

import copy
import threading
import time
import uuid
from .runtime import Execution

BREAKPOINTS = {"call_model", "execute_tool", "observation"}


class Conflict(ValueError):
    """A stale or concurrent control command cannot advance the run twice."""


class DebugSession:
    """Own one paused engine, one worker at a time, and immutable publications."""

    def __init__(self, config, breakpoints=None, delay_ms=350):
        """Create a paused session; construction executes no model or tool work."""
        if not isinstance(breakpoints, list) or any(
            not isinstance(item, str) or item not in BREAKPOINTS for item in breakpoints
        ):
            raise ValueError("Unknown breakpoint list.")
        if type(delay_ms) is not int or not 0 <= delay_ms <= 2000:
            raise ValueError("Delay must be an integer from 0 to 2000 milliseconds.")
        self.config = copy.deepcopy(config)
        self.engine = Execution(**config)
        self.id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.breakpoints, self.delay_ms = set(breakpoints), delay_ms
        self.revision, self.debug_status = 0, "paused"
        self.breakpoint_hit, self.active_action = None, None
        self.pause_requested = self.stop_requested = False
        self.updated_at = time.monotonic()
        self._publish()

    def _publish(self):
        """Store detached evidence so polling never races an in-flight engine."""
        self.published_result = copy.deepcopy(self.engine.result)
        self.published_next = copy.deepcopy(self.engine.next_action)
        self.updated_at = time.monotonic()

    def snapshot(self):
        """Read the latest publication without waiting for provider I/O."""
        with self.lock:
            return copy.deepcopy(
                {
                    "session_id": self.id,
                    "revision": self.revision,
                    "debug_status": self.debug_status,
                    "breakpoint_hit": self.breakpoint_hit,
                    "active_action": self.active_action,
                    "next_action": self.published_next,
                    "pause_requested": self.pause_requested,
                    "stop_requested": self.stop_requested,
                    "breakpoints": sorted(self.breakpoints),
                    "delay_ms": self.delay_ms,
                    "result": self.published_result,
                    "config": self.config,
                }
            )

    def command(self, action, revision=None):
        """Atomically accept a control request and launch at most one worker."""
        if action not in ("step", "continue", "pause", "stop"):
            raise ValueError("Unknown debugger action.")
        with self.lock:
            if action in ("pause", "stop"):
                if self.debug_status == "running":
                    self.pause_requested = True
                    self.stop_requested = action == "stop" or self.stop_requested
                    self.wake.set()
                elif action == "stop" and not self.engine.done:
                    self.engine.cancel()
                    self.debug_status = "cancelled"
                    self._publish()
                self.revision += 1
                return self.snapshot()
            if self.debug_status == "running":
                raise Conflict(
                    "A boundary is already running. Wait, pause, or stop it."
                )
            if type(revision) is not int or revision != self.revision:
                raise Conflict("Stale revision. Refresh the run before advancing it.")
            if self.engine.done:
                raise Conflict(
                    "This run has stopped. Create a new run to execute again."
                )
            self.debug_status = "running"
            self.pause_requested = self.stop_requested = False
            self.active_action = None
            self.wake.clear()
            self.revision += 1
            # Continue from an already-hit breakpoint authorizes that boundary.
            skip_initial_breakpoint = (
                self.breakpoint_hit is not None or action == "step"
            )
            self.breakpoint_hit = None
            threading.Thread(
                target=self._work, args=(action, skip_initial_breakpoint), daemon=True
            ).start()
            return self.snapshot()

    def _work(self, action, skip_initial_breakpoint):
        """Advance real boundaries, publishing before and after each operation."""
        count = 0
        try:
            while True:
                with self.lock:
                    if self.stop_requested:
                        self.engine.cancel()
                    if self.engine.done:
                        self.debug_status = (
                            "cancelled"
                            if self.engine.result["status"] == "cancelled"
                            else "completed"
                        )
                        break
                    if self.pause_requested or (action == "step" and count):
                        self.debug_status = "paused"
                        break
                    next_action = self.engine.next_action
                    if (
                        action == "continue"
                        and next_action["kind"] in self.breakpoints
                        and not (count == 0 and skip_initial_breakpoint)
                    ):
                        self.breakpoint_hit = next_action["kind"]
                        self.debug_status = "paused"
                        break
                    self.active_action = next_action
                    self.revision += 1
                # Do not hold the control lock during provider I/O. Pause and
                # Stop can be accepted while the current boundary is executing.
                self.engine.step()
                count += 1
                with self.lock:
                    self.active_action = None
                    self._publish()
                    self.revision += 1
                if action == "continue" and self.delay_ms:
                    self.wake.wait(self.delay_ms / 1000)
        except Exception as exc:
            # Preserve evidence and expose the failure category, never a hidden
            # success. Raw exception text may contain private provider payloads.
            with self.lock:
                self.engine.cancel()
                self.debug_status = "error"
                self.engine.result["debugger_error"] = type(exc).__name__
        finally:
            with self.lock:
                self.active_action = None
                self._publish()
                self.revision += 1

    def override_argument(self, argument, value, revision):
        """Edit only the pending tool's declared input while paused."""
        with self.lock:
            if (
                self.debug_status != "paused"
                or type(revision) is not int
                or revision != self.revision
            ):
                raise Conflict("Pause and refresh before editing pending arguments.")
            self.engine.override_tool_argument(argument, value)
            self._publish()
            self.revision += 1
            return self.snapshot()

    def override(self, query, revision):
        """Keep the original query-edit command available to older examples."""
        return self.override_argument("query", query, revision)

    def configure(self, breakpoints, revision):
        """Change breakpoints only at a stable paused boundary."""
        if not isinstance(breakpoints, list) or any(
            not isinstance(item, str) or item not in BREAKPOINTS for item in breakpoints
        ):
            raise ValueError("Unknown breakpoint list.")
        with self.lock:
            if (
                self.debug_status == "running"
                or type(revision) is not int
                or revision != self.revision
            ):
                raise Conflict("Pause and refresh before changing breakpoints.")
            self.breakpoints = set(breakpoints)
            self.revision += 1
            return self.snapshot()


class SessionStore:
    """Bound local session retention; do not add persistent agent memory."""

    def __init__(self):
        """Store runs in process memory and isolate access with one small lock."""
        self.sessions = {}
        self.lock = threading.Lock()

    def create(self, config, breakpoints=None, delay_ms=350):
        """Expire inactive runs and reject overload rather than evict a live run."""
        session = DebugSession(
            config, [] if breakpoints is None else breakpoints, delay_ms
        )
        with self.lock:
            cutoff = time.monotonic() - 3600
            self.sessions = {
                key: value
                for key, value in self.sessions.items()
                if value.updated_at > cutoff or value.debug_status == "running"
            }
            if len(self.sessions) >= 32:
                raise Conflict(
                    "Session capacity reached. Restart the local server to clear retained runs."
                )
            self.sessions[session.id] = session
        return session

    def get(self, session_id):
        """Look up one opaque session ID; it is never interpreted as a path."""
        with self.lock:
            if not isinstance(session_id, str) or session_id not in self.sessions:
                raise KeyError("Unknown debug session.")
            return self.sessions[session_id]
