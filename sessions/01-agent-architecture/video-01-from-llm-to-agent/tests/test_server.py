"""HTTP integration tests exercise actual loopback requests and source bounds."""

import http.client
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from agent_lab.server import Handler, LabServer
from agent_lab.tools import TOOL_SCHEMA


class ServerTests(unittest.TestCase):
    """Use an ephemeral local port; leave no server or trace files behind."""

    @classmethod
    def setUpClass(cls):
        cls.server = LabServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, body=None, headers=None):
        """Return decoded JSON or asset text through the real HTTP stack."""
        conn = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        payload = response.read().decode()
        result = (
            response.status,
            (
                json.loads(payload)
                if response.headers["Content-Type"].startswith("application/json")
                else payload
            ),
            response.headers,
        )
        conn.close()
        return result

    def test_assets_catalog_and_source(self):
        for path in (
            "/",
            "/app.js",
            "/style.css",
            "/api/catalog",
            "/api/source?file=runtime.py",
            "/api/source?file=network.py",
        ):
            with self.subTest(path=path):
                status, data, headers = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
                self.assertTrue(data)
        self.assertIn(
            "def run", self.request("GET", "/api/source?file=runtime.py")[1]["source"]
        )
        self.assertIn(
            "def verified_https_context",
            self.request("GET", "/api/source?file=network.py")[1]["source"],
        )
        catalog = self.request("GET", "/api/catalog")[1]
        self.assertEqual(
            {tool["function"]["name"] for tool in catalog["tools"]},
            {"search_documents", "search_weather", "calculate"},
        )
        self.assertEqual(set(catalog["mode_views"]), {"agent", "workflow", "chatbot"})
        self.assertIn(
            "runtime-executor", {edge["id"] for edge in catalog["mode_edges"]}
        )

    def test_cannot_read_arbitrary_files(self):
        for path in ("/api/source?file=../../etc/passwd", "/run.py", "/missing"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_origin_and_host_checks(self):
        self.assertEqual(
            self.request("GET", "/", headers={"Host": "evil.example"})[0], 403
        )
        self.assertEqual(
            self.request("POST", "/api/run", "{}", {"Origin": "http://evil.example"})[
                0
            ],
            403,
        )
        port = self.server.server_port
        self.assertEqual(
            self.request(
                "GET", "/api/catalog", headers={"Origin": f"http://127.0.0.1:{port}"}
            )[0],
            200,
        )

    def test_post_run_and_checker(self):
        status, data, _ = self.request(
            "POST",
            "/api/run",
            json.dumps({"prompt": "Find company capabilities"}),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertIn("DOC-001", data["answer"])
        for schema, passed in ((TOOL_SCHEMA, True), ({}, False)):
            status, data, _ = self.request(
                "POST",
                "/api/check-schema",
                json.dumps({"schema": schema}),
                {"Content-Type": "application/json"},
            )
            self.assertEqual(data["passed"], passed)

    def test_debug_http_controls_gate_real_tool_execution(self):
        headers = {"Content-Type": "application/json"}
        status, snapshot, _ = self.request(
            "POST",
            "/api/debug/create",
            json.dumps(
                {
                    "prompt": "Company capabilities",
                    "breakpoints": ["execute_tool"],
                    "delay_ms": 0,
                }
            ),
            headers,
        )
        self.assertEqual(status, 201)
        self.assertEqual(snapshot["result"]["events"], [])
        session_id = snapshot["session_id"]
        status, _, _ = self.request(
            "POST",
            "/api/debug/control",
            json.dumps(
                {
                    "session_id": session_id,
                    "action": "continue",
                    "revision": snapshot["revision"],
                }
            ),
            headers,
        )
        self.assertEqual(status, 200)
        for _ in range(100):
            status, snapshot, _ = self.request(
                "GET", "/api/debug/session?id=" + session_id
            )
            if snapshot["debug_status"] != "running":
                break
            time.sleep(0.005)
        self.assertEqual(snapshot["breakpoint_hit"], "execute_tool")
        self.assertEqual(snapshot["result"]["tool_calls"], 0)
        status, snapshot, _ = self.request(
            "POST",
            "/api/debug/query",
            json.dumps(
                {
                    "session_id": session_id,
                    "query": "evaluation",
                    "revision": snapshot["revision"],
                }
            ),
            headers,
        )
        self.assertEqual(status, 200)
        status, _, _ = self.request(
            "POST",
            "/api/debug/control",
            json.dumps({"session_id": session_id, "action": "step", "revision": 0}),
            headers,
        )
        self.assertEqual(status, 409)
        self.assertEqual(self.request("GET", "/api/debug/session?id=missing")[0], 404)
        self.assertEqual(
            self.request(
                "POST",
                "/api/debug/create",
                '{"prompt":"x","breakpoints":["shell"]}',
                headers,
            )[0],
            400,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/api/debug/control",
                '{"session_id":"missing","action":"step"}',
                headers,
            )[0],
            404,
        )

    def test_debug_http_edits_a_declared_weather_argument_before_execution(self):
        headers = {"Content-Type": "application/json"}
        status, snapshot, _ = self.request(
            "POST",
            "/api/debug/create",
            json.dumps(
                {
                    "prompt": "What is the current weather in Hanoi, Vietnam?",
                    "breakpoints": ["execute_tool"],
                    "delay_ms": 0,
                }
            ),
            headers,
        )
        self.assertEqual(status, 201)
        session_id = snapshot["session_id"]
        self.request(
            "POST",
            "/api/debug/control",
            json.dumps(
                {
                    "session_id": session_id,
                    "action": "continue",
                    "revision": snapshot["revision"],
                }
            ),
            headers,
        )
        for _ in range(100):
            _, snapshot, _ = self.request("GET", "/api/debug/session?id=" + session_id)
            if snapshot["debug_status"] != "running":
                break
            time.sleep(0.005)
        self.assertEqual(snapshot["next_action"]["tool"]["name"], "search_weather")
        self.assertEqual(snapshot["result"]["tool_calls"], 0)
        status, changed, _ = self.request(
            "POST",
            "/api/debug/argument",
            json.dumps(
                {
                    "session_id": session_id,
                    "revision": snapshot["revision"],
                    "argument": "location",
                    "value": "Oslo, Norway",
                }
            ),
            headers,
        )
        self.assertEqual(status, 200)
        event = changed["result"]["events"][-1]
        self.assertEqual(event["kind"], "debug_override")
        self.assertEqual(
            changed["next_action"]["tool"]["arguments"], {"location": "Oslo, Norway"}
        )
        self.assertEqual(changed["result"]["tool_calls"], 0)

    def test_bad_json_and_request_bounds(self):
        headers = {"Content-Type": "application/json"}
        for payload in (
            "not-json",
            "[]",
            "{}",
            '{"prompt":""}',
            '{"prompt":"x","extra":1}',
        ):
            self.assertEqual(self.request("POST", "/api/run", payload, headers)[0], 400)
        self.assertEqual(
            self.request("POST", "/api/run", "{}", {"Content-Type": "text/plain"})[0],
            415,
        )
        self.assertEqual(self.request("POST", "/missing", "{}", headers)[0], 404)
        self.assertEqual(self.request("POST", "/api/run", " " * 17000, headers)[0], 413)
        self.assertEqual(self.request("POST", "/api/run", b"", headers)[0], 413)


if __name__ == "__main__":
    unittest.main()
