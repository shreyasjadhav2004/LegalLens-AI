import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# Ollama Configuration (replaces Google Gemini / Google ADK model settings)
# ---------------------------------------------------------------------------

# Base URL for the locally running Ollama server
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Model to use for all AI inference.
# phi3:latest is a strong 2.2GB instruction-following model that handles
# structured JSON output well. Switch to a larger model (e.g. llama3:8b,
# mistral:7b) if you have more RAM / VRAM available.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3:latest")

# Request timeout in seconds (local inference on CPU can be slow)
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))

# Legacy alias kept for internal compatibility; not used for Gemini any more.
MODEL_ID = OLLAMA_MODEL
