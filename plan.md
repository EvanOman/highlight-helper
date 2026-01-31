# Background Agents Implementation Plan

## Goal

Add intelligent background agents to Highlight Helper that enhance the reading experience while staying within a **$0.50/month budget target**.

## Cost Analysis

### Pricing Reference (Claude Haiku 4.5 - Batch API)

| Type | Price per Million Tokens | Price per 1K Tokens |
|------|-------------------------|---------------------|
| Input | $0.50 | $0.0005 |
| Output | $2.50 | $0.0025 |

Using Haiku 4.5 with Batch API provides the most cost-effective option (50% discount on already-cheap model).

### Monthly Budget Breakdown: $0.50/month

#### Feature 1: Highlight Auto-Categorization
- **Trigger:** On new highlight import
- **Tokens per highlight:** 500 input + 50 output
- **Cost per highlight:** (500 * $0.0005 / 1000) + (50 * $0.0025 / 1000) = $0.000375
- **Monthly volume:** 100 highlights
- **Monthly cost:** **$0.0375**

#### Feature 2: Weekly Reading Digest
- **Trigger:** Weekly cron job (4x/month)
- **Tokens per digest:** 3000 input + 500 output
- **Cost per digest:** (3000 * $0.0005 / 1000) + (500 * $0.0025 / 1000) = $0.00275
- **Monthly volume:** 4 digests
- **Monthly cost:** **$0.011**

#### Feature 3: Related Highlight Discovery
- **Trigger:** On-demand when viewing a highlight
- **Tokens per request:** 2000 input + 200 output
- **Cost per request:** (2000 * $0.0005 / 1000) + (200 * $0.0025 / 1000) = $0.0015
- **Monthly volume:** 50 requests
- **Monthly cost:** **$0.075**

#### Feature 4: Monthly Book Recommendations
- **Trigger:** Monthly cron job (1x/month)
- **Tokens per job:** 5000 input + 300 output
- **Cost per job:** (5000 * $0.0005 / 1000) + (300 * $0.0025 / 1000) = $0.00325
- **Monthly volume:** 1 job
- **Monthly cost:** **$0.00325**

### Total Monthly Cost Estimate

| Feature | Monthly Cost |
|---------|-------------|
| Auto-Categorization (100 highlights) | $0.0375 |
| Weekly Digest (4 digests) | $0.011 |
| Related Discovery (50 requests) | $0.075 |
| Book Recommendations (1 job) | $0.00325 |
| **Buffer for overhead/retries (20%)** | $0.025 |
| **Total** | **$0.152** |

**Result:** Well under the $0.50/month target with room for 3x growth.

### Cost Scaling Scenarios

| Usage Level | Highlights/mo | Discovery/mo | Est. Cost |
|-------------|---------------|--------------|-----------|
| Light | 50 | 20 | $0.07 |
| Normal | 100 | 50 | $0.15 |
| Heavy | 300 | 150 | $0.42 |
| Extreme | 500 | 300 | $0.72 |

## Proposed Features (Priority Order)

### Phase 1: Highlight Auto-Categorization

**Value:** Automatic organization without manual tagging
**Complexity:** Low
**Cost:** ~$0.04/month

**Implementation:**
```python
from claude_agent_sdk import query, ClaudeAgentOptions

async def categorize_highlight(highlight_text: str, book_title: str) -> list[str]:
    options = ClaudeAgentOptions(
        system_prompt="""You are a reading assistant. Categorize highlights into themes.
        Return a JSON array of 1-3 category tags. Categories should be broad themes like:
        'philosophy', 'productivity', 'relationships', 'science', 'history', etc.""",
        max_turns=1,
    )

    async for message in query(
        prompt=f"Book: {book_title}\nHighlight: {highlight_text}",
        options=options
    ):
        if isinstance(message, ResultMessage):
            return parse_categories(message)
```

### Phase 2: Weekly Reading Digest

**Value:** Regular engagement and reflection prompts
**Complexity:** Medium
**Cost:** ~$0.01/month

**Implementation:**
- Cron job runs weekly
- Collects all highlights from past week
- Generates 3-5 sentence summary + reflection question
- Stores in database for UI display

### Phase 3: Related Highlight Discovery

**Value:** Surface connections between ideas across books
**Complexity:** Medium
**Cost:** ~$0.08/month

**Implementation:**
- On-demand API endpoint
- Uses semantic similarity + LLM for explanation
- Caches results to reduce redundant calls

### Phase 4: Book Recommendations

**Value:** Personalized reading suggestions
**Complexity:** Low
**Cost:** ~$0.003/month

**Implementation:**
- Monthly batch job
- Analyzes highlight themes and reading patterns
- Suggests 3-5 books with explanations

## Architecture

### Background Job Infrastructure

```
FastAPI App
    |
    +-- BackgroundTasks (built-in)
    |       |
    |       +-- Highlight categorization (on import)
    |
    +-- APScheduler or Celery
            |
            +-- Weekly digest cron
            +-- Monthly recommendations cron
```

### Database Schema Additions

```sql
-- Store AI-generated categories
ALTER TABLE highlights ADD COLUMN ai_categories JSON;
ALTER TABLE highlights ADD COLUMN categorized_at TIMESTAMP;

-- Store reading digests
CREATE TABLE reading_digests (
    id INTEGER PRIMARY KEY,
    week_start DATE NOT NULL,
    summary TEXT NOT NULL,
    reflection_question TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Store recommendations
CREATE TABLE book_recommendations (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT,
    reason TEXT NOT NULL,
    based_on_highlights JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Cost Tracking

```python
# Track costs for budget monitoring
async def track_agent_cost(feature: str, input_tokens: int, output_tokens: int):
    cost = (input_tokens * 0.0005 + output_tokens * 0.0025) / 1000
    await db.execute(
        "INSERT INTO agent_costs (feature, input_tokens, output_tokens, cost_usd, created_at) VALUES (?, ?, ?, ?, ?)",
        (feature, input_tokens, output_tokens, cost, datetime.now())
    )
```

## Risk Mitigation

### Cost Overruns
- **Hard monthly cap:** Disable features if budget exceeded
- **Per-feature limits:** Max requests per day/week
- **Alert at 80%:** Notify when approaching budget

### API Failures
- **Graceful degradation:** Features are additive, app works without them
- **Retry with backoff:** 3 retries with exponential backoff
- **Fallback:** Queue for later processing if API unavailable

### Quality Control
- **Confidence thresholds:** Only apply categorization if model is confident
- **Human override:** Users can edit/reject AI suggestions
- **Feedback loop:** Track user corrections for improvement

## Implementation Timeline

| Week | Deliverable |
|------|-------------|
| 1 | SDK integration + cost tracking infrastructure |
| 2 | Phase 1: Highlight auto-categorization |
| 3 | Phase 2: Weekly reading digest |
| 4 | Phase 3: Related highlight discovery |
| 5 | Phase 4: Book recommendations |
| 6 | Polish, testing, documentation |

## Success Metrics

1. **Cost efficiency:** Stay under $0.50/month for typical usage
2. **User engagement:** Increase in highlight views/interactions
3. **Categorization accuracy:** >80% user acceptance rate
4. **Discovery value:** Users click through to related highlights

## Open Questions

1. Should categorization run on import or as a batch job?
2. What's the right frequency for digests (weekly vs. monthly)?
3. Should we allow users to disable AI features?
4. How do we handle highlights in non-English languages?

## References

- [Claude Agent SDK Quickstart](https://platform.claude.com/docs/en/agent-sdk/quickstart)
- [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [SDK Demo Repository](https://github.com/anthropics/claude-agent-sdk-demos)
