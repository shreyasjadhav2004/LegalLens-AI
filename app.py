import streamlit as st
import asyncio
import tempfile
import os
import re
from pathlib import Path
from src.tools.pdf_parser import DocumentParser
from src.ollama_client import check_ollama_health, chat_stream
from src.utils.docx_generator import generate_docx

import base64
from dotenv import load_dotenv

load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="Legal AI | Contract Review",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for Premium Look ---
st.markdown("""
<style>
    /* Main Background */
    .stApp {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    
    /* Typography */
    /* Custom Header Sizes for Report */
    h1 {
        font-size: 1.8rem !important;
    }
    h2 {
        font-size: 1.5rem !important;
    }
    h3 {
        font-size: 1.2rem !important;
    }
    h1, h2, h3 {
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        color: #FFFFFF;
    }
    
    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #161B22;
        border-right: 1px solid #30363D;
    }
    
    /* Buttons */
    .stButton > button {
        background-color: #238636;
        color: white;
        border: none;
        border-radius: 6px;
        padding: 0.5rem 1rem;
        font-weight: 500;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        background-color: #2EA043;
        box-shadow: 0 4px 12px rgba(46, 160, 67, 0.4);
    }
    
    /* File Uploader */
    .stFileUploader {
        border: 1px dashed #30363D;
        border-radius: 8px;
        padding: 2rem;
        background-color: #0D1117;
    }
    
    /* Cards/Containers */
    .css-1r6slb0 {
        background-color: #161B22;
        border: 1px solid #30363D;
        border-radius: 8px;
        padding: 1.5rem;
    }
    
    /* Status Indicators */
    .status-box {
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 10px;
        font-family: monospace;
        font-size: 0.9em;
    }
    .status-info { background-color: #1F6FEB33; color: #58A6FF; border-left: 3px solid #1F6FEB; }
    .status-success { background-color: #23863633; color: #3FB950; border-left: 3px solid #238636; }
    .status-warning { background-color: #9E6A0333; color: #D29922; border-left: 3px solid #9E6A03; }
    .status-error { background-color: #DA363333; color: #F85149; border-left: 3px solid #DA3633; }

</style>
""", unsafe_allow_html=True)

def displayPDF(file_path):
    """Display PDF in Streamlit using an iframe"""
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    
    pdf_display = f'''
        <iframe src="data:application/pdf;base64,{base64_pdf}" 
                width="100%" 
                height="800" 
                type="application/pdf"
                style="border: 2px solid #ddd; border-radius: 5px;">
        </iframe>
    '''
    st.markdown(pdf_display, unsafe_allow_html=True)

# --- Sidebar ---
with st.sidebar:
    st.title("⚖️ Multi Agent System")
    st.markdown("---")
    
    # Show Ollama status
    health = check_ollama_health()
    if health["ok"]:
        ollama_model = os.getenv("OLLAMA_MODEL", "phi3:latest")
        st.markdown(f"""
**System Status:** 🟢 Online

**Backend:** 🦙 Ollama (local)
**Model:** `{ollama_model}`

**Agents Active:**
- 🔍 Intake Agent
- 📄 Clause Extractor
- ⚠️ Risk Scorer
- 📚 Playbook Auditor
- 📝 Report Generator
""")
    else:
        st.error(f"⚠️ Ollama Offline\n\n{health['error']}")
        st.info(health["hint"])

# --- Main Content ---
st.title("Contract Review System")
st.markdown("Upload a legal contract (PDF) for comprehensive AI analysis against company playbooks.")

# Show a warning banner if Ollama is not available
if not health["ok"]:
    st.error(
        f"**❌ Ollama is not available.** {health['error']}\n\n"
        f"**How to fix:** {health['hint']}"
    )
    st.stop()

uploaded_file = st.file_uploader("Drop your contract here", type="pdf")

if uploaded_file is not None:
    # Save temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_path = tmp_file.name

    # Initialize Session State
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "report_text" not in st.session_state:
        st.session_state.report_text = ""
    if "contract_text" not in st.session_state:
        st.session_state.contract_text = ""
    if "debug_text" not in st.session_state:
        st.session_state.debug_text = ""
    if "analysis_complete" not in st.session_state:
        st.session_state.analysis_complete = False

    # 1. Setup Layout (Always visible if file uploaded)
    # Sidebar: Debug Logs
    with st.sidebar:
        st.markdown("---")
        st.subheader("🕵️ Agent Traces")
        status_container = st.container(height=600)
        with status_container:
            # If we have logs in history, show them
            if st.session_state.debug_text:
                st.code(st.session_state.debug_text, language="text")
            debug_placeholder = st.empty() # Placeholder for new logs
        
    # Main Area: Split View
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader(f"📄 {uploaded_file.name}")
        displayPDF(tmp_path)
        st.markdown("###") # Spacer
        # Use nested columns to match the button size of the right column
        start_col1, start_col2 = st.columns(2)
        with start_col1:
            start_analysis = st.button("🚀 Start Analysis", use_container_width=True)
        
    with col2:
        st.subheader("📊 Analysis Report")
        # Scrollable container for the report
        report_scroll = st.container(height=800)
        with report_scroll:
            report_placeholder = st.empty()
            # If we have a report in history, show it
            if st.session_state.report_text:
                report_placeholder.markdown(st.session_state.report_text)

        # Action Buttons (Download / Copy)
        if st.session_state.report_text:
            st.markdown("###") # Spacer
            btn_col1, btn_col2 = st.columns(2)
            
            with btn_col1:
                docx_file = generate_docx(st.session_state.report_text)
                st.download_button(
                    label="📄 Download Report (.docx)",
                    data=docx_file,
                    file_name="contract_review.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True
                )
            
            with btn_col2:
                with st.popover("📋 Copy Report Text", use_container_width=True):
                    st.markdown("Click the copy icon in the top right of the code block:")
                    st.code(st.session_state.report_text, language="markdown")

    # Start Analysis Logic
    if start_analysis:
        # Reset state
        st.session_state.messages = []
        st.session_state.report_text = ""
        st.session_state.contract_text = ""
        st.session_state.debug_text = ""
        st.session_state.analysis_complete = False
        
        # Clear the debug placeholder if it has content from previous run
        debug_placeholder.empty()
        
        # 2. Run Subprocess
        import subprocess
        import sys
        import os
        
        # Use the same python executable that is running streamlit
        cmd = [sys.executable, "run_single.py", tmp_path]
        
        # Copy current env and set unbuffered output + UTF-8 mode
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONUTF8"] = "1"  # Force UTF-8 on Windows (avoids cp1252 UnicodeEncodeError)
        env["PYTHONIOENCODING"] = "utf-8"
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            universal_newlines=True,
            env=env
        )
        
        full_report_text = ""
        full_debug_text = ""
        captured_contract_text = ""
        is_report_content = False
        is_contract_text = False
        
        # Progress tracking
        progress_stages = {
            "intake": {"weight": 0.15, "complete": False, "name": "📋 Contract Intake"},
            "extraction": {"weight": 0.25, "complete": False, "name": "📄 Clause Extraction"},
            "risk": {"weight": 0.25, "complete": False, "name": "⚠️ Risk Assessment"},
            "playbook": {"weight": 0.20, "complete": False, "name": "📚 Playbook Compliance"},
            "report": {"weight": 0.15, "complete": False, "name": "📝 Report Generation"}
        }
        current_progress = 0.0
        
        # 3. Stream Output with Progress Indicators
        progress_bar = report_placeholder.progress(0.0)
        status_text = st.empty()
        status_text.markdown("🚀 **Starting analysis...**")
        
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                # Update progress based on agent output
                # Stage 1: Intake
                if "contract_intake_agent" in line and not progress_stages["intake"]["complete"]:
                    current_progress += progress_stages["intake"]["weight"]
                    progress_stages["intake"]["complete"] = True
                    progress_bar.progress(min(current_progress, 1.0))
                    status_text.markdown(f"✅ **{progress_stages['intake']['name']}** - Complete")
                
                # Stage 2: Clause Extraction
                if "clause_extraction_agent" in line or "ClauseExtractor" in line:
                    if not progress_stages["extraction"]["complete"]:
                        status_text.markdown(f"⏳ **{progress_stages['extraction']['name']}** - In Progress...")
                
                # Check if extraction complete (when risk scoring starts)
                if "risk_scoring_agent" in line and not progress_stages["extraction"]["complete"]:
                    current_progress += progress_stages["extraction"]["weight"]
                    progress_stages["extraction"]["complete"] = True
                    progress_bar.progress(min(current_progress, 1.0))
                    status_text.markdown(f"✅ **{progress_stages['extraction']['name']}** - Complete")
                
                # Stage 3: Risk Assessment
                if "risk_scoring_agent" in line or "RiskScorer" in line:
                    if not progress_stages["risk"]["complete"]:
                        status_text.markdown(f"⏳ **{progress_stages['risk']['name']}** - In Progress...")
                
                # Check if risk scoring complete (when playbook starts)
                if "playbook_comparison_agent" in line and not progress_stages["risk"]["complete"]:
                    current_progress += progress_stages["risk"]["weight"]
                    progress_stages["risk"]["complete"] = True
                    progress_bar.progress(min(current_progress, 1.0))
                    status_text.markdown(f"✅ **{progress_stages['risk']['name']}** - Complete")
                
                # Stage 4: Playbook Comparison
                if "PlaybookAgent" in line:
                    if not progress_stages["playbook"]["complete"]:
                        status_text.markdown(f"⏳ **{progress_stages['playbook']['name']}** - In Progress...")
                
                # Check if playbook complete (when report generation starts)
                if "ReportGenerator" in line and not progress_stages["playbook"]["complete"]:
                    current_progress += progress_stages["playbook"]["weight"]
                    progress_stages["playbook"]["complete"] = True
                    progress_bar.progress(min(current_progress, 1.0))
                    status_text.markdown(f"✅ **{progress_stages['playbook']['name']}** - Complete")
                
                # Stage 5: Report Generation
                if "report_generator_agent" in line or "ReportGenerator" in line:
                    if not progress_stages["report"]["complete"]:
                        status_text.markdown(f"⏳ **{progress_stages['report']['name']}** - Synthesizing final report...")
                        current_progress += progress_stages["report"]["weight"] * 0.5
                        progress_bar.progress(min(current_progress, 1.0))
                
                # Capture Contract Text
                if "---CONTRACT_TEXT_START---" in line:
                    is_contract_text = True
                    continue
                if "---CONTRACT_TEXT_END---" in line:
                    is_contract_text = False
                    continue
                if is_contract_text:
                    captured_contract_text += line
                    continue

                # Logic to separate Debug vs Report
                is_report_line = (
                    "report_generator_agent >" in line or 
                    "# Contract Review Report" in line or 
                    "Contract Review Report:" in line or
                    "1. Executive Summary" in line
                )
                
                # Stop treating as report if we see other agent outputs after report started
                if is_report_content and ("playbook_comparison_agent >" in line or "PlaybookAgent:" in line):
                    is_report_content = False
                
                if is_report_line:
                    is_report_content = True
                    # Clean up the line if it has the agent prefix
                    line = line.replace("report_generator_agent >", "")
                
                if is_report_content:
                    # Mark report stage as complete and clear progress UI
                    if not progress_stages["report"]["complete"]:
                        current_progress = 1.0
                        progress_stages["report"]["complete"] = True
                        status_text.empty()
                    
                    # Skip debug print statements from report content
                    if "ReportGenerator: Formatting final report" not in line:
                        full_report_text += line
                    
                    # Always display the accumulated report
                    if full_report_text.strip():
                        report_placeholder.markdown(full_report_text)
                else:
                    # Debug logs
                    if "---REPORT_START---" not in line:
                        full_debug_text += line
                        debug_placeholder.code(full_debug_text, language="text")

        # Clean up the report text
        def clean_report_text(text):
            """Remove conversational filler and markdown code fences from report."""
            # Remove markdown code fences
            text = re.sub(r'^```markdown\s*\n', '', text, flags=re.MULTILINE)
            text = re.sub(r'\n```\s*$', '', text, flags=re.MULTILINE)
            # Remove common conversational prefixes
            prefixes_to_remove = [
                r'^Sure,?\s+I\s+can\s+help.*?\.?\s*',
                r'^Here\'s\s+.*?report.*?\.?\s*',
                r'^I\'ll\s+.*?\.?\s*',
                r'^Let\s+me\s+.*?\.?\s*',
            ]
            for prefix in prefixes_to_remove:
                text = re.sub(prefix, '', text, flags=re.IGNORECASE)
            text = text.strip()
            return text
        
        full_report_text = clean_report_text(full_report_text)
        
        # If no report was parsed from the pipe, try to read stderr for error messages
        if not full_report_text.strip():
            stderr_output = process.stderr.read()
            if stderr_output:
                st.error(f"Analysis failed. Agent error:\n\n```\n{stderr_output[:2000]}\n```")
            else:
                st.warning("Analysis completed but no report was generated. Check the Agent Traces panel for details.")
        
        if process.returncode == 0:
            st.sidebar.success("✅ Analysis Complete!")
            # Save to session state
            st.session_state.report_text = full_report_text
            st.session_state.contract_text = captured_contract_text
            st.session_state.debug_text = full_debug_text
            st.session_state.analysis_complete = True
            st.rerun()
        else:
            stderr = process.stderr.read()
            if "Cannot connect to Ollama" in stderr or "Ollama Error" in stderr:
                st.error(
                    "**❌ Ollama connection failed.**\n\n"
                    "Make sure Ollama is running (`ollama serve`) and the model is downloaded "
                    f"(`ollama pull {os.getenv('OLLAMA_MODEL', 'phi3:latest')}`)."
                )
            else:
                st.error(f"Process failed with error:\n```\n{stderr[:2000]}\n```")

    # --- Chat Interface ---
    if st.session_state.analysis_complete:
        st.markdown("---")
        st.subheader("💬 Chat with your Contract")
        
        # Display chat messages
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # Chat Input
        if prompt := st.chat_input("Ask a question about the contract..."):
            # Add user message
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # Generate response via Ollama (streaming)
            with st.chat_message("assistant"):
                response_placeholder = st.empty()
                full_response = ""
                
                try:
                    # Build OpenAI-style message list for the chat endpoint
                    system_content = (
                        "You are a helpful legal assistant. You have analyzed a contract. "
                        "Answer questions based ONLY on the contract text and the analysis report provided. "
                        "Be concise, precise, and cite specific clauses when relevant."
                    )
                    context_content = (
                        f"CONTRACT TEXT:\n{st.session_state.contract_text[:4000]}\n\n"
                        f"ANALYSIS REPORT:\n{st.session_state.report_text[:3000]}"
                    )

                    messages = [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": context_content},
                        {"role": "assistant", "content": "I have reviewed the contract and the analysis report. I am ready to answer your questions."},
                    ]

                    # Add prior conversation history (last 6 turns to stay within context)
                    for msg in st.session_state.messages[-6:]:
                        messages.append({"role": msg["role"], "content": msg["content"]})

                    # Stream the response
                    for chunk in chat_stream(messages):
                        full_response += chunk
                        response_placeholder.markdown(full_response + "▌")

                    response_placeholder.markdown(full_response)
                    st.session_state.messages.append({"role": "assistant", "content": full_response})
                    
                except Exception as exc:
                    error_msg = str(exc)
                    if "Cannot connect to Ollama" in error_msg:
                        st.error(
                            "**❌ Ollama connection lost.** "
                            "Make sure Ollama is still running: `ollama serve`"
                        )
                    elif "timed out" in error_msg.lower():
                        st.error(
                            "**⏱️ Response timed out.** "
                            "The model may be busy. Try again in a moment."
                        )
                    else:
                        st.error(f"Error generating response: {exc}")
            
    # Cleanup (optional, maybe keep it for debugging or move inside button)
    # os.unlink(tmp_path)
