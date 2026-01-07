
import os, requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": "✅ Prueba desde GitHub Actions (hola Lucio)"}

r = requests.post(url, data=payload, timeout=30)
print(r.status_code, r.text)
r.raise_for_status()
