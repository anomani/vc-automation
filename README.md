# vc-automation

Automated VC discovery research as a service. Submit a startup idea, get back a fully-formatted `.docx` discovery document — market sizing, competitive landscape, regulatory analysis, scoring, and a VALIDATE/PASS recommendation — produced by Claude with web research and document generation skills.

## What it does

A FastAPI server exposes a single endpoint that, given a one-line business idea, drives Claude through a 45–60 minute research session and returns a polished Word document. The agent:

1. Reads a custom **vc-research** skill that defines the discovery methodology (6 phases: understanding, market sizing, competitive intel, regulatory, problem validation, synthesis).
2. Uses **web search** extensively to source market data, competitor info, funding rounds, and regulatory details.
3. Calculates Conservative / Base / Aggressive TAM scenarios with documented assumptions and evidence quality tags.
4. Produces a structured discovery doc with ~13 sections (opportunity overview, wedge design, scoring, decision trace, pre-mortem, etc.).
5. Uses the **docx** skill via the Code Execution tool to render the report as a `.docx` and returns it as a file response.

The output is decision-grade analysis intended for a venture studio reviewing many ideas per week.

## Architecture

Two server implementations are included:

- **`app.py`** — Direct Anthropic Messages API. Handles the long-running session via a `pause_turn` loop (up to 15 continuations), reusing the same container ID so the agent resumes in the same execution context. Retrieves the generated `.docx` via the Files API.
- **`app_sdk.py`** — Same flow built on the Claude Agent SDK with `ClaudeSDKClient`, which handles turn management automatically and streams assistant messages.

**Beta features:** `code-execution-2025-08-25`, `skills-2025-10-02`, `files-api-2025-04-14`

**Default model:** `claude-opus-4-6` (configurable per request)

### Custom skills

- `.claude/skills/vc-research/` — Methodology and document template that the agent loads to perform structured research. The full template (~13 mandatory sections, scoring rubric, gate checks) lives in `references/methodology.md`.
- `docx` — Anthropic's built-in document generation skill, used to render the final report.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in:

- `ANTHROPIC_API_KEY` — your Anthropic API key
- `RESEARCH_SKILL_ID` — the uploaded `vc-research` custom skill ID (format: `skill_...`)

## Running

```bash
uvicorn app:app --reload
# or, for the Agent SDK version:
uvicorn app_sdk:app --reload
```

Generate a report:

```bash
curl -X POST http://localhost:8000/generate-research \
  -H "Content-Type: application/json" \
  -d '{"idea": "AI-powered compliance copilot for mid-market fintechs"}' \
  --output report.docx
```

Optional `model` field in the request body overrides the default (e.g. `"claude-sonnet-4-5-20250929"`).

The response is the `.docx` file. Run metadata (elapsed seconds, turn count, token usage, USD cost) is returned in `X-*` response headers.

## Endpoints

- `POST /generate-research` — Submit `{ "idea": "...", "model": "..." }`. Returns a `.docx` file (or JSON with `report` text and a `warning` if document generation failed).
- `GET /skills` — Lists custom skills available on the account (only on `app.py`).

## Files

| File | Purpose |
|------|---------|
| `app.py` | FastAPI server using the Messages API directly |
| `app_sdk.py` | FastAPI server using the Claude Agent SDK |
| `benchmark.py` | Benchmark harness for comparing models / configurations |
| `request.json` | Sample request payload |
| `.claude/skills/vc-research/` | Custom research skill (methodology + template) |
