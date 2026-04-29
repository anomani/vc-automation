# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

Copy `.env.example` to `.env` and populate:
- `ANTHROPIC_API_KEY` — Anthropic API key
- `RESEARCH_SKILL_ID` — Custom skill ID for VC research (format: `skill_...`)

Install dependencies (using a virtual environment):
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Activate the venv (`source venv/bin/activate`) at the start of each new terminal session.

## Running

```bash
uvicorn app:app --reload
```

The API runs at `http://localhost:8000`. Send a POST request to generate a report:
```bash
curl -X POST http://localhost:8000/generate-research \
  -H "Content-Type: application/json" \
  -d '{"idea": "your business idea here"}' \
  --output report.docx
```

## Architecture

Single-file FastAPI app (`app.py`) with one endpoint: `POST /generate-research`.

**Flow:**
1. Receives a business idea string
2. Calls `client.beta.messages.create` with a container config that includes two custom skills (research + docx generation) and two tools (web search + code execution)
3. Handles the `pause_turn` stop reason in a loop (up to 15 continuation turns) — required because long-running skill operations cause Claude to pause mid-generation
4. Scans all assistant turns for `bash_code_execution_tool_result` blocks to find generated file IDs
5. Retrieves the `.docx` file via the Files API (`client.beta.files`) and returns it as a `FileResponse`

**Beta features in use:** `code-execution-2025-08-25`, `skills-2025-10-02`, `files-api-2025-04-14`

**Model:** `claude-sonnet-4-5-20250929`

The `pause_turn` loop is the core complexity: each continuation must reuse the same `container.id` from the previous response so Claude resumes in the same execution context.
