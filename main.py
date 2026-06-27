import os
import base64
import json
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables from .env file (local development)
load_dotenv()
from openai import AzureOpenAI
from google.cloud import firestore

app = Flask(__name__)

# Initialize Firestore DB globally
try:
    db = firestore.Client()
except Exception as e:
    print(f"WARNING: Failed to initialize Firestore Client. Error: {e}")
    db = None

# Basic API Key authentication
EXPECTED_API_KEY = os.environ.get('API_KEY')
if not EXPECTED_API_KEY:
    print("CRITICAL: API_KEY environment variable is not set. API authentication will fail.")

# Initialize the Azure OpenAI client
azure_endpoint = os.environ.get('OPEN_AI_END_POINT')
azure_api_key  = os.environ.get('OPEN_AI_KEY')
azure_api_version = os.environ.get('AZURE_OPENAI_API_VERSION', '2024-12-01-preview')

if not azure_endpoint or not azure_api_key:
    print("CRITICAL: OPEN_AI_END_POINT or OPEN_AI_KEY environment variable is not set.")
    client = None
else:
    try:
        client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_api_key,
            api_version=azure_api_version,
        )
        print("Azure OpenAI client initialized successfully.")
    except Exception as e:
        print("WARNING: Failed to initialize Azure OpenAI Client. Error:", e)
        client = None


def pdf_bytes_to_base64_images(pdf_bytes: bytes, rotation_degrees: int = 0) -> list[str]:
    """
    Converts each page of a PDF (provided as bytes) into a Base64-encoded PNG string.
    Returns a list of Base64 strings, one per page.
    """
    images_b64 = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            # Render page at 2x resolution for better OCR accuracy
            mat = fitz.Matrix(2.0, 2.0)
            if rotation_degrees != 0:
                mat.prerotate(rotation_degrees)
            
            pix = page.get_pixmap(matrix=mat)
            png_bytes = pix.tobytes("png")
            images_b64.append(base64.b64encode(png_bytes).decode("utf-8"))
        doc.close()
    except Exception as e:
        print(f"ERROR: Failed to convert PDF to images: {e}")
        raise
    return images_b64


def call_azure_openai(model: str, system_prompt: str, page_images_b64: list[str]) -> dict:
    """
    Calls Azure OpenAI chat completions with the given model.
    Sends all PDF page images as vision inputs.
    Returns the parsed JSON dict from the model response.
    """
    global client
    if client is None:
        print("Attempting to re-initialize Azure OpenAI client...")
        client = AzureOpenAI(
            azure_endpoint=os.environ.get('OPEN_AI_END_POINT'),
            api_key=os.environ.get('OPEN_AI_KEY'),
            api_version=os.environ.get('AZURE_OPENAI_API_VERSION', '2024-12-01-preview'),
        )

    # Build the content array: one image entry per PDF page
    user_content = []
    for idx, img_b64 in enumerate(page_images_b64):
        user_content.append({
            "type": "text",
            "text": f"Page {idx + 1}:"
        })
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
                "detail": "high"
            }
        })

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content}
        ],
        response_format={"type": "json_object"},
        temperature=0,  # Fully deterministic — extraction must be consistent
    )

    raw_text = response.choices[0].message.content
    return json.loads(raw_text)


def require_api_key(func):
    def wrapper(*args, **kwargs):
        # In Cloud Functions, 'request' is a global flask.request
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401

        token = auth_header.split(' ')[1]
        print(f"AUTH Token: {token}")
        print(f"EXPECTED Token: {EXPECTED_API_KEY}")
        if token != EXPECTED_API_KEY:
            return jsonify({"error": "Unauthorized API Key"}), 401

        return func(*args, **kwargs)

    # Required to preserve the original function name for Flask routes
    wrapper.__name__ = func.__name__
    return wrapper


@app.route('/customer_config/<customer_id>', methods=['GET'])
@require_api_key
def get_customer_config(customer_id, arg_request=None):
    if not db:
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        doc = db.collection('customer_instructions').document(customer_id).get()
        if doc.exists:
            return jsonify(doc.to_dict()), 200
        else:
            return jsonify({}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/extract_pdf', methods=['POST'])
@require_api_key
def extract_pdf(arg_request=None):
    """
    HTTP Cloud Function.
    Args:
        arg_request (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """
    try:
        # Use the passed argument if provided (Cloud Functions),
        # otherwise fallback to the global flask request (Local Testing).
        actual_request = arg_request if arg_request is not None else request

        data = actual_request.get_json(silent=True)
        if not data or 'pdf_base64' not in data:
            return jsonify({"error": "Missing 'pdf_base64' in JSON body"}), 400

        pdf_base64 = data['pdf_base64']
        pdf_bytes  = base64.b64decode(pdf_base64)
        customer_id       = data.get('customer_id')
        new_instructions  = data.get('new_instructions')
        rotation_degrees  = data.get('rotate_pages', 0)

        # Build the base extraction prompt
        # Default field definitions
        po_instruction        = "the PO number or order number — extract ONLY the numeric/alphanumeric code, NOT any dates or surrounding text"
        addr_instruction      = "the full delivery address block (usually below a 'Ship To' or 'Deliver To' label)"
        addr_name_instruction = "the first line of that same delivery address block"
        item_num_instruction  = "the customer's own product/item code for the item"
        materials_table_hint  = ""

        po_override      = False
        address_override = False
        item_num_override = False

        # Look up or update customer-specific instructions globally
        applied_instructions = None
        if customer_id and db:
            doc_ref = db.collection('customer_instructions').document(customer_id)

            # Always save the rotation preference
            try:
                doc_ref.set({"rotate_pages": rotation_degrees}, merge=True)
            except Exception as e:
                print(f"Warning: Could not save rotation to Firestore: {e}")

            # If new instructions are provided, update the DB
            if new_instructions:
                try:
                    new_instr_dict = json.loads(new_instructions)
                    doc_ref.set(new_instr_dict, merge=True)
                    print(f"Saved/Updated specific field instructions in Firestore for customer: {customer_id}")
                except Exception as e:
                    print(f"Warning: Could not save instructions to Firestore: {e}")

            # Fetch custom instructions
            try:
                doc = doc_ref.get()
                if doc.exists:
                    custom_instruction = doc.to_dict()
                    if custom_instruction and isinstance(custom_instruction, dict):
                        applied_instructions = custom_instruction
                        print(f"Applying custom field instructions for customer: {customer_id}")

                        if 'po' in custom_instruction:
                            raw_po = custom_instruction['po']
                            po_override = True
                            po_instruction = (
                                f"CUSTOMER OVERRIDE: {raw_po}. "
                                f"You MUST follow this instruction exactly. "
                                f"Extract ONLY the pure numeric or alphanumeric PO code — "
                                f"do NOT include dates, labels, or any other surrounding text in your output."
                            )

                        if 'address' in custom_instruction:
                            raw_addr = custom_instruction['address']
                            address_override = True
                            addr_instruction = (
                                f"CUSTOMER OVERRIDE: {raw_addr}. "
                                f"You MUST follow this instruction strictly. "
                                f"If it provides a hardcoded address, output exactly that address. "
                                f"If it tells you to use a specific block on the document (like 'Supplier Address' or 'Remit To'), use that block. "
                                f"IGNORE standard 'Ship To' or 'Delivery Address' blocks if they conflict with this instruction."
                            )
                            addr_name_instruction = f"the first line of the address determined by the CUSTOMER OVERRIDE above"

                        if 'materials' in custom_instruction:
                            raw_mat = custom_instruction['materials']
                            item_num_override = True
                            materials_table_hint = f" CUSTOMER INSTRUCTION FOR THIS TABLE: {raw_mat}."
                            item_num_instruction = (
                                f"CUSTOMER OVERRIDE: {raw_mat}. "
                                f"Follow this instruction strictly to find the item number."
                            )

            except Exception as e:
                print(f"Warning: Could not read instructions from Firestore: {e}")
        elif customer_id and not db:
            print(f"WARNING: Cannot apply instructions for {customer_id} because Firestore is not initialized.")

        prompt = f"""
        You are an AI assistant that extracts structured data from customer order PDFs.
        Extract the following fields:

        - purchase_order (string): {po_instruction}.
        - full_delivery_address (string): {addr_instruction} Include all lines.
        - delivery_address (string): Same address as full_delivery_address but WITHOUT the zip code.
        - delivery_address_name (string): {addr_name_instruction}.
        - zip_code (string): Only the zip/postal code from that same address block.
        - materials (array of objects): All line items from the order table.{materials_table_hint} For each item:
            - item_number (string): {item_num_instruction}. IMPORTANT: Extract the EXACT item number from each row - do NOT copy item numbers from other rows.
            - description (string): The product name or description.
            - quantity (number): The quantity ordered.
            - unit_of_measure (string): The unit (e.g., EA, Box, KG, msf).
            IMPORTANT: Extract EVERY row as a separate item. Do NOT duplicate item numbers or descriptions from other rows - each row must have its own unique values.
        - confidence_score (number): Float 0.0–1.0 indicating your extraction confidence.
        - reasoning (string): Brief note on any difficulties or assumptions made.

        IMPORTANT: Respond ONLY with a valid JSON object. No markdown, no code fences, no extra text.
        """

        # Model configuration — Production cascade
        BASE_MODEL           = os.environ.get('AZURE_BASE_MODEL', 'gpt-4o-mini')
        PRO_MODEL            = os.environ.get('AZURE_PRO_MODEL',  'gpt-4o')
        CONFIDENCE_THRESHOLD = 0.8

        # --- Dynamic Routing ---
        # When any field-level custom instruction is active, the mini model is unreliable:
        # - For address/materials: it fails on negative constraints ("ignore X, use Y").
        # - For PO: visually ambiguous documents (number+date in same block) cause hallucinations.
        # - For multiple line items: mini model sometimes duplicates item numbers across rows
        #   when descriptions are identical - it copies the first item_number to all rows.
        # Going directly to PRO costs ONE call instead of two (mini fail + PRO correction),
        # so the total time is actually equivalent to the no-customer-ID flow.
        if po_override or address_override or item_num_override:
            print("Custom field override active. Routing directly to PRO model for reliability.")
            BASE_MODEL = PRO_MODEL

        # Force PRO model for documents with multiple line items to avoid item number duplication
        # (mini model copies first item_number to all rows when descriptions are identical)
        # Note: We can't know row count before extraction, but we'll check post-extraction

        # Convert PDF pages to Base64 images (PyMuPDF — no disk I/O)
        try:
            print(f"Converting PDF to images (rotation: {rotation_degrees}°)...")
            page_images_b64 = pdf_bytes_to_base64_images(pdf_bytes, rotation_degrees)
            print(f"PDF converted successfully: {len(page_images_b64)} page(s).")
        except Exception as conv_err:
            import traceback
            print("CRITICAL: Failed to convert PDF to images:")
            traceback.print_exc()
            return jsonify({"error": "Failed to process the PDF file. Please contact IT support."}), 500

        # Call base model (GPT-4o mini)
        try:
            print(f"Sending request to base model ({BASE_MODEL})...")
            extracted_json = call_azure_openai(BASE_MODEL, prompt, page_images_b64)
            print(f"Successfully received response from base model ({BASE_MODEL}).")

            # --- Duplicate Item Number Check ---
            # If we have multiple items but all have the same item_number, it's likely the mini model
            # copied the first item's number to all rows (common when descriptions are identical).
            # Re-extract with PRO model to get accurate item numbers.
            materials = extracted_json.get('materials', [])
            if len(materials) > 1 and BASE_MODEL != PRO_MODEL:
                item_numbers = [m.get('item_number', '') for m in materials]
                # Check if all items have the same item number (duplication issue)
                if len(set(item_numbers)) == 1:
                    print(f"DUPLICATE DETECTED: All {len(materials)} items have same item_number '{item_numbers[0]}'. Escalating to PRO model...")
                    extracted_json = call_azure_openai(PRO_MODEL, prompt, page_images_b64)
                    print(f"PRO correction complete. New materials: {extracted_json.get('materials', [])}")

            # --- Post-PRO Fix: Merge items split by unit of measure ---
            # PRO model sometimes incorrectly splits one row into multiple (MSF + LB for same item)
            # Merge them back into single items with combined quantities
            materials = extracted_json.get('materials', [])
            if len(materials) > 2:
                # Group by item_number + description
                from collections import defaultdict
                merged = defaultdict(lambda: {'quantity': 0, 'unit_of_measure': None})
                for m in materials:
                    key = (m.get('item_number', ''), m.get('description', ''))
                    merged[key]['quantity'] += float(m.get('quantity', 0))
                    merged[key]['unit_of_measure'] = m.get('unit_of_measure', '')
                    merged[key]['description'] = m.get('description', '')
                    merged[key]['item_number'] = m.get('item_number', '')

                # If we merged more than 2 items down to 2, use the merged result
                if len(merged) <= 2 and len(materials) > len(merged):
                    print(f"MERGING: Reduced {len(materials)} items to {len(merged)} after detecting unit-of-measure split")
                    extracted_json['materials'] = [
                        {
                            'item_number': v['item_number'],
                            'description': v['description'],
                            'quantity': v['quantity'],
                            'unit_of_measure': v['unit_of_measure']
                        }
                        for v in merged.values()
                    ]

            # --- Smart PO Validation ---
            # If the customer has a PO override and the extracted PO looks "contaminated"
            # (contains a date like 07/22/25, or has spaces suggesting mixed content),
            # escalate immediately to PRO model to correct it — without always paying the PRO cost.
            po_value = extracted_json.get('purchase_order', '')
            import re
            po_has_date  = bool(re.search(r'\d{1,2}/\d{1,2}/\d{2,4}', str(po_value)))
            po_has_space = ' ' in str(po_value).strip()
            if po_override and (po_has_date or po_has_space):
                print(f"PO value '{po_value}' appears contaminated (date/space detected). Escalating to PRO model.")
                po_fix_prompt = f"""
                The previous model extracted an incorrect Purchase Order number: '{po_value}'.
                It contains extra text (like a date or label) mixed in with the actual PO number.

                Original extraction instructions:
                {prompt}

                Review the PDF carefully and extract ONLY the clean PO number, no dates, no extra text.
                IMPORTANT: Respond ONLY with a valid JSON object.
                """
                extracted_json = call_azure_openai(PRO_MODEL, po_fix_prompt, page_images_b64)
                print(f"PRO correction complete. New PO: {extracted_json.get('purchase_order', '')}")

            # --- Low Confidence Fallback ---
            # If confidence is below threshold and we haven't already escalated, fall back to PRO.
            confidence = extracted_json.get('confidence_score', 0)
            if confidence < CONFIDENCE_THRESHOLD and BASE_MODEL != PRO_MODEL:
                print(f"Confidence score {confidence} is below threshold {CONFIDENCE_THRESHOLD}. Falling back to Pro model ({PRO_MODEL})...")

                correction_prompt = f"""
                The previous base model extracted this data from the PDF but was unsure and had a low confidence score of {confidence}.
                Can you carefully review the original PDF pages and correct any errors in this extraction?

                Previous Extracted Data:
                {json.dumps(extracted_json, indent=2)}

                Original Extraction Instructions to adhere to:
                {prompt}

                IMPORTANT: Respond ONLY with a valid JSON object. Do not include markdown, code fences, or any text outside the JSON.
                """

                extracted_json = call_azure_openai(PRO_MODEL, correction_prompt, page_images_b64)
                print(f"Successfully received response from Pro model ({PRO_MODEL}).")

        except Exception as api_err:
            import traceback
            print("CRITICAL: Azure OpenAI model error (invalid key, deployment not found, or transient failure):")
            traceback.print_exc()
            return jsonify({"error": "An internal error occurred while processing the AI extraction. Please contact IT support."}), 500

        if applied_instructions:
            extracted_json['applied_instructions'] = applied_instructions

        return jsonify(extracted_json), 200

    except Exception as e:
        import traceback
        print("CRITICAL: General extraction route failure:")
        traceback.print_exc()
        return jsonify({"error": "Internal Server Error. Please contact IT support."}), 500


if __name__ == '__main__':
    # Run the Flask app on port 8080 (for local testing)
    app.run(host='0.0.0.0', port=8080)
