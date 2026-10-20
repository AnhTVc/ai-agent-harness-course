"""Execution-control contracts: stepping must gate actual provider/tool calls."""

import threading
import time
import unittest
from unittest.mock import patch
from agent_lab.runtime import Execution
from agent_lab.debugger import DebugSession, SessionStore, Conflict


def reach(execution, kind):
    """Advance prepared boundaries without executing the named next action."""
    for _ in range(100):
        if execution.next_action and execution.next_action["kind"] == kind:
            return
        if execution.done:
            break
        execution.step()
    raise AssertionError("Boundary not reached: " + kind)


def settle(session):
    """Bound the wait for a background debugger command in deterministic tests."""
    for _ in range(300):
        snap = session.snapshot()
        if snap["debug_status"] != "running":
            return snap
        time.sleep(0.005)
    raise AssertionError("Debugger did not settle")


class ExecutionTests(unittest.TestCase):
    """Prove that unstepped actions have not already happened in the background."""

    def test_create_executes_nothing(self):
        with patch("agent_lab.runtime.execute") as tool, patch(
            "agent_lab.runtime.OfflineModel.complete"
        ) as model:
            execution = Execution("Find company capabilities")
            self.assertEqual(execution.result["messages"], [])
            self.assertEqual(execution.result["events"], [])
            tool.assert_not_called()
            model.assert_not_called()

    def test_step_stops_before_tool_and_allows_query_override(self):
        execution = Execution("Find company capabilities")
        reach(execution, "execute_tool")
        self.assertEqual(execution.result["tool_calls"], 0)
        self.assertEqual(execution.result["events"][-1]["kind"], "tool_request")
        execution.override_query("evaluation")
        execution.step()
        result = execution.result["events"][-1]
        self.assertEqual(result["kind"], "tool_result")
        self.assertEqual(result["payload"]["matches"][0]["id"], "DOC-004")
        self.assertEqual(execution.result["tool_calls"], 1)
        self.assertFalse(any(m["role"] == "tool" for m in execution.result["messages"]))
        execution.step()
        self.assertEqual(execution.result["messages"][-1]["role"], "tool")
        self.assertIn("DOC-004", execution.result["messages"][-1]["content"])

    def test_weather_tool_can_be_edited_at_the_real_execution_boundary(self):
        execution = Execution("What is the current weather in Hanoi, Vietnam?")
        reach(execution, "execute_tool")
        self.assertEqual(execution.pending["name"], "search_weather")
        self.assertEqual(execution.result["tool_calls"], 0)
        with patch(
            "agent_lab.runtime.execute",
            return_value={"tool": "search_weather", "source": "Open-Meteo"},
        ) as tool:
            execution.override_tool_argument("location", "Oslo, Norway")
            execution.step()
        tool.assert_called_once_with("search_weather", {"location": "Oslo, Norway"})
        result = next(
            event
            for event in execution.result["events"]
            if event["kind"] == "tool_result"
        )
        self.assertEqual(result["source"]["file"], "tools.py")
        self.assertEqual(result["source"]["symbol"], "_search_weather")
        override = next(
            event
            for event in execution.result["events"]
            if event["kind"] == "debug_override"
        )
        self.assertEqual(
            override["payload"]["original"], {"location": "Hanoi, Vietnam"}
        )
        self.assertEqual(
            override["payload"]["replacement"], {"location": "Oslo, Norway"}
        )

    def test_calculation_argument_can_be_changed_before_execution(self):
        execution = Execution("Calculate 2 * 4")
        reach(execution, "execute_tool")
        self.assertEqual(execution.pending["name"], "calculate")
        with patch(
            "agent_lab.runtime.execute",
            return_value={"tool": "calculate", "result": 18},
        ) as tool:
            execution.override_tool_argument("expression", "3 * 6")
            execution.step()
        tool.assert_called_once_with("calculate", {"expression": "3 * 6"})

    def test_debug_argument_override_rejects_mismatched_tool_fields(self):
        execution = Execution("What is the current weather in Hanoi, Vietnam?")
        reach(execution, "execute_tool")
        for argument, value in (
            ("query", "weather"),
            ("url", "https://example.com"),
            ("location", ""),
        ):
            with self.subTest(argument=argument), self.assertRaises(ValueError):
                execution.override_tool_argument(argument, value)

    def test_event_context_snapshots_are_immutable(self):
        execution = Execution("Find company capabilities")
        reach(execution, "execute_tool")
        model_event = next(
            e for e in execution.result["events"] if e["kind"] == "model_response"
        )
        before = str(model_event)
        execution.override_query("evaluation")
        while not execution.done:
            execution.step()
        self.assertEqual(str(model_event), before)
        self.assertIn("state_before", model_event)
        self.assertIn("state_after", model_event)
        self.assertGreater(model_event["source"]["line"], 0)

    def test_override_is_only_allowed_at_the_tool_boundary(self):
        execution = Execution("Find company capabilities")
        with self.assertRaises(ValueError):
            execution.override_query("evaluation")
        reach(execution, "execute_tool")
        for query in ("", 42, "x" * 2001):
            with self.assertRaises(ValueError):
                execution.override_query(query)

    def test_cancel_preserves_evidence_without_executing_pending_tool(self):
        execution = Execution("Find company capabilities")
        reach(execution, "execute_tool")
        execution.cancel()
        self.assertEqual(execution.result["status"], "cancelled")
        self.assertEqual(execution.result["tool_calls"], 0)
        count = len(execution.result["events"])
        execution.step()
        self.assertEqual(len(execution.result["events"]), count)


class SessionTests(unittest.TestCase):
    """Check live control, breakpoints, safe pause, and isolated in-memory runs."""

    def test_continue_hits_breakpoint_before_actual_tool(self):
        session = DebugSession(
            {"prompt": "Find company capabilities"}, ["execute_tool"], 0
        )
        session.command("continue", 0)
        snap = settle(session)
        self.assertEqual(snap["debug_status"], "paused")
        self.assertEqual(snap["breakpoint_hit"], "execute_tool")
        self.assertEqual(snap["result"]["tool_calls"], 0)
        session.override("evaluation", snap["revision"])
        snap = session.snapshot()
        session.command("continue", snap["revision"])
        snap = settle(session)
        self.assertEqual(snap["debug_status"], "completed")
        self.assertIn("DOC-004", snap["result"]["answer"])

    def test_single_step_and_stale_revision_rejection(self):
        session = DebugSession({"prompt": "Hello"}, [], 0)
        session.command("step", 0)
        snap = settle(session)
        self.assertEqual(len(snap["result"]["events"]), 1)
        self.assertEqual(snap["debug_status"], "paused")
        with self.assertRaises(Conflict):
            session.command("step", 0)

    def test_pause_waits_for_inflight_provider_and_blocks_next_action(self):
        entered, release = threading.Event(), threading.Event()

        def slow_complete(*_args):
            entered.set()
            self.assertTrue(release.wait(2))
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "search_documents",
                            "arguments": {"query": "company"},
                        }
                    }
                ],
            }

        with patch(
            "agent_lab.runtime.OfflineModel.complete", side_effect=slow_complete
        ):
            session = DebugSession({"prompt": "Company"}, [], 0)
            session.command("continue", 0)
            self.assertTrue(entered.wait(2))
            snap = session.snapshot()
            self.assertEqual(snap["active_action"]["kind"], "call_model")
            session.command("pause")
            with self.assertRaises(Conflict):
                session.command("step", session.snapshot()["revision"])
            release.set()
            snap = settle(session)
        self.assertEqual(snap["debug_status"], "paused")
        self.assertEqual(snap["result"]["tool_calls"], 0)
        self.assertEqual(snap["next_action"]["kind"], "tool_request")

    def test_stop_during_provider_does_not_dispatch_requested_tool(self):
        entered, release = threading.Event(), threading.Event()

        def slow_complete(*_args):
            entered.set()
            self.assertTrue(release.wait(2))
            return {"role": "assistant", "content": "Late provider response"}

        with patch(
            "agent_lab.runtime.OfflineModel.complete", side_effect=slow_complete
        ):
            session = DebugSession({"prompt": "Company"}, [], 0)
            session.command("continue", 0)
            self.assertTrue(entered.wait(2))
            session.command("stop")
            release.set()
            snap = settle(session)
        self.assertEqual(snap["debug_status"], "cancelled")
        self.assertEqual(snap["result"]["tool_calls"], 0)

    def test_sessions_are_isolated_and_controls_validated(self):
        store = SessionStore()
        a = store.create({"prompt": "Company"}, [], 0)
        b = store.create({"prompt": "Hello"}, [], 0)
        self.assertNotEqual(a.id, b.id)
        a.command("step", 0)
        settle(a)
        self.assertEqual(store.get(b.id).snapshot()["result"]["events"], [])
        for breakpoints, delay in [
            (["shell"], 0),
            ("execute_tool", 0),
            ([], -1),
            ([], True),
        ]:
            with self.assertRaises(ValueError):
                store.create({"prompt": "Hello"}, breakpoints, delay)
        with self.assertRaises(KeyError):
            store.get("missing")
        with self.assertRaises(ValueError):
            b.command("unknown", 0)
