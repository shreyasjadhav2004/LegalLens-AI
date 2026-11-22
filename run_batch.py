#!/usr/bin/env python3
"""
Batch Contract Review Script
Processes all PDFs in input_contracts/ and prints reports to stdout.

Now uses the local Ollama backend instead of Google Gemini / Google ADK.
"""

import asyncio
import sys
from pathlib import Path

from src.tools.pdf_parser import DocumentParser
from src.agent import contract_review_workflow
from src.ollama_client import check_ollama_health


async def process_contract(contract_path: Path):
    """Process a single contract PDF and print the review report."""

    print(f"\n{'='*80}")
    print(f"Processing: {contract_path.name}")
    print(f"{'='*80}\n")

    parser = DocumentParser()
    try:
        parsed = parser.parse(str(contract_path))
        contract_text = parsed["text"]
        print(f"✓ Parsed PDF: {parsed['metadata']['pages']} pages\n")
    except Exception as exc:
        print(f"✗ Error parsing PDF: {exc}\n")
        return

    print("🤖 Running Ollama Multi-Agent Review...\n")

    try:
        report = await contract_review_workflow.run(
            contract_text=contract_text,
            filename=parsed["metadata"]["filename"],
            pages=parsed["metadata"]["pages"],
        )
        print(report)

    except Exception as exc:
        print(f"\n✗ Error during agent processing: {exc}")
        import traceback
        traceback.print_exc()


async def main():
    # ── Health check ─────────────────────────────────────────────────────────
    health = check_ollama_health()
    if not health["ok"]:
        print(f"\n❌ Ollama Error: {health['error']}")
        print(f"\n💡 How to fix:\n{health['hint']}")
        sys.exit(1)

    input_dir = Path("input_contracts")
    pdf_files = list(input_dir.glob("*.pdf"))

    if not pdf_files:
        print("\n⚠️  No PDF files found in input_contracts/")
        print("Place your contract PDFs there and run again.\n")
        return

    for pdf_file in pdf_files:
        await process_contract(pdf_file)
        print(f"\n{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
