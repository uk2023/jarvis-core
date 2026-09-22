import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.abspath(".env"))

key = os.getenv("OPENROUTER_API_KEY", "").strip()

URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-oss-120b:free"

print("=" * 72)
print("JARVIS — OPENROUTER GPT-OSS-120B FREE LIVE TEST")
print("=" * 72)

if not key:
    print("OPENROUTER_API_KEY: NOT SET")
    print()
    print("Add to .env:")
    print("OPENROUTER_API_KEY=your_key_here")
    raise SystemExit(1)

print("MODEL:", MODEL)
print("KEY  :", key[:8] + "..." + key[-4:])
print()

payload = {
    "model": MODEL,
    "messages": [
        {
            "role": "user",
            "content": "Reply with exactly: JARVIS_OPENROUTER_OK"
        }
    ],
    "max_tokens": 20,
    "temperature": 0
}

headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/uk2023/Jarvis_Work",
    "X-Title": "JARVIS",
}

try:
    r = requests.post(
        URL,
        headers=headers,
        json=payload,
        timeout=45,
    )

    print("HTTP:", r.status_code)

    for h in [
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "retry-after",
    ]:
        if h in r.headers:
            print(f"{h}: {r.headers[h]}")

    print()

    if r.status_code == 200:
        data = r.json()

        text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )

        print("STATUS: VALID")
        print("MODEL :", data.get("model"))
        print("REPLY :", repr(text))

        if "JARVIS_OPENROUTER_OK" in text:
            print()
            print("RESULT: ✅ GPT-OSS-120B EXECUTED")
        else:
            print()
            print("RESULT: ⚠️ HTTP 200, unexpected response")

    elif r.status_code == 401:
        print("RESULT: ❌ INVALID / UNAUTHORIZED KEY")

    elif r.status_code == 402:
        print("RESULT: ❌ PAYMENT / CREDIT REQUIRED")

    elif r.status_code == 429:
        print("RESULT: ⚠️ FREE RATE/DAILY LIMIT EXHAUSTED")

    else:
        print("RESULT: ⚠️ PROVIDER ERROR")

    print()
    print("RESPONSE:")
    print(r.text[:2000])

except requests.exceptions.Timeout:
    print("RESULT: ⚠️ TIMEOUT")

except requests.exceptions.RequestException as e:
    print("RESULT: ❌ NETWORK ERROR")
    print(e)

print("=" * 72)
