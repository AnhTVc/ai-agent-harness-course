# Tool contract practice

Complete schema_starter.json using schema_reference.json as the answer key.
The contract describes search_documents(query):

- query must be a string with at least one and at most 2000 characters.
- query is required.
- Extra properties are rejected.
- The handler is read-only and returns source IDs and text.

The checker is available through the local lesson API at POST /api/check-schema
with a JSON object containing schema. The response includes passed and errors.
For a real behavior change, update the trusted schema and executor together,
then review the runtime trace. A passing contract check alone does not execute
a tool.
