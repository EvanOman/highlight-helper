# Background Agents Research

## Overview

This document captures research on implementing background AI agents using the Claude Agent SDK for the Highlight Helper application. The goal is to add intelligent automation features while staying within a $0.50/month budget target.

## Claude Agent SDK

### Installation

```bash
pip install claude-agent-sdk
```

**Prerequisites:** Python 3.10+

The Claude Code CLI is automatically bundled with the package. For custom paths:
```python
ClaudeAgentOptions(cli_path="/path/to/claude")
```

### Two Main Approaches

The SDK provides two primary interfaces:

#### 1. `query()` - Simple Async Iterator

Best for straightforward, single-prompt interactions:

```python
import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

async def analyze_highlight():
    options = ClaudeAgentOptions(
        system_prompt="You are a helpful reading assistant.",
        max_turns=1,
    )

    async for message in query(
        prompt="Summarize this highlight: '...'",
        options=options
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"Result: {block.text}")
        elif isinstance(message, ResultMessage) and message.total_cost_usd > 0:
            print(f"Cost: ${message.total_cost_usd:.4f}")

anyio.run(analyze_highlight)
```

#### 2. `ClaudeSDKClient` - Bidirectional Interactive Conversations

Best for custom tools, hooks, and multi-turn conversations:

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

async with ClaudeSDKClient(options=options) as client:
    await client.query("Your prompt")
    async for msg in client.receive_response():
        print(msg)
```

### Custom Tools (In-Process MCP Servers)

Custom tools allow defining Python functions that Claude can invoke:

```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions, ClaudeSDKClient

@tool("search_highlights", "Search user's highlights", {"query": str})
async def search_highlights(args):
    # Query database for matching highlights
    results = await db.search(args['query'])
    return {
        "content": [
            {"type": "text", "text": f"Found {len(results)} highlights"}
        ]
    }

server = create_sdk_mcp_server(
    name="highlight-tools",
    version="1.0.0",
    tools=[search_highlights]
)

options = ClaudeAgentOptions(
    mcp_servers={"tools": server},
    allowed_tools=["mcp__tools__search_highlights"]
)
```

**Benefits of in-process MCP servers:**
- No subprocess management
- Better performance (no IPC overhead)
- Simpler deployment (single process)
- Easier debugging

### Hooks for Guardrails

Hooks provide deterministic control over agent behavior:

```python
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher

async def check_tool_use(input_data, tool_use_id, context):
    tool_name = input_data["tool_name"]
    tool_input = input_data["tool_input"]

    # Block dangerous operations
    if tool_name == "Bash":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Bash commands not allowed",
            }
        }
    return {}

options = ClaudeAgentOptions(
    allowed_tools=["Read", "Edit"],
    hooks={
        "PreToolUse": [
            HookMatcher(matcher="*", hooks=[check_tool_use]),
        ],
    }
)
```

### Tool Configuration

Standard tools available:
- `Read`, `Glob`, `Grep` - Read-only analysis
- `Edit`, `Write` - File modification
- `Bash` - Command execution
- `WebSearch` - Web search capability

Permission modes:
- `acceptEdits` - Auto-approve file edits
- `bypassPermissions` - Run without prompts (for automation)
- `default` - Requires `canUseTool` callback

### Streaming vs Single-Turn

For background jobs, collect all messages at once instead of streaming:

```python
from claude_agent_sdk import query, ClaudeAgentOptions

async def background_task():
    messages = []
    async for message in query(
        prompt="Analyze these highlights...",
        options=ClaudeAgentOptions(max_turns=3)
    ):
        messages.append(message)
    return messages
```

## Model Pricing (January 2026)

Source: [Anthropic Pricing Documentation](https://platform.claude.com/docs/en/about-claude/pricing)

### Standard API Pricing

| Model | Input (per MTok) | Output (per MTok) |
|-------|------------------|-------------------|
| Claude Haiku 4.5 | $1.00 | $5.00 |
| Claude Sonnet 4.5 | $3.00 | $15.00 |
| Claude Opus 4.5 | $5.00 | $25.00 |

### Batch API Pricing (50% discount)

| Model | Batch Input (per MTok) | Batch Output (per MTok) |
|-------|------------------------|-------------------------|
| Claude Haiku 4.5 | $0.50 | $2.50 |
| Claude Sonnet 4.5 | $1.50 | $7.50 |
| Claude Opus 4.5 | $2.50 | $12.50 |

### Prompt Caching

- **Cache writes (5-min):** 1.25x base input price
- **Cache writes (1-hour):** 2x base input price
- **Cache reads:** 0.1x base input price (90% savings)

### Cost Optimization Strategies

1. **Use Haiku for simple tasks** - 3-5x cheaper than Sonnet
2. **Batch API for async jobs** - 50% discount on all tokens
3. **Prompt caching** - Up to 90% savings on repeated context
4. **Minimize output tokens** - Output costs 5x more than input

## Token Estimation Guidelines

Rough estimates for planning:
- 1 token ~ 4 characters or 0.75 words in English
- Average book highlight: 50-200 words ~ 65-265 tokens
- System prompt + context: ~500-1000 tokens
- Simple analysis response: ~100-300 tokens
- Detailed analysis response: ~500-1500 tokens

## Relevant Use Cases for Highlight Helper

### 1. Highlight Categorization (Low Cost)
- **Task:** Auto-tag highlights by theme/topic
- **Model:** Haiku 4.5 (simple classification)
- **Tokens per request:** ~500 input, ~50 output

### 2. Related Highlight Discovery (Medium Cost)
- **Task:** Find thematically related highlights
- **Model:** Haiku 4.5 or Sonnet 4.5
- **Tokens per request:** ~2000 input, ~200 output

### 3. Reading Insights (Medium Cost)
- **Task:** Generate periodic reading summaries
- **Model:** Sonnet 4.5 (better synthesis)
- **Tokens per request:** ~3000 input, ~500 output

### 4. Book Recommendations (Low Cost)
- **Task:** Suggest books based on highlight patterns
- **Model:** Haiku 4.5 with caching
- **Tokens per request:** ~1000 input, ~200 output

## SDK Demo Repository

For complete working examples, see: [anthropics/claude-agent-sdk-demos](https://github.com/anthropics/claude-agent-sdk-demos)

Demos include:
- Email assistant
- Research agent
- Code review agent
- Multi-agent orchestration

## References

- [Claude Agent SDK Quickstart](https://platform.claude.com/docs/en/agent-sdk/quickstart)
- [Claude Agent SDK Python GitHub](https://github.com/anthropics/claude-agent-sdk-python)
- [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [SDK Demo Repository](https://github.com/anthropics/claude-agent-sdk-demos)
