---
description: Inspect and run an n8n workflow by name
argument-hint: <workflow name> [input as JSON or key=value pairs]
---

Run the n8n workflow matching: $ARGUMENTS

1. Find the workflow with the `n8n` MCP server (n8n-d2ryf plugin). If several
   match, show them and ask which one.
2. Read its details and show me the inputs it expects and what it does.
3. Ask me to confirm before executing if it has side effects, then execute it
   with the given input and report the result or error verbatim.
