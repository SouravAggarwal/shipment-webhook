# AI Webhook Ingestion Service

A production-grade Django REST Framework service that ingests chaotic vendor webhook payloads via a single API endpoint, classifies them using an LLM (OpenAI GPT-4o-mini via LangChain), normalizes the data into strict schemas (Shipment / Invoice), and persists results to a database — all asynchronously using AWS SQS.

---

## What It Does

Vendors send unstructured JSON payloads (shipment updates, invoices, etc.) to a single `/ingest/` endpoint. The service:

1. **Accepts** the payload instantly (< 200ms) with a `200 OK`
2. **Saves** the raw event to the database (`RawWebhook` with status `RECEIVED`)
3. **Pushes** the webhook ID to an AWS SQS queue for async processing
4. **Classifies** the payload using OpenAI (Shipment? Invoice? Unclassified?)
5. **Validates** the LLM output with Python-side checks (catches hallucinations)
6. **Normalizes** the data into strict schemas and stores it (`ShipmentUpdate` or `InvoiceRecord`)
7. **Deduplicates** using a SHA-256 hash of `username + canonicalized JSON`

---

## Architecture

```
   Vendor A ──┐
   Vendor B ──┤    POST /api/webhooks/ingest/  (BasicAuth)
   Vendor C ──┘
                  │
                  ▼
        ┌─────────────────────┐
        │   Ingestion API     │  Django DRF (AWS Lambda via Zappa)
        │   - Authenticate    │
        │   - Save RawWebhook │
        │   - Push to SQS     │
        │   - Return 200 OK   │
        └────────┬────────────┘
                 │
                 ▼
        ┌─────────────────────┐
        │     AWS SQS Queue   │  Decouples ingestion from processing
        │  (ShipmentQueue)    │  Handles traffic spikes, retries
        └────────┬────────────┘
                 │
                 ▼
        ┌─────────────────────┐
        │  Consumer Worker    │  Django management command (EC2)
        │  - Long-poll SQS    │
        │  - Dedup check      │
        │  - LLM Classify     │  OpenAI GPT-4o-mini via LangChain
        │  - Validate + Store │  ShipmentUpdate / InvoiceRecord
        └────────┬────────────┘
                 │
                 ▼
        ┌─────────────────────┐
        │     Database        │  SQLite (dev) / PostgreSQL (prod)
        └─────────────────────┘
```

---

## AWS Services Used

| Service | Purpose |
|---|---|
| **AWS Lambda** | Hosts the Django API (serverless, via Zappa) |
| **API Gateway** | Exposes the Lambda function as an HTTPS endpoint |
| **S3** | Stores the Zappa deployment package |
| **SQS** | Message queue between API and consumer worker |
| **EC2** | Runs the SQS consumer worker as a systemd service |
| **IAM** | Access control for Lambda, SQS, S3, and EC2 |

---

## Key Design Decisions

### 1. Fast ACK + Async Processing
The API returns `200 OK` immediately after saving and queueing. Heavy work (LLM classification, validation) happens asynchronously in the consumer. This ensures vendors never timeout.

### 2. Save ALL Events (Including Duplicates)
Every webhook is persisted. Duplicates are detected in the consumer via `payload_hash` (SHA-256 of `username:canonicalized_json`) and marked with `status=DUPLICATE`. This gives full audit trail.

### 3. Vendor Identity from Auth
HTTP BasicAuth user = vendor identity. The hash includes the username, so two vendors sending identical payloads are treated as separate events.

### 4. Single LLM Call + Strict Validation
One `ChatOpenAI.with_structured_output()` call classifies and extracts data. Python-side validation (status mapping, timestamp parsing, amount checks) catches LLM hallucinations. Confidence below 0.7 → `UNCLASSIFIED`.

### 5. LLM Rate Limiting via Semaphore
A `threading.Semaphore(5)` in `LLMService` limits concurrent LLM calls to 5 at a time. Extra calls block until a slot is available — preventing API rate limit errors without dropping requests.

### 6. Generic Reusable Services
`LLMService` (in `common/`) and `AWSSQSService` (in `common/`) are fully generic and can be reused by other apps.

---

## Project Structure

```
ai_webhook_service/
├── config/                         # Django project settings
│   ├── settings.py                 # All config (DRF, AWS, OpenAI, Lambda)
│   ├── urls.py                     # URL routing
│   └── wsgi.py                     # WSGI entry (auto-migrate on Lambda)
│
├── webhooks/                       # Main application
│   ├── models.py                   # RawWebhook, ShipmentUpdate, InvoiceRecord
│   ├── views.py                    # POST /api/webhooks/ingest/
│   ├── schemas.py                  # Pydantic models (LLM structured output)
│   ├── constants.py                # LLM prompt, status mapping, enums
│   ├── utils.py                    # canonical_json_hash, normalize_status, parsers
│   ├── admin.py                    # Django admin configuration
│   ├── services/
│   │   └── webhook_processor.py    # WebhookProcessor (classify, validate, store, consume)
│   ├── management/commands/
│   │   └── consume_webhooks.py     # SQS consumer management command
│   └── tests/
│       ├── test_views.py           # API tests
│       ├── test_processor.py       #  processor tests
│
├── common/                         # Reusable generic services
│   ├── sqs_service.py              # AWSSQSService (push, receive, delete)
│   └── llm_service.py              # LLMService (structured output via OpenAI)
│
├── .github/workflows/
│   └── ci-cd.yml                   # GitHub Actions CI/CD pipeline
│
├── webhook-consumer.service        # systemd unit file for EC2 deployment
├── requirements.txt                # Python dependencies
├── .env.example                    # Template for environment variables
├── .gitignore                      # Git ignore rules
└── zappa_settings.json             # Zappa config (gitignored — contains secrets)
```

---

## Local Development Setup

### Prerequisites
- Python 3.12+
- AWS account with SQS queue created
- OpenAI API key

### Step-by-step

```bash
# 1. Navigate to the project
cd ai_webhook_service

# 2. Create and activate virtual environment
python -m venv venv

# Windows:
.\venv\Scripts\activate

# macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your actual keys:
#   SECRET_KEY, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
#   SQS_QUEUE_URL, OPENAI_API_KEY

# 5. Run database migrations
python manage.py migrate

# 6. Create a vendor user (for BasicAuth)
python manage.py createsuperuser

# 7. Start the API server
python manage.py runserver

# 8. Start the SQS consumer (in a separate terminal)
python manage.py consume_webhooks
```

### Run Tests

```bash
python manage.py test webhooks --verbosity=2
```

All 35 tests run without needing AWS or OpenAI credentials (fully mocked).

---

## API Usage

### POST /api/webhooks/ingest/

**Authentication:** HTTP BasicAuth

**Request:**
```bash
curl -X POST http://localhost:8000/api/webhooks/ingest/ \
  -u vendor1:password \
  -H "Content-Type: application/json" \
  -d '{
    "tracking_number": "TRK-12345",
    "status": "delivered",
    "timestamp": "2024-01-15T10:30:00Z",
    "carrier": "FedEx",
    "destination": "New York"
  }'
```

**Response (200 OK):**
```json
{
  "status": "received",
  "webhook_id": 1
}
```

The payload is accepted regardless of structure — the LLM figures out what it is.
