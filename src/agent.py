"""
Contract Review Multi-Agent Pipeline – Ollama Backend
======================================================
This module replicates the original 5-stage multi-agent workflow that was
built with Google ADK, but drives every LLM call through a locally running
Ollama model instead of the Gemini API.

The architecture is preserved:
  Stage 1 – Intake Agent        (was ADK Sequential Agent)
  Stage 2 – Clause Extractor    (was ADK Loop Agent, max 10 iterations)
  Stage 3 – Risk Scorer         (was ADK Parallel Agent)
  Stage 4 – Playbook Comparator (was ADK Sequential Agent + MCP)
  Stage 5 – Report Generator    (was ADK Sequential Agent)

Why no Google ADK?
  google.adk.agents.Agent only supports Google-hosted models (Gemini).
  There is no official adapter for Ollama as of the migration date.
  Rather than wrap ADK around an incompatible backend, we implement the
  same orchestration logic directly so the workflow remains identical.

Tool functions (score_clause_risk, compare_to_playbook, format_markdown_report)
are kept with the same signatures so app.py and run_single.py can still
reference them and the agent trace output matches the original progress
parsing in app.py.
"""

import json
import sys
from typing import Optional

from .config import OLLAMA_MODEL
from .ollama_client import generate, generate_stream_collect, extract_json
from .tools.pdf_parser import DocumentParser
from .tools.risk_matrix import RiskMatrix
from .mcp.playbook_server import PlaybookServer

# ---------------------------------------------------------------------------
# Shared services (unchanged from original)
# ---------------------------------------------------------------------------

pdf_parser = DocumentParser()
risk_matrix = RiskMatrix()
playbook_server = PlaybookServer("data/playbooks")


# ---------------------------------------------------------------------------
# Tool functions (preserved signatures so app.py progress tracking works)
# ---------------------------------------------------------------------------

def analyze_contract_metadata(contract_text: str, filename: str, pages: int) -> dict:
    """
    Extracts high-level metadata from a contract.
    Called internally by the intake agent stage.
    """
    print("\n🔍 IntakeAgent: Analyzing contract metadata...")
    return {
        "status": "tool_called",
        "message": "Contract metadata extraction initiated",
    }


def extract_clause_from_section(
    section_title: str, section_text: str, contract_type: str
) -> dict:
    """
    Extracts structured clause information from a contract section.
    Called internally by the clause extraction stage.
    """
    print(f"\n📄 ClauseExtractor: Extracting from section '{section_title}'...")
    return {
        "status": "clause_extraction_initiated",
        "section": section_title,
    }


def score_clause_risk(clause_type: str, clause_text: str, key_terms: dict) -> dict:
    """
    Scores the risk level of a specific clause using the risk matrix.
    """
    print(f"\n⚠️  RiskScorer: Scoring risk for '{clause_type}' clause...")
    risk_result = risk_matrix.evaluate_risk(clause_type, key_terms)
    return risk_result


def compare_to_playbook(
    clause_type: str, actual_value: str, contract_type: str
) -> dict:
    """
    Compares an actual contract term against company playbook standards.
    """
    print(f"\n📚 PlaybookAgent: Comparing '{clause_type}' to standards...")

    normalized_type = contract_type.lower().replace(" ", "_")
    if "employment" in normalized_type:
        normalized_type = "employment_agreement"
    elif "saas" in normalized_type:
        normalized_type = "saas_agreement"
    elif "nda" in normalized_type or "non-disclosure" in normalized_type:
        normalized_type = "nda"
    elif "msa" in normalized_type or "master_services" in normalized_type:
        normalized_type = "msa"

    comparison = playbook_server.compare_term(normalized_type, clause_type, actual_value)
    return comparison


def format_markdown_report(report_data: dict) -> str:
    """
    Signals that the final Markdown report has been generated.
    """
    print("\n📝 ReportGenerator: Formatting final report...")
    return "Report generation completed. The markdown report should be in the agent's response."


# ---------------------------------------------------------------------------
# STAGE 1 – Intake Agent
# ---------------------------------------------------------------------------

INTAKE_SYSTEM = """You are a legal contract intake specialist. Analyze the contract and extract metadata.

CRITICAL RULES:
- Respond ONLY with valid JSON, no extra text, no markdown fences.
- Use null for unknown fields, not empty strings.
- Dates must be YYYY-MM-DD or null.

Return this exact JSON structure:
{
  "contract_type": "string",
  "contract_subtype": "string or null",
  "parties": {
    "provider": "string",
    "customer": "string"
  },
  "effective_date": "YYYY-MM-DD or null",
  "term_length": "string",
  "expiration_date": "YYYY-MM-DD or null",
  "auto_renewal": true or false,
  "renewal_notice_period": "string or null",
  "jurisdiction": "string or null",
  "governing_law": "string or null",
  "estimated_value": "string or null",
  "document_quality": {
    "complete": true or false,
    "signed": true or false,
    "issues": []
  },
  "confidence": 0.85
}"""


def run_intake_agent(contract_text: str, filename: str, pages: int) -> dict:
    """Stage 1: Classify and extract contract metadata."""
    print("contract_intake_agent > running intake analysis", flush=True)

    prompt = f"""Analyze this contract and return JSON metadata only.

CONTRACT FILE: {filename}
PAGES: {pages}

CONTRACT TEXT:
{contract_text[:8000]}

Return ONLY the JSON object, nothing else."""

    raw = generate(prompt, system=INTAKE_SYSTEM, temperature=0.1)
    result = extract_json(raw)

    # Safely handle list or non-dict responses
    if isinstance(result, list):
        if result and isinstance(result[0], dict):
            result = result[0]
        else:
            result = {}

    if not isinstance(result, dict) or result.get("parse_error"):
        print("⚠️  Intake agent returned non-JSON; using defaults.", flush=True)
        result = {
            "contract_type": "Unknown",
            "parties": {"provider": "Unknown", "customer": "Unknown"},
            "confidence": 0.3,
        }

    print(f"✅ contract_intake_agent > Contract type: {result.get('contract_type', 'Unknown')}", flush=True)
    return result


# ---------------------------------------------------------------------------
# STAGE 2 – Clause Extraction (Loop Agent – up to 10 sections)
# ---------------------------------------------------------------------------

CLAUSE_SYSTEM = """You are a legal clause extraction specialist. Extract structured clause information.

CRITICAL RULES:
- Respond ONLY with valid JSON, no extra text, no markdown fences.
- Split distinct concepts into separate clause entries (e.g., role vs salary vs start date = 3 entries).
- For SaaS: license_grant, payment_terms, term_and_termination, warranties, limitation_of_liability, indemnification, data_privacy, service_level_agreement, confidentiality, dispute_resolution, auto_renewal
- For Employment: position_and_duties, compensation_and_benefits, non_compete, non_solicitation, confidentiality, ip_assignment, termination_conditions, severance

Return this exact JSON structure:
{
  "clauses": [
    {
      "clause_type": "string",
      "section_title": "string",
      "text": "string",
      "key_terms": {},
      "confidence": 0.85
    }
  ]
}"""


def run_clause_extraction_agent(
    contract_text: str, contract_type: str, max_iterations: int = 10
) -> list[dict]:
    """Stage 2: Extract all clauses from the contract (loop over sections)."""

    # Split contract into sections for iterative processing
    lines = contract_text.split("\n")
    sections = []
    current_section = {"title": "Introduction", "text": ""}

    for line in lines:
        stripped = line.strip()
        is_header = (
            (stripped.isupper() and 5 < len(stripped) < 100)
            or any(
                stripped.startswith(f"{n}.")
                for n in range(1, 25)
            )
            or stripped.lower().startswith(("section", "article", "clause"))
        )
        if is_header and stripped:
            if current_section["text"].strip():
                sections.append(current_section)
            current_section = {"title": stripped, "text": ""}
        else:
            current_section["text"] += line + "\n"

    if current_section["text"].strip():
        sections.append(current_section)

    # If no sections found, treat the whole document as one section
    if not sections:
        sections = [{"title": "Full Contract", "text": contract_text}]

    all_clauses: list[dict] = []
    iterations = 0

    for section in sections[:max_iterations]:
        iterations += 1
        print(
            f"clause_extraction_agent > iteration {iterations}: processing '{section['title']}'",
            flush=True,
        )
        print(f"📄 ClauseExtractor: Extracting from section '{section['title']}'...", flush=True)

        section_text = section["text"].strip()
        if len(section_text) < 30:
            continue

        prompt = f"""Extract clauses from this contract section. Contract type: {contract_type}

SECTION: {section['title']}
TEXT:
{section_text[:3000]}

Return ONLY the JSON object with a "clauses" array."""

        raw = generate(prompt, system=CLAUSE_SYSTEM, temperature=0.1)
        result = extract_json(raw)

        if isinstance(result, list):
            clauses = result
        elif isinstance(result, dict):
            clauses = result.get("clauses", [])
        else:
            clauses = []

        if isinstance(clauses, list):
            for c in clauses:
                if isinstance(c, dict):
                    all_clauses.append(c)

    print(f"✅ clause_extraction_agent > extracted {len(all_clauses)} clauses", flush=True)
    return all_clauses


# ---------------------------------------------------------------------------
# STAGE 3 – Risk Scoring (Parallel Agent – all clauses, using risk matrix)
# ---------------------------------------------------------------------------

RISK_SYSTEM = """You are a legal risk assessment specialist. Evaluate the risk of a contract clause.

CRITICAL RULES:
- Respond ONLY with valid JSON, no extra text, no markdown fences.
- Risk levels: critical (9-10), high (7-8), medium (4-6), low (1-3)

Return this exact JSON structure:
{
  "clause_id": "string",
  "risk_level": "critical|high|medium|low",
  "risk_score": 5,
  "risk_factors": [
    {
      "factor": "string",
      "description": "string",
      "severity": "string",
      "impact": "string"
    }
  ],
  "recommendation": "string"
}"""


def run_risk_scoring_agent(clauses: list[dict]) -> list[dict]:
    """Stage 3: Score risk for all extracted clauses."""
    scored_clauses: list[dict] = []

    for i, clause in enumerate(clauses):
        clause_type = clause.get("clause_type", "unknown")
        clause_text = clause.get("text", "")
        key_terms = clause.get("key_terms", {})

        print(f"risk_scoring_agent > scoring clause {i+1}/{len(clauses)}: {clause_type}", flush=True)
        print(f"⚠️  RiskScorer: Scoring risk for '{clause_type}' clause...", flush=True)

        # First use the deterministic risk matrix
        matrix_result = risk_matrix.evaluate_risk(clause_type, key_terms)

        # Then enrich with LLM analysis
        prompt = f"""Assess the legal risk of this contract clause.

CLAUSE TYPE: {clause_type}
CLAUSE TEXT:
{clause_text[:1500]}

KEY TERMS: {json.dumps(key_terms, indent=2)}
MATRIX RESULT: {json.dumps(matrix_result, indent=2)}

Return ONLY the JSON risk assessment object."""

        raw = generate(prompt, system=RISK_SYSTEM, temperature=0.1)
        llm_result = extract_json(raw)

        if isinstance(llm_result, list):
            if llm_result and isinstance(llm_result[0], dict):
                llm_result = llm_result[0]
            else:
                llm_result = {}

        if not isinstance(llm_result, dict) or llm_result.get("parse_error"):
            # Fall back to matrix result
            scored = {
                "clause_id": f"clause_{i+1}_{clause_type}",
                "risk_level": matrix_result.get("risk_level", "low"),
                "risk_score": matrix_result.get("risk_score", 1),
                "risk_factors": matrix_result.get("risk_factors", []),
                "recommendation": "Review this clause carefully.",
            }
        else:
            # Merge matrix factors into LLM result
            llm_result.setdefault("clause_id", f"clause_{i+1}_{clause_type}")
            if matrix_result.get("risk_factors"):
                existing = llm_result.get("risk_factors", [])
                if isinstance(existing, list):
                    llm_result["risk_factors"] = existing + matrix_result["risk_factors"]
                else:
                    llm_result["risk_factors"] = matrix_result["risk_factors"]
            scored = llm_result

        scored_clause = {**clause, "risk_assessment": scored}
        scored_clauses.append(scored_clause)

    print(f"✅ risk_scoring_agent > {len(scored_clauses)} clauses scored", flush=True)
    return scored_clauses


# ---------------------------------------------------------------------------
# STAGE 4 – Playbook Comparison
# ---------------------------------------------------------------------------

def run_playbook_comparison_agent(
    scored_clauses: list[dict], contract_type: str
) -> list[dict]:
    """Stage 4: Compare each clause against the company playbook standards."""
    print("playbook_comparison_agent > starting playbook comparison", flush=True)

    compared_clauses: list[dict] = []

    for clause in scored_clauses:
        clause_type = clause.get("clause_type", "unknown")
        clause_text = clause.get("text", "")

        print(f"📚 PlaybookAgent: Comparing '{clause_type}' to standards...", flush=True)

        comparison = compare_to_playbook(clause_type, clause_text, contract_type)
        compared_clause = {**clause, "playbook_comparison": comparison}
        compared_clauses.append(compared_clause)

    print(f"✅ playbook_comparison_agent > {len(compared_clauses)} clauses compared", flush=True)
    return compared_clauses


# ---------------------------------------------------------------------------
# STAGE 5 – Report Generator
# ---------------------------------------------------------------------------

REPORT_SYSTEM = """You are a legal contract reviewer. Write a contract review report in Markdown.

RULES (follow exactly):
- Start with # Contract Review Report as the very first line.
- NO conversational intro. NO code fences. Raw markdown only.
- Be concise. Aim for 300-500 words total.

Sections to include:
1. # Contract Review Report: [Type] – [Party]
2. ## Executive Summary (2 short paragraphs)
3. ## Critical Issues ❌ (bullet list, skip if none)
4. ## High-Priority Issues ⚠️ (bullet list, skip if none)
5. ## Acceptable Terms ✅ (bullet list)
6. ## Negotiation Strategy (3-5 bullet points)
7. ## Clause Summary (markdown table: Clause | Risk | Recommendation)

Use ❌ ⚠️ ✅ emoji. Be specific and actionable."""


def run_report_generator_agent(
    intake_result: dict,
    compared_clauses: list[dict],
    filename: str,
) -> str:
    """Stage 5: Generate the final Markdown report using streaming to avoid timeout."""
    print("report_generator_agent > generating final report", flush=True)
    print("\n📝 ReportGenerator: Formatting final report...", flush=True)

    # Build a compact per-clause summary (keep it small to fit in phi3's context window)
    clause_lines = []
    for c in compared_clauses:
        ra = c.get("risk_assessment", {})
        risk  = ra.get("risk_level", "low").upper()
        score = ra.get("risk_score", 1)
        rec   = ra.get("recommendation", "Review carefully.")[:120]
        ctype = c.get("clause_type", "unknown")
        preview = c.get("text", "")[:100].replace("\n", " ")
        clause_lines.append(f"- {ctype} | {risk} ({score}/10) | {rec} | Text: {preview}")

    clauses_text = "\n".join(clause_lines)

    prompt = (
        f"Write a contract review report for this contract.\n\n"
        f"FILE: {filename}\n"
        f"TYPE: {intake_result.get('contract_type', 'Unknown')}\n"
        f"PARTIES: {intake_result.get('parties', {}).get('provider', '?')} / "
        f"{intake_result.get('parties', {}).get('customer', '?')}\n"
        f"GOVERNING LAW: {intake_result.get('governing_law', 'Unknown')}\n"
        f"TERM: {intake_result.get('term_length', 'Unknown')}\n\n"
        f"CLAUSES ANALYZED:\n{clauses_text}\n\n"
        f"Start with: # Contract Review Report"
    )

    # Use streaming so we never hit a hard wall-clock timeout.
    # Tokens are collected as they arrive; a per-token timeout of 90s
    # catches a truly frozen model without cutting off long generations.
    print("report_generator_agent > streaming report tokens...", flush=True)
    report = generate_stream_collect(
        prompt,
        system=REPORT_SYSTEM,
        temperature=0.2,
        token_timeout=90,
        print_progress=True,
    )

    # Strip any accidental code fences
    import re
    report = re.sub(r"^```markdown\s*\n", "", report, flags=re.MULTILINE)
    report = re.sub(r"\n```\s*$", "", report, flags=re.MULTILINE)
    report = report.strip()

    format_markdown_report({})  # triggers progress-tracking print in app.py
    return report


# ---------------------------------------------------------------------------
# Master Workflow – called by run_single.py
# ---------------------------------------------------------------------------

class ContractReviewWorkflow:
    """
    Orchestrates the 5-stage contract review pipeline.
    Replaces the Google ADK SequentialAgent / InMemoryRunner.
    """

    name = "contract_review_workflow"

    async def run(self, contract_text: str, filename: str, pages: int) -> str:
        """
        Run the complete contract review pipeline.

        Args:
            contract_text: Full extracted text of the contract PDF.
            filename:      Original filename (for the report header).
            pages:         Number of pages (informational).

        Returns:
            The final Markdown report as a string.
        """
        # Stage 1
        intake = run_intake_agent(contract_text, filename, pages)
        contract_type = intake.get("contract_type", "Unknown")

        # Stage 2
        clauses = run_clause_extraction_agent(contract_text, contract_type)

        # Stage 3
        scored = run_risk_scoring_agent(clauses)

        # Stage 4
        compared = run_playbook_comparison_agent(scored, contract_type)

        # Stage 5
        report = run_report_generator_agent(intake, compared, filename)

        return report


# ---------------------------------------------------------------------------
# Public exports – kept for backward-compatibility with run_single.py / run_batch.py
# ---------------------------------------------------------------------------

contract_review_workflow = ContractReviewWorkflow()
root_agent = contract_review_workflow  # alias used in legacy scripts
