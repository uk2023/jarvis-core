#!/usr/bin/env python3

import os
import requests
from dotenv import load_dotenv

ENV_PATH = os.path.abspath(".env")
load_dotenv(ENV_PATH)

KEY = os.getenv("AIRFORCE_API_KEY", "").strip()

URL = "https://api.airforce/v1/chat/completions"
MODEL = "gpt-oss-120b"

print("=" * 72)
print("JARVIS — API.AIRFORCE GPT-OSS-120B LIVE TEST")
print("=" * 72)
print(f"ENV   : {ENV_PATH}")
print(f"MODEL : {MODEL}")
print()

if not KEY:
    print("AIRFORCE_API_KEY: NOT SET")
    print()
    print("Add this to .env:")
    print("AIRFORCE_API_KEY=your_key_here")
    raise SystemExit(1)

masked = KEY[:6] + "..." + KEY[-4:] if len(KEY) > 12 else "***"

print(f"KEY   : {masked}")
print(f"URL   : {URL}")
print()

payload = {
    "model": MODEL,
    "messages": [
        {
            "role": "user",
            "content": "Reply with exactly: JARVIS_AIRFORCE_OK"
        }
    ],
    "max_tokens": 20,
    "temperature": 0
}

headers = {
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
}

try:
    r = requests.post(
        URL,
        headers=headers,
        json=payload,
        timeout=30,
    )

    print(f"HTTP   : {r.status_code}")

    for h in [
        "x-ratelimit-limit-requests",
        "x-ratelimit-remaining-requests",
        "x-ratelimit-reset-requests",
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-tokens",
        "retry-after",
    ]:
        if h in r.headers:
            print(f"{h}: {r.headers[h]}")

    print()

    if r.status_code == 200:
        try:
            data = r.json()
            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

            print("STATUS : VALID + MODEL EXECUTED")
            print("MODEL  :", data.get("model", MODEL))
            print("REPLY  :", repr(text))

            if "JARVIS_AIRFORCE_OK" in text:
                print()
                print("RESULT : ✅ GPT-OSS-120B WORKING")
            else:
                print()
                print("RESULT : ⚠️ HTTP 200 but unexpected response")

        except Exception as e:
            print("RESULT : ⚠️ HTTP 200 but response parsing failed")
            print("ERROR  :", e)

    elif r.status_code == 401:
        print("STATUS : ❌ INVALID / UNAUTHORIZED KEY")

    elif r.status_code == 402:
        print("STATUS : ❌ PAYMENT / BILLING REQUIRED")

    elif r.status_code == 429:
        print("STATUS : ⚠️ RATE LIMITED / FREE QUOTA EXHAUSTED")

    elif r.status_code >= 500:
        print("STATUS : ⚠️ PROVIDER SERVER ERROR")

    else:
        print("STATUS : ⚠️ OTHER HTTP ERROR")

    print()
    print("RAW RESPONSE:")
    print(r.text[:2000])

except requests.exceptions.Timeout:
    print("STATUS : ⚠️ TIMEOUT")

except requests.exceptions.RequestException as e:
    print("STATUS : ❌ NETWORK ERROR")
    print("ERROR  :", e)

print("=" * 72)
