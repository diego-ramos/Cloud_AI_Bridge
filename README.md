# Cloud AI Bridge

This is a lightweight Python Flask service that accepts a base64 encoded PDF and uses the `google-genai` SDK to extract structured purchase order data from it.

## Setup

1. Install Python 3.9+
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set your API Key:
   ```bash
   # On Windows PowerShell
   $env:GEMINI_API_KEY="your_api_key_here"
   ```
4. Run the server:
   ```bash
   python app.py
   ```

The server will be available at `http://localhost:8080/extract_pdf`.

## License
This project is licensed under the Apache License 2.0. See the [LICENSE](file:///c:/Purchase_orders_WorkSpace/Cloud_AI_Bridge/LICENSE) file for details.

Copyright © 2026 Diego Alberto Ramos Patarroyo (Digzu.co)
