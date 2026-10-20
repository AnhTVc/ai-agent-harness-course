# Alignment to Video 01

The supplied Video 01 script controls this lesson. It covers approximately 38
minutes across slides 04–12. The scope document describes the full session; this
repository implements the approved first video only.

| Slide | Video time  | Topic                           | Debugger demonstration                                                              |
| ----- | ----------- | ------------------------------- | ----------------------------------------------------------------------------------- |
| 04    | 00:00–03:00 | From LLM to AI Agent            | Compare the model node with the runtime and environment nodes.                      |
| 05    | 03:00–06:00 | What an LLM does                | Inspect provider output: a structured request is still only data.                   |
| 06    | 06:00–10:00 | Chatbot, workflow, and agent    | Create runs with each pattern and compare tool/model counters.                      |
| 07    | 10:00–13:00 | Five conceptual components      | Inspect model, context, tools, runtime, and the fixture/API environment.            |
| 08    | 13:00–18:00 | Responsibilities and boundaries | Open the actual Python method behind each graph node.                               |
| 09    | 18:00–22:00 | Agent loop                      | Step through input, context, provider, request, result, observation, and stop.      |
| 10    | 22:00–26:00 | ReAct                           | Read observable proposal, action, and observation events without private reasoning. |
| 11    | 26:00–30:00 | Tool calling                    | Pause before execution and distinguish schema, request, executor, and result.       |
| 12    | 30:00–38:00 | Prepared Python demonstration   | Follow the eight-minute runbook and inspect context changes.                        |

The slide 13 pipeline extension is out of scope. This lesson does not implement
multi-agent messaging, an orchestration framework, RAG indexing, retry/backoff,
persistent memory, or production operations.

## Continuity with the script

Use the same prepared task throughout: summarize a company's AI capabilities
from supplied documents. The fixture documents describe fictional ExampleCo.
The primary prepared task remains document lookup: it returns IDs and text from
a small synthetic collection. Do not present it as a real company lookup or a
RAG system. The weather and arithmetic presets are supplementary tool-contract
examples. Weather reads current conditions from Open-Meteo only when the
executor boundary is stepped; arithmetic is evaluated locally.

## Adapted paths

| Script reference           | Lesson equivalent                                            |
| -------------------------- | ------------------------------------------------------------ |
| Course agent source        | Runtime module                                               |
| Model adapter              | Provider module                                              |
| Tool implementation        | Tools module                                                 |
| Prepared architecture demo | Local web debugger                                           |
| Start the video demo       | python3 run.py                                               |
| Ollama CLI                 | OLLAMA_MODEL=qwen3:8b python3 run.py --cli --provider ollama |
| Model input event          | model_input                                                  |
| Tool request event         | tool_request                                                 |
| Successful tool execution  | tool_result                                                  |
| Final stop                 | stop with reason completed                                   |

Event names are implementation details. Causal order, matching call IDs,
context changes, and explicit stop reasons are the evidence to inspect.
