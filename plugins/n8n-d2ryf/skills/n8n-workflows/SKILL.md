---
name: n8n-workflows
description: Find, inspect and run workflows on the self-hosted n8n instance (n8n.d2ryf.com) through the plugin's `n8n` MCP server. Use when the user mentions n8n, an automation or workflow they host there, or asks to trigger, check or debug one.
---

# Working with the n8n instance

The plugin registers an MCP server named `n8n` pointing at
`https://n8n.d2ryf.com/mcp-server/http`. Its tools appear as `mcp__plugin_n8n-d2ryf_n8n__*`.

## Before anything else

1. If no `n8n` tools are listed, the server is not connected or not authorized.
   Tell the user to run `/mcp`, select **n8n**, and complete the OAuth sign-in
   in the browser. Do not guess tool names or fabricate results.
2. Only workflows that are enabled for MCP access in n8n (workflow settings →
   "Available in MCP") are visible. If an expected workflow is missing, say so
   instead of assuming it does not exist.

## Workflow

1. **Discover** – list the server's tools first; use its search/list tool to
   find workflows by name or description.
2. **Inspect** – read the workflow's details (trigger type, expected input
   fields) before running it. Summarize what it will do.
3. **Confirm** – executing a workflow can have real side effects (uploads,
   messages, Drive moves, deliveries). Confirm with the user before running
   anything that writes, sends or deletes, unless they explicitly asked to run it.
4. **Execute** – pass inputs exactly as the trigger expects. Report the
   execution result or ID faithfully, including errors.

## Notes for this project

Workflows here typically glue the drone video pipeline to Google Drive,
Cloudflare Stream and delivery steps (see `integrations/` and `services/`).
When a workflow fails, cross-check the corresponding Python integration before
proposing a fix.
