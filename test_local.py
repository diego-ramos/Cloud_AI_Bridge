"""
Script de prueba local para el endpoint /extract_pdf
Convierte un PDF a Base64 y lo envía al servidor Flask corriendo en localhost:8080
"""
import base64
import json
import sys
import requests

SERVER_URL  = "http://127.0.0.1:8080/extract_pdf"
API_KEY     = "secret-php-api-key"
PDF_PATH    = sys.argv[1] if len(sys.argv) > 1 else r"examples\Bedrosians - 20260130104430863.pdf"
CUSTOMER_ID = sys.argv[2] if len(sys.argv) > 2 else None

def run_test(pdf_path: str, customer_id: str = None):
    print(f"\n{'='*60}")
    print(f"PDF:         {pdf_path}")
    print(f"Customer ID: {customer_id or '(none)'}")
    print(f"Server:      {SERVER_URL}")
    print(f"{'='*60}\n")

    # Read and encode PDF
    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {"pdf_base64": pdf_b64}
    if customer_id:
        payload["customer_id"] = customer_id

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    print("Sending request...")
    response = requests.post(SERVER_URL, json=payload, headers=headers, timeout=120)

    print(f"HTTP Status: {response.status_code}")
    print(f"\n--- Response JSON ---")
    try:
        result = response.json()
        print(json.dumps(result, indent=2, ensure_ascii=False))

        # Quick summary
        confidence = result.get("confidence_score", "N/A")
        model_used = "gpt-4o" if float(confidence) < 0.8 else "gpt-4o-mini"
        print(f"\n{'='*60}")
        print(f"✅ Confidence Score : {confidence}")
        print(f"🤖 Model Used       : {model_used}")
        print(f"📦 Materials Found  : {len(result.get('materials', []))} item(s)")
        print(f"{'='*60}\n")
    except Exception as e:
        print(f"ERROR parsing response: {e}")
        print(response.text)

if __name__ == "__main__":
    run_test(PDF_PATH, CUSTOMER_ID)
