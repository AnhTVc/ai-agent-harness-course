# AI Agent and Agent Harness

This repository contains the approved **Session 01 / Video 01** lesson. The
lesson is a runnable debugger for a Python agent runtime: learners can pause,
step, inspect each operation, and compare the state before and after it.

## Run the lesson

Requires Python 3.11 or later. The default offline lesson uses only the Python
standard library.

```sh
cd sessions/01-agent-architecture/video-01-from-llm-to-agent
python3 run.py
```

Open **http://127.0.0.1:8765**. The lesson guide explains the debugger, model
providers, tools, source map, and classroom runbook:

[Session 01 / Video 01 — From LLM to AI Agent](sessions/01-agent-architecture/video-01-from-llm-to-agent/README.md)

## Repository layout

```text
ai-agent-harness-course/
├── README.md
├── .gitignore
└── sessions/
    └── 01-agent-architecture/
        └── video-01-from-llm-to-agent/
            ├── docs/          Architecture, video alignment, runbook, exercises, verification
            ├── examples/      Reproducible offline traces
            ├── exercises/     Tool-contract starter and reference
            ├── presentation/  Video slides and supplied illustration assets
            ├── src/           Python runtime, debugger API, and web interface
            ├── tests/         Runtime, debugger, HTTP, and package checks
            └── run.py         Web debugger and command-line entry point
```

The documentation and source comments are in English. Supplied slide artwork is
kept as lesson material. Local `.env` files, generated traces, coverage output,
and test caches are excluded by the repository-level `.gitignore`.
