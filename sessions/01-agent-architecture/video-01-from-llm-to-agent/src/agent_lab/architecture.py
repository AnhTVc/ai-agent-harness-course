"""One catalog connects diagram boxes, responsibility notes, and source files.

The browser receives only this allowlisted catalog. Source inspection cannot
accept arbitrary disk paths. The layout is original course material.
"""

NODES = [
    {
        "id": "user",
        "label": "User",
        "tag": "01 / GOAL",
        "file": "runtime.py",
        "symbol": "run",
        "description": "Supplies the goal. The user does not directly execute a model-generated tool request.",
    },
    {
        "id": "context",
        "label": "Working context",
        "tag": "02 / STATE",
        "file": "runtime.py",
        "symbol": "run",
        "description": "Runtime-owned system prompt, user goal, assistant messages, and tool observations. Rebuilt for every run; no long-term memory.",
    },
    {
        "id": "model",
        "label": "Model",
        "tag": "03 / PROPOSE",
        "file": "providers.py",
        "symbol": "OfflineModel",
        "description": "Returns text or structured tool requests. Offline is a rule-based stand-in; Ollama is a real local model. Neither gets a Python executor handle.",
    },
    {
        "id": "schema",
        "label": "Tool schema",
        "tag": "CAPABILITY CONTRACT",
        "file": "tools.py",
        "symbol": "TOOL_SCHEMAS",
        "description": "Describes search_documents, search_weather, and calculate. Schemas constrain model requests but contain no executable implementation.",
    },
    {
        "id": "executor",
        "label": "Tool executor",
        "tag": "04 / VALIDATE + ACT",
        "file": "tools.py",
        "symbol": "execute",
        "description": "Application code validates the allowlist and arguments, then dispatches one bounded operation. Unknown tools and unexpected fields are rejected.",
    },
    {
        "id": "environment",
        "label": "Tool data",
        "tag": "05 / EVIDENCE",
        "file": "tools.py",
        "symbol": "_search_weather",
        "description": "The tools use a synthetic document fixture, a local arithmetic evaluator, or the fixed read-only Open-Meteo API. Each result is returned as an inspectable observation.",
    },
    {
        "id": "runtime",
        "label": "Runtime / Harness",
        "tag": "CONTROL BOUNDARY",
        "file": "runtime.py",
        "symbol": "run",
        "description": "Owns context, tool dispatch, trace events, and the model-call limit. Orchestration is a responsibility and may be implemented in ordinary code.",
    },
    {
        "id": "answer",
        "label": "Answer + stop",
        "tag": "06 / VERIFY",
        "file": "runtime.py",
        "symbol": "_finalize",
        "description": "No tool requests ends the turn. A hard step limit or provider failure also stops it. Inspect status and trace instead of trusting the answer alone.",
    },
]
EDGES = [
    {"from": "user", "to": "context", "label": "goal"},
    {"from": "context", "to": "model", "label": "messages"},
    {"from": "schema", "to": "model", "label": "capabilities"},
    {"from": "model", "to": "executor", "label": "tool request"},
    {"from": "executor", "to": "environment", "label": "validated lookup"},
    {"from": "environment", "to": "context", "label": "observation"},
    {"from": "model", "to": "answer", "label": "no tool request"},
]

# Canvas coordinates are part of the same catalog as source responsibilities.
# The UI renders these nodes/edges directly instead of maintaining another map.
POSITIONS = {
    "user": (30, 28, 148, 66),
    "context": (268, 28, 166, 66),
    "model": (548, 28, 170, 66),
    "runtime": (30, 126, 148, 66),
    "schema": (268, 126, 166, 66),
    "executor": (548, 126, 170, 66),
    "environment": (548, 226, 170, 66),
    "answer": (30, 226, 166, 66),
}
for node in NODES:
    node["position"] = POSITIONS[node["id"]]

EDGE_PATHS = {
    ("user", "context"): "M178 61 H268",
    ("context", "model"): "M434 61 H548",
    ("schema", "model"): "M434 159 H486 V84 H548",
    ("model", "executor"): "M633 94 V126",
    ("executor", "environment"): "M633 192 V226",
    ("environment", "context"): "M548 259 H466 V110 H351 V94",
    # Enter Answer through the open gap between node rows, avoiding a frame around the canvas.
    ("model", "answer"): "M548 61 H500 V109 H212 V259 H196",
}
for edge in EDGES:
    edge["id"] = edge["from"] + "-" + edge["to"]
    edge["path"] = EDGE_PATHS[(edge["from"], edge["to"])]
    # Tie each conceptual connection to the runtime event that proves it ran.
    edge["event_kinds"] = {
        "user-context": ["context"],
        "context-model": ["model_input"],
        "schema-model": ["tool_specs"],
        "model-executor": ["tool_request"],
        "executor-environment": ["tool_result"],
        "environment-context": ["observation"],
        "model-answer": ["stop"],
    }[edge["id"]]
    # Keep the short visible label beside its route instead of hard-coding UI coordinates.
    edge["label_position"] = {
        "user-context": [202, 51],
        "context-model": [465, 51],
        "schema-model": [490, 119],
        "model-executor": [643, 115],
        "executor-environment": [643, 215],
        "environment-context": [359, 215],
        "model-answer": [340, 104],
    }[edge["id"]]

# Mode-only routes put the Runtime explicitly on the control path. Their SVG
# geometry avoids the shared nodes so each execution pattern has a distinct map.
MODE_EDGES = [
    {
        "id": "user-runtime",
        "from": "user",
        "to": "runtime",
        "label": "goal enters runtime",
        "short_label": "goal",
        "label_position": [110, 119],
        "path": "M104 94 V126",
        "event_kinds": ["context", "workflow_step"],
    },
    {
        "id": "runtime-context",
        "from": "runtime",
        "to": "context",
        "label": "runtime assembles context",
        "short_label": "context",
        "label_position": [266, 106],
        "path": "M178 159 H220 V110 H351 V94",
        "event_kinds": ["context", "model_input"],
    },
    {
        "id": "runtime-executor",
        "from": "runtime",
        "to": "executor",
        "label": "runtime validates and dispatches",
        "short_label": "validate + dispatch",
        "label_position": [330, 224],
        "path": "M178 159 H220 V211 H528 V159 H548",
        "event_kinds": ["workflow_step", "tool_request"],
    },
    {
        "id": "environment-runtime",
        "from": "environment",
        "to": "runtime",
        "label": "workflow result returns to code",
        "short_label": "result",
        "label_position": [335, 255],
        "path": "M548 259 H210 V216 H104 V192",
        "event_kinds": ["tool_result"],
    },
    {
        "id": "runtime-answer",
        "from": "runtime",
        "to": "answer",
        "label": "code returns the fixed result",
        "short_label": "answer",
        "label_position": [111, 219],
        "path": "M104 192 V226",
        "event_kinds": ["stop"],
    },
    {
        "id": "model-runtime",
        "from": "model",
        "to": "runtime",
        "label": "model proposal returns to runtime",
        "short_label": "tool proposal",
        "label_position": [344, 101],
        "path": "M548 61 H500 V108 H210 V159 H178",
        "event_kinds": ["tool_request"],
    },
    {
        "id": "workflow-answer",
        "from": "environment",
        "to": "answer",
        "label": "fixed result becomes the answer",
        "short_label": "result",
        "label_position": [690, 214],
        "path": "M682 192 V226",
        "event_kinds": ["tool_result", "stop"],
    },
]

# Every mode owns a complete canvas layout and path table. Moving the nodes as
# well as changing the routes makes each control pattern visibly distinct.
MODE_VIEWS = {
    "agent": {
        "label": "Agent loop",
        "decision_owner": "MODEL SELECTS THE NEXT ACTION",
        "description": "The model receives tool schemas, proposes an action, and continues from the returned observation.",
        "model_behavior": "Model call: includes tool schemas",
        "tool_behavior": "Tools: model may request an allowlisted tool",
        "node_ids": [
            "user",
            "runtime",
            "context",
            "model",
            "schema",
            "executor",
            "environment",
            "answer",
        ],
        "edge_ids": [
            "user-runtime",
            "runtime-context",
            "context-model",
            "schema-model",
            "model-runtime",
            "runtime-executor",
            "executor-environment",
            "environment-runtime",
            "model-answer",
        ],
        "positions": {
            "user": [20, 60, 140, 66],
            "runtime": [220, 60, 150, 66],
            "context": [430, 60, 150, 66],
            "model": [620, 60, 130, 66],
            "schema": [620, 220, 130, 66],
            "executor": [430, 220, 150, 66],
            "environment": [220, 220, 150, 66],
            "answer": [20, 220, 140, 66],
        },
        "edge_paths": {
            "user-runtime": "M160 93 H220",
            "runtime-context": "M370 93 H430",
            "context-model": "M580 93 H620",
            "schema-model": "M685 220 V126",
            "model-runtime": "M620 93 H600 V40 H370 V93",
            "runtime-executor": "M295 126 V165 H505 V220",
            "executor-environment": "M430 253 H370",
            "environment-runtime": "M220 253 H190 V93 H220",
            "model-answer": "M685 60 V12 H170 V253 H160",
        },
        "label_positions": {
            "user-runtime": [169, 86],
            "runtime-context": [382, 86],
            "context-model": [587, 86],
            "schema-model": [690, 176],
            "model-runtime": [465, 34],
            "runtime-executor": [386, 158],
            "executor-environment": [383, 245],
            "environment-runtime": [192, 180],
            "model-answer": [395, 20],
        },
    },
    "workflow": {
        "label": "Fixed workflow",
        "decision_owner": "PYTHON CODE SELECTS THE NEXT STEP",
        "description": "The prescribed lookup runs through code; the model and tool-schema nodes are not used.",
        "model_behavior": "Model call: none",
        "tool_behavior": "Tool: selected by code, then executed",
        "node_ids": ["user", "runtime", "executor", "environment", "answer"],
        "edge_ids": [
            "user-runtime",
            "runtime-executor",
            "executor-environment",
            "workflow-answer",
        ],
        "positions": {
            "user": [20, 126, 140, 66],
            "runtime": [205, 126, 150, 66],
            "executor": [425, 126, 150, 66],
            "environment": [620, 126, 125, 66],
            "answer": [620, 226, 125, 66],
            "context": [20, 226, 166, 66],
            "schema": [220, 226, 166, 66],
            "model": [425, 226, 170, 66],
        },
        "edge_paths": {
            "user-runtime": "M160 159 H205",
            "runtime-executor": "M355 159 H425",
            "executor-environment": "M575 159 H620",
            "workflow-answer": "M682 192 V226",
        },
        "label_positions": {
            "user-runtime": [164, 119],
            "runtime-executor": [365, 119],
            "executor-environment": [582, 119],
            "workflow-answer": [691, 214],
        },
    },
    "chatbot": {
        "label": "Chatbot baseline",
        "decision_owner": "MODEL WRITES AN ANSWER ONLY",
        "description": "The model receives context without tool schemas, so no executor action is available.",
        "model_behavior": "Model call: without tool schemas",
        "tool_behavior": "Tools: unavailable to the model",
        "node_ids": ["user", "runtime", "context", "model", "answer"],
        "edge_ids": [
            "user-runtime",
            "runtime-context",
            "context-model",
            "model-answer",
        ],
        "positions": {
            "user": [10, 126, 138, 66],
            "runtime": [160, 126, 138, 66],
            "context": [310, 126, 138, 66],
            "model": [460, 126, 138, 66],
            "answer": [610, 126, 138, 66],
            "schema": [160, 226, 166, 66],
            "executor": [310, 226, 170, 66],
            "environment": [460, 226, 170, 66],
        },
        "edge_paths": {
            "user-runtime": "M148 159 H160",
            "runtime-context": "M298 159 H310",
            "context-model": "M448 159 H460",
            "model-answer": "M598 159 H610",
        },
        "label_positions": {
            "user-runtime": [73, 118],
            "runtime-context": [222, 118],
            "context-model": [367, 118],
            "model-answer": [513, 118],
        },
    },
}
