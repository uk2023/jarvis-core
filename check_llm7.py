import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.abspath(".env"))

key = os.getenv("LLM7_API_KEY")
if not key:
    raise SystemExit("LLM7_API_KEY NOT LOADED")

print("=" * 72)
print("JARVIS — LLM7 LIVE HTTP TEST")
print("=" * 72)

print("KEY:", key[:6] + "..." + key[-4:])

# LLM7 OpenAI-compatible endpoint
url = "https://api.llm7.io/v1/chat/completions"

payload = {
    "model": "openai/gpt-oss-120b",
    "messages": [
        {"role": "user", "content": "Reply with exactly: OK"}
    ],
    "max_tokens": 8,
    "temperature": 0
}

try:
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    print("HTTP:", r.status_code)

    for h in [
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "ratelimit-limit",
        "ratelimit-remaining",
        "ratelimit-reset",
    ]:
        if h in r.headers:
            print(f"{h}: {r.headers[h]}")

    print("\nRESPONSE:")
    print(r.text[:2000])

except Exception as e:
    print("ERROR:", repr(e))

print("=" * 72)
