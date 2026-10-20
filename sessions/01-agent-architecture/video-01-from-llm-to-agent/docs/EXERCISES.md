# Learner exercises and completion rubric

Use the offline provider so all expected branches are reproducible. The fixture
documents describe fictional ExampleCo.

## Exercise A — Trace one actual run

Create a paused run with the default goal. Predict what the model-call and
tool-call counters will show before pressing a control. Step through the user
goal and context assembly, then Continue to the default tool breakpoint.

Record:

- Which events ran before the breakpoint?
- Which Python method is next?
- Has the document tool executed?
- Which event first contains a structured tool request?

## Exercise B — Separate request from action

At the tool breakpoint, inspect the request. Step once to run the tool. Then
compare the timeline result with **Context → Before / After**.

Explain why a result event can exist before the result appears as a tool-role
message in context. Step once more and record the change.

## Exercise C — Edit and audit a pending request

While paused before the document-search tool, change the query to **evaluation**.
Inspect the debug-override event before executing. Compare its original and
replacement arguments, then run the tool and cite the returned document ID.
Explain why an edit after execution would not represent the same operation.

## Exercise D — Compare the control patterns

Create separate runs for Agent loop, Fixed workflow, and Chatbot baseline. For
each one, record model-call count, executed-tool count, and the operation that
selected the next action. Keep the same goal so the control pattern is the
meaningful variable.

## Exercise E — Remove a boundary

In Agent loop mode, repeat the run with **Remove executor**. Predict the result
before continuing. Confirm that a model request exists but no successful
document result follows. Optionally compare **Remove tool specifications** or
**Withhold observation** and inspect the trace rather than assuming the offline
provider and a real model behave identically.

## Optional tool-contract practice

Complete the schema starter using the requirements in the exercises folder.
The prepared handler accepts a nonempty string from 1 to 2000 characters and
rejects extra arguments. A schema check tests this lesson contract only; it is
not a general JSON Schema validator.

## Completion rubric

The learner can identify who proposes, validates, and executes a tool request;
pair a request and result by call ID; show when a result enters context; find the
source method for an executed boundary; and state why a request alone does not
prove successful retrieval.

## Compare external I/O with local computation

Use **Weather · Hanoi** and **Calculate** with the offline provider. At each
tool breakpoint, inspect the declared argument and confirm that no operation
has run yet. Then compare the result events and their source locations.

- Which weather request first crosses the process boundary, and what evidence
  identifies its place, observation time, and source?
- Can the model choose the weather API host? Which code fixes that destination?
- Which arithmetic syntax is accepted, and which AST node rejects a function
  call or name?
- Does the observation enter context in the same boundary as tool execution?

The weather exercise makes two read-only HTTPS requests only after Step. The
calculator exercise runs in-process and has no network side effect.
