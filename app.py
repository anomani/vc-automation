import os
import tempfile
import time

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

load_dotenv()

app = FastAPI()
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

print("=== VC Automation Config ===")
print(f"  RESEARCH_SKILL_ID : {os.environ.get('RESEARCH_SKILL_ID', '(not set)')}")
print(f"  ANTHROPIC_API_KEY : {os.environ['ANTHROPIC_API_KEY'][:12]}...")
print("================================")

RESEARCH_SKILL_ID = os.environ["RESEARCH_SKILL_ID"]

BETAS = ["code-execution-2025-08-25", "skills-2025-10-02", "files-api-2025-04-14"]

# Pricing per million tokens
MODEL_PRICING = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0},
}

SYSTEM_PROMPT = """You are a venture capital analyst. Use the research skill and web search to produce a complete Discovery Document on the given business idea.

Follow the methodology and document structure defined in the vc-discovery skill exactly. The document MUST include every section — do not skip or abbreviate any:

1. Cover page (title, date, overall decision)
2. Opportunity Overview (What Excites Us / What Gives Us Pause table)
3. Summary: Problem Statement, Company Description, Product Features, Critical Unknowns, Wedge Design
4. Market Overview (with Evidence rating)
5. Market Size (Conservative/Base/Aggressive table with N, N Evidence, ACV, ACV Evidence, Penetration, Pen Evidence, Total) + Sources by Scenario + Key Assumptions (with Why it matters, Evidence, Validation test, Kill threshold) + Market Size Conclusion table
6. Competitive Landscape: Direct Competitors table, Adjacent Competitors table, Incumbents table, Feature-by-Feature Comparison narrative, Funding Analysis
7. Regulatory Environment: Current Regulations table, Compliance Costs/Burden, Upcoming Changes, Regulatory Moat or Risk
8. Pre-Mortem (Why This Fails) table with Failure Mode, Earliest Signal, Mitigation, Fatal?
9. Scoring Analysis 1-10 table (Problem Clarity, Solution Fit, Market Potential, Competitive Landscape, GTM, Execution Risk, Studio Fit)
10. Decision Trace: Gates Passed, Gates Failed, Strongest Reason to Proceed, Strongest Reason to Kill, Evidence Required to Change Decision
11. Overall Decision (PASS / VALIDATE / INVEST) with justification
12. Next Step Recommendation: 3 Concrete Reasons, What New Evidence Would Justify Reconsideration
13. Portfolio Conflict Check

Use web search extensively — search multiple times for market data, each competitor, regulatory details, and funding information. Cite specific numbers and sources throughout.

Once the full document is complete, use the docx skill to format and save it as a .docx file to /tmp/discovery_report.docx."""


def build_skills():
    return [
        {"type": "custom", "skill_id": RESEARCH_SKILL_ID, "version": "latest"},
        {"type": "anthropic", "skill_id": "docx", "version": "latest"},
    ]


def extract_file_ids(content):
    file_ids = []
    for item in content:
        if getattr(item, "type", None) == "bash_code_execution_tool_result":
            result = item.content
            if getattr(result, "type", None) == "bash_code_execution_result":
                for f in result.content:
                    if hasattr(f, "file_id"):
                        file_ids.append(f.file_id)
    return file_ids


def calc_cost(model, input_tokens, output_tokens):
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-5-20250929"])
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


class ResearchRequest(BaseModel):
    idea: str
    model: str = "claude-opus-4-6"


@app.get("/skills")
async def list_skills():
    try:
        skills = client.beta.skills.list(betas=["skills-2025-10-02"])
        return {"skills": [s.model_dump() for s in skills.data]}
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Could not list skills: {e}")


@app.post("/generate-research")
async def generate_research(request: ResearchRequest):
    model = request.model
    start_time = time.time()
    total_input_tokens = 0
    total_output_tokens = 0
    num_turns = 0

    messages = [
        {
            "role": "user",
            "content": f"Conduct comprehensive market research on the following business idea and produce a Discovery Document:\n\n{request.idea}",
        }
    ]

    container_config = {"skills": build_skills()}

    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16384,
            betas=BETAS,
            system=SYSTEM_PROMPT,
            container=container_config,
            messages=messages,
            tools=[
                {"type": "web_search_20250305", "name": "web_search"},
                {"type": "code_execution_20250825", "name": "code_execution"},
            ],
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {e}")

    total_input_tokens += response.usage.input_tokens
    total_output_tokens += response.usage.output_tokens
    num_turns += 1

    # Handle pause_turn loop for long-running skill operations
    for _ in range(15):
        if response.stop_reason != "pause_turn":
            break

        messages.append({"role": "assistant", "content": response.content})
        container_config = {"id": response.container.id, "skills": build_skills()}

        try:
            response = client.beta.messages.create(
                model=model,
                max_tokens=16384,
                betas=BETAS,
                system=SYSTEM_PROMPT,
                container=container_config,
                messages=messages,
                tools=[
                    {"type": "web_search_20250305", "name": "web_search"},
                    {"type": "code_execution_20250825", "name": "code_execution"},
                ],
            )
        except anthropic.APIError as e:
            raise HTTPException(status_code=502, detail=f"Claude API error: {e}")

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        num_turns += 1

    elapsed = time.time() - start_time
    cost = calc_cost(model, total_input_tokens, total_output_tokens)

    # Build metrics dict
    metrics = {
        "model": model,
        "elapsed_seconds": round(elapsed, 1),
        "num_turns": num_turns,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "cost_usd": round(cost, 4),
    }
    print(f"=== Metrics: {metrics} ===")

    # Collect file IDs from all turns
    file_ids = []
    for msg in messages:
        if msg["role"] == "assistant":
            file_ids.extend(extract_file_ids(msg["content"]))
    file_ids.extend(extract_file_ids(response.content))

    all_content = []
    for msg in messages:
        if msg["role"] == "assistant":
            all_content.extend(msg["content"])
    all_content.extend(response.content)

    if not file_ids:
        all_text = []
        for item in all_content:
            if hasattr(item, "text") and item.text:
                all_text.append(item.text)
        report = max(all_text, key=len) if all_text else ""
        return {
            "report": report,
            "docx": None,
            "warning": "No .docx file was generated — returning text output.",
            "metrics": metrics,
        }

    # Prefer .docx, fall back to first file
    target_file_id = file_ids[0]
    for file_id in file_ids:
        meta = client.beta.files.retrieve_metadata(
            file_id=file_id, betas=["files-api-2025-04-14"]
        )
        if meta.filename.endswith(".docx"):
            target_file_id = file_id
            break

    meta = client.beta.files.retrieve_metadata(
        file_id=target_file_id, betas=["files-api-2025-04-14"]
    )
    content = client.beta.files.download(
        file_id=target_file_id, betas=["files-api-2025-04-14"]
    )

    suffix = os.path.splitext(meta.filename)[1] or ".docx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    content.write_to_file(tmp.name)

    headers = {
        "X-Model": model,
        "X-Elapsed-Seconds": str(metrics["elapsed_seconds"]),
        "X-Num-Turns": str(metrics["num_turns"]),
        "X-Input-Tokens": str(metrics["input_tokens"]),
        "X-Output-Tokens": str(metrics["output_tokens"]),
        "X-Total-Tokens": str(metrics["total_tokens"]),
        "X-Cost-USD": str(metrics["cost_usd"]),
    }

    return FileResponse(
        path=tmp.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=meta.filename,
        headers=headers,
    )
