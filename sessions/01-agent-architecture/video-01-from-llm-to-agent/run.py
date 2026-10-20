"""One entry point for the dependency-free classroom demo and JSON CLI."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
# Load the lesson's ignored local .env before provider modules read configuration.
from agent_lab.config import load_env_file

load_env_file(Path(__file__).resolve().parent / ".env")
from agent_lab.runtime import run
from agent_lab.server import serve

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Session 01 / Video 01 architecture lab"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Print a full run as JSON instead of starting the web view",
    )
    parser.add_argument("--prompt", default="Summarize the company AI capabilities.")
    parser.add_argument(
        "--mode", choices=["agent", "workflow", "chatbot"], default="agent"
    )
    parser.add_argument(
        "--provider", choices=["offline", "ollama", "cloudflare"], default="offline"
    )
    parser.add_argument(
        "--fault",
        choices=["none", "no_specs", "no_executor", "no_observation"],
        default="none",
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.cli:
        result = run(
            args.prompt, mode=args.mode, provider=args.provider, fault=args.fault
        )
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] == "completed" else 2)
    serve(args.port)
