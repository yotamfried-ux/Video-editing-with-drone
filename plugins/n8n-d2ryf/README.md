# n8n-d2ryf (Claude Code plugin)

Connects Claude Code to the self-hosted n8n instance at
`https://n8n.d2ryf.com/mcp-server/http` (MCP over HTTP, OAuth).

## Contents

| Path | What |
| --- | --- |
| `.mcp.json` | Registers the `n8n` MCP server |
| `skills/n8n-workflows/` | How Claude should discover, inspect and safely run workflows |
| `commands/n8n-list.md` | `/n8n-d2ryf:n8n-list` – list exposed workflows |
| `commands/n8n-run.md` | `/n8n-d2ryf:n8n-run <name> [input]` – inspect and run one |

## Install

From inside this repository:

```
/plugin marketplace add ./
/plugin install n8n-d2ryf@video-editing-with-drone
```

Or from GitHub: `/plugin marketplace add yotamfried-ux/Video-editing-with-drone`.

Then run `/mcp`, choose **n8n**, and finish the OAuth sign-in.

## n8n side

In n8n: Settings → MCP access must be enabled, and each workflow you want
Claude to see needs "Available in MCP" turned on.
