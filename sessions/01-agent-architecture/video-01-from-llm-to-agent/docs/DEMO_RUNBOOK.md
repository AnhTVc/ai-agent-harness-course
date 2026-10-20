# Eight-minute live debugger runbook

## Prepare

From this video directory, start **python3 run.py** and open
http://127.0.0.1:8765 in a desktop browser. Keep the default goal
**Summarize the company AI capabilities.** and provider **Offline · rule-based**.
The source document fixtures describe fictional ExampleCo.

Say: **“This run uses deterministic rules to make the execution reproducible.
It is not a real model inference or an answer-quality test.”**

Keep the default **Tool execution** breakpoint checked. Set **Continue pace** to
**350 ms / step** so the event order is easy to follow.

## 00:00–01:00 — Start with no hidden work

Select **Create paused run**. Show zero events, zero model calls, and zero tool
calls. Explain that creating a session has not called the model or document
handler.

Select **Step** once for the user goal, then once for context assembly. The
timeline records these operations and the graph marks the nodes they visited.

## 01:00–02:15 — Let the model propose

Select **Continue**. It advances the actual Python engine until the default
breakpoint, before tool execution.

Read the model input and response in the timeline. Then inspect the tool
request. Point out its call ID, function name, and arguments. The executed-tool
counter must still be zero: a tool request is only a proposal.

## 02:15–03:15 — Change one pending argument

In **Paused before tool execution**, replace the query with **evaluation**, then
select **Apply query edit**. Show the new debug-override event. The original
model request remains in the trace, and the inspector shows both original and
replacement values.

Open **Documents** and show that the fixture includes DOC-004, about
evaluation. This panel is read-only; the Python executor still performs the
lookup.

## 03:15–04:30 — Execute exactly one operation

Select **Step**. The tool-execution boundary performs the allowlisted lookup.
The result should contain DOC-004 and the same call ID. The executed-tool
counter becomes one.

Select **Context → Before / After** for this tool result. Both sides still show
three messages. The lookup result exists as an event, but it has not entered
model context yet.

## 04:30–05:30 — Append the observation

Select **Step** again. The observation boundary appends one tool-role message.
The context count becomes four.

Compare **Before** and **After**. Open **Source** to highlight the method that
appends the observation. Explain that the next model input is prepared only
after this boundary completes.

## 05:30–07:00 — Finish and inspect the evidence

Select **Continue**. The offline model reads the recorded tool message and
returns a response that cites DOC-004. The stop event records why the run ended.

Select the model response, result, and observation in the timeline. Explain why
a claim without a matching successful result is not enough to prove the lookup.

## 07:00–08:00 — Preserve an inspection copy

Select **Export trace** and explain that it downloads the current local debug
snapshot as JSON for annotation. Timeline selection is read-only and does not
call the model or tool again.

Optional contrast: create a new run with **Remove executor** selected. Continue
to the tool boundary, then Step once. The request remains visible, no document
lookup succeeds, and the stop status explains the missing handler. Keep this
experiment short; later sessions cover broader orchestration and resilience.

## Optional local-model take

If Ollama and a tool-capable model are already installed, select
**Ollama · real local LLM** and create a fresh run. Describe only what its trace
shows. The model may answer directly, propose an invalid request, or fail. A
failed or unexecuted request is not a successful live-model demonstration.

## Alternate live-weather tool demonstration

This short take uses the additional allowlisted weather capability to contrast
a real external read with local fixture search. Keep **Offline · rule-based**
selected so tool choice is repeatable; the weather result itself comes from the
Open-Meteo API.

1. Select **Weather · Hanoi**, keep **Agent loop**, and create a paused run.
2. Continue to the **execute_tool** breakpoint. Inspect the proposed
   `search_weather` call and confirm that the tool counter is still zero.
3. Open **Tools / Data** to compare the weather schema and fixed API source with
   the synthetic document fixture. Edit `location` to `Oslo, Norway` if you
   want to demonstrate the audited argument override.
4. Select **Step**. This is the first point where the two bounded HTTPS requests
   run: one geocodes the place, and one reads current conditions. The result
   event shows the matched location, observation time, units, and source.
5. Select **Source** on the result event. The inspector highlights the actual
   `_search_weather` handler. Step again to append that observation to context,
   then Continue to the offline model's evidence-based answer.

Use the **Calculate** preset for a local-only comparison. At its executor
breakpoint, inspect and edit the arithmetic expression, Step once, and open
**Source** on the result to see the restricted AST evaluator. This path makes no
external API request.
