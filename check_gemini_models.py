"""
check_ollama.py  (replaces check_gemini_models.py)
===================================================
Verifies that Ollama is running and lists available models.
Run this before starting LegalLens-AI to confirm your setup is correct.

Usage:
    python check_ollama.py
"""

import os
import sys
import requests
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows (avoids UnicodeEncodeError with emojis)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
configured_model = os.getenv("OLLAMA_MODEL", "phi3:latest")

print(f"\n🦙 Ollama Health Check")
print(f"   Base URL : {base_url}")
print(f"   Model    : {configured_model}")
print("-" * 50)

# ── 1. Check connectivity ────────────────────────────────────────────────────
try:
    resp = requests.get(f"{base_url}/api/tags", timeout=5)
    resp.raise_for_status()
    print("✅ Ollama is running\n")
except requests.exceptions.ConnectionError:
    print(f"❌ Cannot connect to Ollama at {base_url}")
    print("\n💡 Fix:")
    print("   1. Install Ollama: https://ollama.com/download")
    print("   2. Start service:  ollama serve")
    print(f"   3. Pull model:     ollama pull {configured_model}")
    raise SystemExit(1)
except Exception as exc:
    print(f"❌ Unexpected error: {exc}")
    raise SystemExit(1)

# ── 2. List installed models ─────────────────────────────────────────────────
models = resp.json().get("models", [])
print("📦 Installed models:\n")
if not models:
    print("   (no models installed)")
else:
    for m in models:
        name   = m.get("name", "?")
        size   = m.get("size", 0) / 1_073_741_824  # bytes → GB
        marker = " ← configured" if configured_model in name else ""
        print(f"   • {name:<30}  {size:.1f} GB{marker}")

print()

# ── 3. Check that the configured model is present ───────────────────────────
available_names = [m.get("name", "") for m in models]
if any(configured_model in n for n in available_names):
    print(f"✅ Configured model '{configured_model}' is ready")
else:
    print(f"⚠️  Model '{configured_model}' is NOT downloaded.")
    print(f"\n💡 Download it now:")
    print(f"   ollama pull {configured_model}")
    raise SystemExit(1)

# ── 4. Quick inference test ──────────────────────────────────────────────────
print("\n🧪 Running quick inference test...")
try:
    test_resp = requests.post(
        f"{base_url}/api/generate",
        json={
            "model": configured_model,
            "prompt": "Reply with exactly: OK",
            "stream": False,
            "options": {"num_predict": 10, "temperature": 0, "num_ctx": 2048},
        },
        timeout=60,
    )
    test_resp.raise_for_status()
    answer = test_resp.json().get("response", "").strip()
    print(f"   Model response: '{answer}'")
    print("\n✅ LegalLens-AI is ready to run!")
    print("   Start with: streamlit run app.py")
except Exception as exc:
    print(f"❌ Inference test failed: {exc}")
    raise SystemExit(1)
