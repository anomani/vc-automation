"""
Benchmark runner: tests both app methods (original API vs Agent SDK) with both models (Opus vs Sonnet).
Runs all 4 combinations, collects metrics, and prints a comparison table.

Usage:
    1. Start both servers:
       uvicorn app:app --port 8000
       uvicorn app_sdk:app --port 8001
    2. Run this script:
       python benchmark.py
"""

import asyncio
import json
import os
import sys
import time

import httpx

IDEA = (
    "An orchestration layer for ecommerce clients that integrates with Google's "
    "Universal Commerce Protocol (UCP) to streamline data management, identity "
    "verification, and payment processing.\n"
    "With the introduction of Google's Universal Commerce Protocol (UCP), ecommerce "
    "retailers face the challenge of integrating and orchestrating their data with "
    "this new standard. Retailers struggle with identity and payment solutions, as "
    "well as creating effective feedback loops for reporting. Current workarounds "
    "involve piecemeal solutions that lack cohesion and efficiency, leading to "
    "increased operational costs and missed opportunities for optimization.\n"
    "The platform would act as an orchestration layer providing:\n"
    "* Intent layer/parser that interprets customer intents from various data inputs\n"
    "* Seamless identity verification and payment processing integration\n"
    "* Comprehensive feedback loop and reporting tools for analytics"
)

TESTS = [
    {"label": "Original + Opus",  "port": 8000, "model": "claude-opus-4-6",            "method": "original"},
    {"label": "Original + Sonnet","port": 8000, "model": "claude-sonnet-4-5-20250929",  "method": "original"},
    {"label": "SDK + Opus",       "port": 8001, "model": "claude-opus-4-6",            "method": "sdk"},
    {"label": "SDK + Sonnet",     "port": 8001, "model": "claude-sonnet-4-5-20250929",  "method": "sdk"},
]

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "benchmark_reports")


async def run_test(test_config: dict) -> dict:
    label = test_config["label"]
    port = test_config["port"]
    model = test_config["model"]
    method = test_config["method"]

    url = f"http://localhost:{port}/generate-research"
    payload = {"idea": IDEA, "model": model}

    safe_label = label.lower().replace(" ", "_").replace("+", "")
    output_file = os.path.join(OUTPUT_DIR, f"{safe_label}.docx")

    print(f"\n{'='*60}")
    print(f"  STARTING: {label}")
    print(f"  URL: {url}")
    print(f"  Model: {model}")
    print(f"{'='*60}")

    start = time.time()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
            resp = await client.post(url, json=payload)

        elapsed = time.time() - start

        if resp.status_code != 200:
            # Try to parse error
            try:
                error_body = resp.json()
            except Exception:
                error_body = resp.text[:500]
            print(f"  ERROR [{resp.status_code}]: {error_body}")
            return {
                "label": label,
                "method": method,
                "model": model,
                "status": "FAILED",
                "error": str(error_body)[:100],
                "elapsed_seconds": round(elapsed, 1),
                "cost_usd": None,
                "num_turns": None,
                "input_tokens": None,
                "output_tokens": None,
                "file_size_kb": None,
            }

        # Check if response is JSON (fallback/no docx) or file
        content_type = resp.headers.get("content-type", "")

        if "application/json" in content_type:
            body = resp.json()
            metrics = body.get("metrics", {})
            print(f"  WARNING: {body.get('warning', 'JSON response (no docx)')}")
            return {
                "label": label,
                "method": method,
                "model": model,
                "status": "TEXT_ONLY",
                "elapsed_seconds": metrics.get("elapsed_seconds", round(elapsed, 1)),
                "cost_usd": metrics.get("cost_usd"),
                "num_turns": metrics.get("num_turns"),
                "input_tokens": metrics.get("input_tokens"),
                "output_tokens": metrics.get("output_tokens"),
                "file_size_kb": None,
            }

        # Save docx file
        with open(output_file, "wb") as f:
            f.write(resp.content)

        file_size_kb = round(len(resp.content) / 1024, 1)

        # Extract metrics from headers
        result = {
            "label": label,
            "method": method,
            "model": model,
            "status": "OK",
            "elapsed_seconds": float(resp.headers.get("X-Elapsed-Seconds", round(elapsed, 1))),
            "cost_usd": resp.headers.get("X-Cost-USD"),
            "num_turns": resp.headers.get("X-Num-Turns"),
            "input_tokens": resp.headers.get("X-Input-Tokens"),
            "output_tokens": resp.headers.get("X-Output-Tokens"),
            "file_size_kb": file_size_kb,
            "file": output_file,
        }

        # Convert numeric strings
        for key in ["cost_usd", "num_turns", "input_tokens", "output_tokens"]:
            if result[key] is not None and result[key] != "None":
                try:
                    result[key] = float(result[key]) if "." in str(result[key]) else int(result[key])
                except (ValueError, TypeError):
                    pass
            else:
                result[key] = None

        print(f"  DONE: {file_size_kb} KB, {result['elapsed_seconds']}s, ${result['cost_usd']}")
        return result

    except Exception as e:
        elapsed = time.time() - start
        print(f"  EXCEPTION: {e}")
        return {
            "label": label,
            "method": method,
            "model": model,
            "status": "ERROR",
            "error": str(e)[:100],
            "elapsed_seconds": round(elapsed, 1),
            "cost_usd": None,
            "num_turns": None,
            "input_tokens": None,
            "output_tokens": None,
            "file_size_kb": None,
        }


def print_table(results):
    """Print a formatted comparison table."""
    print("\n")
    print("=" * 100)
    print("  BENCHMARK RESULTS")
    print("=" * 100)

    # Header
    cols = [
        ("Test", 22),
        ("Status", 10),
        ("Time", 10),
        ("Cost", 10),
        ("Turns", 7),
        ("Input Tok", 11),
        ("Output Tok", 11),
        ("File KB", 9),
    ]

    header = " | ".join(name.ljust(width) for name, width in cols)
    print(f"\n  {header}")
    print(f"  {'-' * len(header)}")

    for r in results:
        elapsed = f"{r['elapsed_seconds']}s" if r.get("elapsed_seconds") else "—"
        cost = f"${r['cost_usd']}" if r.get("cost_usd") is not None else "—"
        turns = str(r.get("num_turns", "—")) if r.get("num_turns") is not None else "—"
        input_tok = f"{r.get('input_tokens', 0):,}" if r.get("input_tokens") else "—"
        output_tok = f"{r.get('output_tokens', 0):,}" if r.get("output_tokens") else "—"
        file_kb = f"{r['file_size_kb']}" if r.get("file_size_kb") else "—"

        row = [
            r["label"].ljust(cols[0][1]),
            r["status"].ljust(cols[1][1]),
            elapsed.ljust(cols[2][1]),
            cost.ljust(cols[3][1]),
            turns.ljust(cols[4][1]),
            input_tok.ljust(cols[5][1]),
            output_tok.ljust(cols[6][1]),
            file_kb.ljust(cols[7][1]),
        ]
        print(f"  {' | '.join(row)}")

    print(f"\n  {'=' * len(header)}")

    # Save results to JSON
    results_file = os.path.join(OUTPUT_DIR, "benchmark_results.json")
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_file}")
    print(f"  Reports saved to: {OUTPUT_DIR}/")


async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Check servers are running
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        for port in [8000, 8001]:
            try:
                resp = await client.get(f"http://localhost:{port}/docs")
                if resp.status_code == 200:
                    print(f"  Port {port}: OK")
                else:
                    print(f"  Port {port}: responded with {resp.status_code}")
                    sys.exit(1)
            except Exception:
                print(f"  Port {port}: NOT RUNNING")
                print(f"\n  Please start both servers first:")
                print(f"    uvicorn app:app --port 8000")
                print(f"    uvicorn app_sdk:app --port 8001")
                sys.exit(1)

    # Run tests sequentially (to avoid resource contention and rate limits)
    results = []
    for test in TESTS:
        result = await run_test(test)
        results.append(result)

    print_table(results)


if __name__ == "__main__":
    asyncio.run(main())
