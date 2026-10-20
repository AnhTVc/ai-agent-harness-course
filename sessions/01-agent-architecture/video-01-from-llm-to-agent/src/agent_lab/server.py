"""Local-only HTTP gateway for the course lab.

Static assets and source inspection use explicit allowlists. JSON requests are
size-bounded; foreign browser origins and Host headers are rejected. No data is
persisted and no remote deployment is implied by this teaching server.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .architecture import NODES, EDGES, MODE_EDGES, MODE_VIEWS
from .runtime import run
from .debugger import SessionStore, Conflict
from .tools import TOOL_SCHEMA, TOOL_SCHEMAS, DOCUMENTS, check_schema

WEB = Path(__file__).resolve().parent.parent / "web"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
}
SOURCES = {
    name: Path(__file__).parent / name
    for name in (
        "runtime.py",
        "providers.py",
        "config.py",
        "network.py",
        "tools.py",
        "architecture.py",
        "server.py",
        "debugger.py",
    )
}


class LabServer(ThreadingHTTPServer):
    """Keep debugger runs scoped to one local server process."""

    def __init__(self, address, handler):
        """Give each server an independent, bounded session store."""
        super().__init__(address, handler)
        self.sessions = SessionStore()


class Handler(BaseHTTPRequestHandler):
    """Serve the UI and bounded JSON API on loopback only."""

    def log_message(self, *_args):
        """Avoid logging prompts or source payloads in the terminal."""

    def send(self, status, data, content_type="application/json"):
        """Use one response path so errors retain the same security headers."""
        body = json.dumps(data).encode() if content_type == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def trusted(self):
        """Prevent browser cross-origin calls and DNS-rebinding Host headers."""
        port = self.server.server_port
        allowed = {f"localhost:{port}", f"127.0.0.1:{port}"}
        origin = self.headers.get("Origin")
        if self.headers.get("Host") not in allowed or (
            origin and origin not in {f"http://{host}" for host in allowed}
        ):
            self.send(403, {"error": "Only same-origin loopback access is allowed."})
            return False
        return True

    def do_GET(self):
        """Read catalog, actual allowlisted source, or the prepared UI."""
        if not self.trusted():
            return
        parsed = urlparse(self.path)
        if parsed.path in ASSETS:
            name, mime = ASSETS[parsed.path]
            return self.send(200, (WEB / name).read_bytes(), mime)
        if parsed.path == "/api/catalog":
            return self.send(
                200,
                {
                    "nodes": NODES,
                    "edges": EDGES,
                    "mode_edges": MODE_EDGES,
                    "mode_views": MODE_VIEWS,
                    "schema": TOOL_SCHEMA,
                    "tools": TOOL_SCHEMAS,
                    "documents": DOCUMENTS,
                },
            )
        if parsed.path == "/api/debug/session":
            session_id = parse_qs(parsed.query).get("id", [""])[0]
            try:
                return self.send(200, self.server.sessions.get(session_id).snapshot())
            except KeyError:
                return self.send(
                    404, {"error": "Debug session not found. Create a new run."}
                )
        if parsed.path == "/api/source":
            name = parse_qs(parsed.query).get("file", [""])[0]
            if name in SOURCES:
                return self.send(
                    200, {"file": name, "source": SOURCES[name].read_text()}
                )
        self.send(404, {"error": "Resource not found."})

    def do_POST(self):
        """Execute a run or validate the lesson's schema exercise."""
        if not self.trusted():
            return
        if self.path not in (
            "/api/run",
            "/api/check-schema",
            "/api/debug/create",
            "/api/debug/control",
            "/api/debug/query",
            "/api/debug/argument",
            "/api/debug/breakpoints",
        ):
            return self.send(404, {"error": "Resource not found."})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send(415, {"error": "Use application/json."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                return self.send(
                    413, {"error": "JSON body must contain 1 to 16384 bytes."}
                )
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object.")
            if self.path == "/api/debug/create":
                if set(data) - {
                    "prompt",
                    "mode",
                    "provider",
                    "fault",
                    "max_steps",
                    "breakpoints",
                    "delay_ms",
                }:
                    raise ValueError("Unexpected configuration fields.")
                breakpoints = data.pop("breakpoints", [])
                delay = data.pop("delay_ms", 350)
                session = self.server.sessions.create(data, breakpoints, delay)
                return self.send(201, session.snapshot())
            if self.path in (
                "/api/debug/control",
                "/api/debug/query",
                "/api/debug/argument",
                "/api/debug/breakpoints",
            ):
                session = self.server.sessions.get(data.get("session_id"))
                if self.path == "/api/debug/control":
                    if set(data) - {"session_id", "action", "revision"}:
                        raise ValueError("Unexpected control fields.")
                    snapshot = session.command(data.get("action"), data.get("revision"))
                elif self.path == "/api/debug/query":
                    if set(data) - {"session_id", "query", "revision"}:
                        raise ValueError("Unexpected query-edit fields.")
                    snapshot = session.override(data.get("query"), data.get("revision"))
                elif self.path == "/api/debug/argument":
                    if set(data) - {"session_id", "argument", "value", "revision"}:
                        raise ValueError("Unexpected tool-argument fields.")
                    snapshot = session.override_argument(
                        data.get("argument"), data.get("value"), data.get("revision")
                    )
                else:
                    if set(data) - {"session_id", "breakpoints", "revision"}:
                        raise ValueError("Unexpected breakpoint fields.")
                    snapshot = session.configure(
                        data.get("breakpoints"), data.get("revision")
                    )
                return self.send(200, snapshot)
            if self.path == "/api/check-schema":
                errors = check_schema(data.get("schema"))
                return self.send(200, {"passed": not errors, "errors": errors})
            if set(data) - {"prompt", "mode", "provider", "fault", "max_steps"}:
                raise ValueError("Unexpected request fields.")
            self.send(200, run(**data))
        except Conflict as exc:
            self.send(409, {"error": str(exc)})
        except KeyError:
            self.send(404, {"error": "Debug session not found. Create a new run."})
        except (ValueError, TypeError, UnicodeError):
            self.send(
                400,
                {
                    "error": "Invalid request. Check prompt, mode, provider, fault, and step limit."
                },
            )


def serve(port=8765):
    """Expose the lab only on this computer; do not use as a public server."""
    server = LabServer(("127.0.0.1", port), Handler)
    print(f"Agent Runtime Debugger: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
