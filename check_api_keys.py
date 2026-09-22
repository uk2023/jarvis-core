#!/usr/bin/env python3

import os
import sys
import json
import time
import requests
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    print("ERROR: python-dotenv not installed")
    sys.exit(1)


# ============================================================
# JARVIS — REAL API KEY HTTP VERIFIER
# ============================================================
#
# Purpose:
#   1. Read API keys from .env
#   2. Send a REAL authenticated HTTP request
#   3. Verify authentication
#   4. Detect quota / rate-limit information when exposed
#   5. Never print the actual API key
#
# Providers:
#   GROQ       -> 6 keys expected
#   CEREBRAS   -> 8 keys expected
#   CLOUDFLARE -> 2 tokens expected
#
# NOTE:
#   "VALID" does NOT necessarily mean quota information
#   is exposed by that provider.
# ============================================================


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"

load_dotenv(ENV_FILE)


TIMEOUT = 20

# Same logical target used by Jarvis.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "openai/gpt-oss-120b")
CLOUDFLARE_MODEL = os.getenv(
    "CLOUDFLARE_MODEL",
    "@cf/openai/gpt-oss-120b",
)


def csv_env(name):
    value = os.getenv(name, "")
    return [
        x.strip()
        for x in value.split(",")
        if x.strip()
    ]


def mask_key(key):
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def classify_status(code):
    if code in (200, 201):
        return "VALID"
    if code in (401, 403):
        return "INVALID_AUTH"
    if code == 429:
        return "RATE_LIMITED"
    if 400 <= code < 500:
        return "CLIENT_ERROR"
    if 500 <= code < 600:
        return "PROVIDER_ERROR"
    return "UNKNOWN"


def quota_headers(headers):
    interesting = {}

    names = [
        "x-ratelimit-limit-requests",
        "x-ratelimit-remaining-requests",
        "x-ratelimit-reset-requests",
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-reset-tokens",
        "retry-after",
    ]

    for name in names:
        value = headers.get(name)
        if value is not None:
            interesting[name] = value

    return interesting


def safe_body(response):
    try:
        data = response.json()

        if isinstance(data, dict):
            # Do not dump huge provider responses.
            if "error" in data:
                return str(data["error"])[:300]

            if "message" in data:
                return str(data["message"])[:300]

            return json.dumps(data)[:300]

        return str(data)[:300]

    except Exception:
        text = response.text.strip()
        return text[:300]


def test_groq(index, key):

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly: OK",
            }
        ],
        "max_tokens": 4,
        "temperature": 0,
    }

    return requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=TIMEOUT,
    )


def test_cerebras(index, key):

    url = "https://api.cerebras.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": CEREBRAS_MODEL,
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly: OK",
            }
        ],
        "max_tokens": 4,
        "temperature": 0,
    }

    return requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=TIMEOUT,
    )


def test_cloudflare(index, token, account_id):

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{account_id}/ai/run/{CLOUDFLARE_MODEL}"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly: OK",
            }
        ],
        "max_tokens": 4,
    }

    return requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=TIMEOUT,
    )


def print_result(provider, index, key, response):

    code = response.status_code
    status = classify_status(code)

    headers = quota_headers(response.headers)

    print(
        f"{provider:<10} "
        f"key[{index}] "
        f"{mask_key(key):<13} "
        f"HTTP={code:<3} "
        f"STATUS={status}"
    )

    if headers:
        for name, value in headers.items():
            print(f"             {name}: {value}")

    if status not in ("VALID", "RATE_LIMITED"):
        body = safe_body(response)
        if body:
            print(f"             response: {body}")


def main():

    print("=" * 72)
    print("JARVIS — REAL API KEY HTTP VERIFICATION")
    print("=" * 72)

    print(f"ENV : {ENV_FILE}")
    print(f"Groq model      : {GROQ_MODEL}")
    print(f"Cerebras model  : {CEREBRAS_MODEL}")
    print(f"Cloudflare model: {CLOUDFLARE_MODEL}")
    print()

    groq_keys = csv_env("GROQ_API_KEYS")

    # Backward compatibility.
    if not groq_keys:
        single = os.getenv("GROQ_API_KEY", "").strip()
        if single:
            groq_keys = [single]

    cerebras_keys = csv_env("CEREBRAS_API_KEYS")

    if not cerebras_keys:
        single = os.getenv("CEREBRAS_API_KEY", "").strip()
        if single:
            cerebras_keys = [single]

    cloudflare_tokens = csv_env("CLOUDFLARE_API_KEYS")

    if not cloudflare_tokens:
        single = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        if single:
            cloudflare_tokens = [single]

    cloudflare_accounts = csv_env("CLOUDFLARE_ACCOUNT_IDS")

    print("KEY INVENTORY")
    print("-" * 72)
    print(f"GROQ       : {len(groq_keys)} key(s)")
    print(f"CEREBRAS   : {len(cerebras_keys)} key(s)")
    print(f"CLOUDFLARE : {len(cloudflare_tokens)} token(s)")
    print(f"CF accounts: {len(cloudflare_accounts)}")
    print()

    total = 0
    valid = 0
    invalid = 0
    rate_limited = 0
    errors = 0

    # --------------------------------------------------------
    # GROQ
    # --------------------------------------------------------

    print("=" * 72)
    print("GROQ — LIVE HTTP TEST")
    print("=" * 72)

    for i, key in enumerate(groq_keys, 1):

        total += 1

        try:
            response = test_groq(i, key)
            print_result("GROQ", i, key, response)

            if response.status_code in (200, 201):
                valid += 1
            elif response.status_code == 429:
                rate_limited += 1
            elif response.status_code in (401, 403):
                invalid += 1
            else:
                errors += 1

        except Exception as exc:
            errors += 1
            print(
                f"GROQ       key[{i}] "
                f"STATUS=NETWORK_ERROR "
                f"{type(exc).__name__}: {exc}"
            )

    print()

    # --------------------------------------------------------
    # CEREBRAS
    # --------------------------------------------------------

    print("=" * 72)
    print("CEREBRAS — LIVE HTTP TEST")
    print("=" * 72)

    for i, key in enumerate(cerebras_keys, 1):

        total += 1

        try:
            response = test_cerebras(i, key)
            print_result("CEREBRAS", i, key, response)

            if response.status_code in (200, 201):
                valid += 1
            elif response.status_code == 429:
                rate_limited += 1
            elif response.status_code in (401, 403):
                invalid += 1
            else:
                errors += 1

        except Exception as exc:
            errors += 1
            print(
                f"CEREBRAS   key[{i}] "
                f"STATUS=NETWORK_ERROR "
                f"{type(exc).__name__}: {exc}"
            )

    print()

    # --------------------------------------------------------
    # CLOUDFLARE
    # --------------------------------------------------------

    print("=" * 72)
    print("CLOUDFLARE — LIVE HTTP TEST")
    print("=" * 72)

    if not cloudflare_accounts:
        print("No CLOUDFLARE_ACCOUNT_IDS found.")
    elif len(cloudflare_accounts) != len(cloudflare_tokens):
        print(
            "WARNING: token count and account-id count differ."
        )
        print(
            f"Tokens={len(cloudflare_tokens)} "
            f"Accounts={len(cloudflare_accounts)}"
        )

    for i, token in enumerate(cloudflare_tokens, 1):

        total += 1

        if i > len(cloudflare_accounts):
            errors += 1
            print(
                f"CLOUDFLARE key[{i}] "
                f"STATUS=NO_ACCOUNT_ID"
            )
            continue

        account_id = cloudflare_accounts[i - 1]

        try:
            response = test_cloudflare(
                i,
                token,
                account_id,
            )

            print_result(
                "CLOUDFLARE",
                i,
                token,
                response,
            )

            if response.status_code in (200, 201):
                valid += 1
            elif response.status_code == 429:
                rate_limited += 1
            elif response.status_code in (401, 403):
                invalid += 1
            else:
                errors += 1

        except Exception as exc:
            errors += 1
            print(
                f"CLOUDFLARE key[{i}] "
                f"STATUS=NETWORK_ERROR "
                f"{type(exc).__name__}: {exc}"
            )

    print()

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print("=" * 72)
    print("FINAL RESULT")
    print("=" * 72)

    print(f"Total credentials tested : {total}")
    print(f"Authenticated / VALID    : {valid}")
    print(f"Invalid authentication   : {invalid}")
    print(f"Rate limited             : {rate_limited}")
    print(f"Other / network errors   : {errors}")

    print()

    if total:
        print(
            f"Authentication success: "
            f"{valid}/{total}"
        )

    print()
    print("IMPORTANT:")
    print("- VALID means the provider accepted the credential/request.")
    print("- Quota is shown only when the provider exposes it.")
    print("- RATE_LIMITED does not automatically mean the key is invalid.")
    print("- Actual API keys are never printed.")
    print("=" * 72)


if __name__ == "__main__":
    main()
