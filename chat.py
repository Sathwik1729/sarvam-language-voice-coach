import os
import sys
from pathlib import Path

from sarvamai import SarvamAI

# Load SARVAM_API_KEY from .env next to this script (no extra dependency needed)
env_file = Path(__file__).with_name(".env")
if env_file.exists():
    for line in env_file.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())

api_key = os.environ.get("SARVAM_API_KEY")
if not api_key:
    raise SystemExit("SARVAM_API_KEY is not set. Add it to .env.")

client = SarvamAI(api_subscription_key=api_key)

response = client.chat.completions(
    model="sarvam-105b-conversations",
    messages=[{"role": "user", "content": "Say hello in Hindi and English."}],
)

sys.stdout.reconfigure(encoding="utf-8")  # Windows console needs this for Indic scripts
print(response.choices[0].message.content)
