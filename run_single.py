#!/usr/bin/env python3
"""
Single Contract Review Script
Reads a specific PDF and prints the review report to stdout.
Designed to be called by the Streamlit UI via subprocess.

Now uses the local Ollama backend instead of Google Gemini / Google ADK.
"""

import asyncio
import sys

# Force UTF-8 output so Unicode characters (emojis, checkmarks) don't crash
# on Windows consoles that default to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import argparse
from pathlib import Path

from src.tools.pdf_parser import DocumentParser
from src.agent import contract_review_workflow
from src.ollama_client import check_ollama_health


async def process_contract(contract_path: Path):
    """Process a single contract PDF and print the review report to stdout."""

    # ── Health check ────────────────────────────────────────────────────────
    health = check_ollama_health()
    if not health["ok"]:
        print(f"\n❌ Ollama Error: {health['error']}", flush=True)
        print(f"\n💡 How to fix:\n{health['hint']}", flush=True)
        sys.exit(1)

    # ── PDF extraction ───────────────────────────────────────────────────────
    print("Agents are analyzing the contract...", flush=True)

    parser = DocumentParser()
    try:
        parsed = parser.parse(str(contract_path))
        contract_text = parsed["text"]
        print(f"✓ PDF Parsed: {parsed['metadata']['pages']} pages found.", flush=True)
    except Exception as exc:
        print(f"Error parsing PDF: {exc}", flush=True)
        sys.exit(1)

    # Expose contract text to the Streamlit UI
    print("\n---CONTRACT_TEXT_START---", flush=True)
    print(contract_text, flush=True)
    print("---CONTRACT_TEXT_END---\n", flush=True)

    print("🤖 Agents are analyzing the contract...", flush=True)

    # ── Run the pipeline ─────────────────────────────────────────────────────
    print("\n---REPORT_START---\n", flush=True)

    try:
        report = await contract_review_workflow.run(
            contract_text=contract_text,
            filename=parsed["metadata"]["filename"],
            pages=parsed["metadata"]["pages"],
        )
        # Print the report to stdout so app.py can capture it
        print(report, flush=True)

    except Exception as exc:
        print(f"\nAgent Error: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="Review a single contract PDF")
    arg_parser.add_argument("pdf_path", help="Path to the PDF file")
    args = arg_parser.parse_args()

    asyncio.run(process_contract(Path(args.pdf_path)))
