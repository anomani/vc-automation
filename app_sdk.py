import os
import tempfile
import time

# Allow running inside a Claude Code session
os.environ.pop("CLAUDECODE", None)

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)

load_dotenv()

app = FastAPI()

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

SYSTEM_PROMPT = """You are a venture capital analyst. Use the available skills to conduct comprehensive research on the given business idea and produce a Discovery Document as a .docx file.

Use the vc-research skill for research methodology and the docx-generation skill to create the final report. Save the .docx file to /tmp/discovery_report.docx."""


class ResearchRequest(BaseModel):
    idea: str
    model: str = "claude-opus-4-6"


@app.post("/generate-research")
async def generate_research(request: ResearchRequest):
    model = request.model
    start_time = time.time()

    # Clean up any previous report
    docx_path = "/tmp/discovery_report.docx"
    if os.path.exists(docx_path):
        os.remove(docx_path)

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=["WebSearch", "WebFetch", "Bash", "Read", "Write", "Skill"],
        permission_mode="bypassPermissions",
        model=model,
        max_turns=30,
        cwd=PROJECT_DIR,
        setting_sources=["project"],
    )

    prompt = (
        f"Conduct comprehensive market research on the following business idea "
        f"and produce a Discovery Document as a .docx file:\n\n{request.idea}"
    )

    report_text_parts = []
    sdk_cost = None
    sdk_turns = None

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            report_text_parts.append(block.text)
                            print(f"[text] {block.text[:100]}...")
                        elif isinstance(block, ToolUseBlock):
                            print(f"[tool_use] {block.name}")

                elif isinstance(message, ResultMessage):
                    sdk_cost = message.total_cost_usd
                    sdk_turns = message.num_turns
                    print(f"[result] turns={message.num_turns} cost=${message.total_cost_usd}")

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent SDK error: {e}")

    elapsed = time.time() - start_time

    metrics = {
        "model": model,
        "elapsed_seconds": round(elapsed, 1),
        "num_turns": sdk_turns or 0,
        "cost_usd": round(sdk_cost, 4) if sdk_cost else None,
    }
    print(f"=== Metrics: {metrics} ===")

    # Check if .docx was generated
    if os.path.exists(docx_path):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
        with open(docx_path, "rb") as src:
            tmp.write(src.read())
        tmp.close()

        headers = {
            "X-Model": model,
            "X-Elapsed-Seconds": str(metrics["elapsed_seconds"]),
            "X-Num-Turns": str(metrics["num_turns"]),
            "X-Cost-USD": str(metrics["cost_usd"]),
        }

        return FileResponse(
            path=tmp.name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="discovery_report.docx",
            headers=headers,
        )

    # Fallback: return text report
    report = "\n\n".join(report_text_parts)
    if report:
        return {
            "report": report,
            "docx": None,
            "warning": "No .docx file was generated — returning text output.",
            "metrics": metrics,
        }

    raise HTTPException(status_code=500, detail="No output was generated.")
