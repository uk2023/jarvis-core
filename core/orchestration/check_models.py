import os
import requests
from dotenv import load_dotenv

load_dotenv()

# .env se pehli API key extract karein
raw_keys = os.getenv("GROQ_API_KEY", "")
api_key = raw_keys.split(",")[0].strip() if raw_keys else ""

if not api_key:
    print("Error: GROQ_API_KEY .env file me nahi mila.")
    exit()

url = "https://api.groq.com/openai/v1/models"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    models = response.json().get("data", [])
    print("=== Aapke Account me Available Groq Models ===")
    for model in models:
        print(f"• {model['id']}")
else:
    print(f"Error {response.status_code}: {response.text}")
