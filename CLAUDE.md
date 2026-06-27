# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cloud AI Bridge is a lightweight Python Flask service that extracts structured purchase order data from PDF files using Azure OpenAI's GPT vision models. It converts PDF pages to images and uses AI to extract fields like PO number, delivery address, and line items.

## Architecture

The application runs as a Flask web service with two main endpoints:

- **`/extract_pdf`** (POST) - Main extraction endpoint. Accepts base64-encoded PDF and returns JSON with extracted purchase order data
- **`/customer_config/<customer_id>`** (GET) - Retrieves customer-specific extraction instructions from Firestore

### Data Flow

1. PDF is received as base64-encoded string
2. PDF is converted to base64 PNG images using PyMuPDF (2x resolution for OCR accuracy)
3. Images are sent to Azure OpenAI GPT-4o vision model
4. AI returns structured JSON with extracted fields
5. Results optionally stored/retrieved from Firestore for customer-specific instructions

### Key Features

- **Dynamic Model Routing**: Uses a base model (GPT-4o-mini) for standard extractions, escalates to PRO model (GPT-4o) when confidence is low or custom field instructions are active
- **Customer-Specific Instructions**: Stores per-customer overrides for PO format, address location, and materials table extraction in Firestore
- **Smart PO Validation**: Detects contaminated PO values (dates/spaces) and auto-escalates for correction
- **Bearer Token Authentication**: All endpoints require `Authorization: Bearer <API_KEY>` header

## Running the Application

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (Windows PowerShell)
$env:API_KEY="secret-php-api-key"
$env:OPEN_AI_END_POINT="https://your-resource.openai.azure.com/"
$env:OPEN_AI_KEY="your-azure-key"

# Run Flask server
python main.py
```

Server runs at `http://localhost:8080`

### Testing

```bash
# Run test with default PDF
python test_local.py

# Run test with specific PDF and customer ID
python test_local.py "examples/Bedrosians - 20260130104430863.pdf" "customer_123"
```

### Docker

```bash
docker build -t cloud-ai-bridge .
docker run -p 8080:8080 -e OPEN_AI_END_POINT=... -e OPEN_AI_KEY=... -e API_KEY=... cloud-ai-bridge
```

### Deployment

- **Cloud Run**: Deploy using `cloudbuild.yaml` - uses gunicorn with Python 3.10
- **Cloud Functions**: Deploy using `app.yaml` - uses Python 3.12, Gen2

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_KEY` | Yes | Bearer token for authentication |
| `OPEN_AI_END_POINT` | Yes | Azure OpenAI endpoint URL |
| `OPEN_AI_KEY` | Yes | Azure OpenAI API key |
| `AZURE_OPENAI_API_VERSION` | No | API version (default: 2024-12-01-preview) |
| `AZURE_BASE_MODEL` | No | Base model for extraction (default: gpt-4o-mini) |
| `AZURE_PRO_MODEL` | No | PRO model for fallback (default: gpt-4o) |

## Key Source Files

- [main.py](main.py) - Flask app, all endpoints, PDF conversion, AI calls, and routing logic
- [test_local.py](test_local.py) - Local testing script for the extraction endpoint

## Firestore Schema

Customer instructions are stored in collection `customer_instructions` with document ID = `customer_id`:

```json
{
  "po": "custom PO extraction instruction",
  "address": "custom address location instruction",
  "materials": "custom materials table instruction",
  "rotate_pages": 90
}
```