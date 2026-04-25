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

## Data Models

### RawWebhook
Stores every webhook event (including duplicates).

| Field | Type | Description |
|---|---|---|
| `id` | BigAutoField | Auto-increment primary key |
| `vendor` | ForeignKey (User) | Authenticated vendor |
| `payload` | JSONField | Raw webhook payload |
| `payload_hash` | CharField(64) | SHA-256 of `username:canonicalized_json` |
| `status` | CharField | `RECEIVED` → `PROCESSING` → `PROCESSED` / `DUPLICATE` / `UNCLASSIFIED` / `FAILED` |
| `created_at` | DateTimeField | Auto-set on creation |
| `updated_at` | DateTimeField | Auto-set on update |

### ShipmentUpdate (Normalized)
| Field | Type |
|---|---|
| `tracking_number` | CharField |
| `status` | `TRANSIT` / `DELIVERED` / `EXCEPTION` |
| `timestamp` | DateTimeField (ISO 8601) |

### InvoiceRecord (Normalized)
| Field | Type |
|---|---|
| `invoice_id` | CharField |
| `amount` | DecimalField |
| `currency` | CharField |

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

### 5. Generic Reusable Services
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
│       ├── test_views.py           # 5 API tests
│       ├── test_processor.py       # 17 processor tests
│       └── test_utils.py           # 13 utility tests
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

---

## Deployment

### API → AWS Lambda (via Zappa)

Zappa packages the Django app and deploys it as a serverless function on AWS Lambda behind API Gateway.

```bash
# Activate a Python 3.12 virtual environment (Lambda requirement)
py -3.12 -m venv venv312
.\venv312\Scripts\activate        # Windows
pip install -r requirements.txt

# First-time deployment
zappa deploy dev

# After code changes
zappa update dev

# View logs
zappa tail dev

# Remove deployment
zappa undeploy dev
```

After deployment, Zappa outputs your API URL:
```
https://<id>.execute-api.us-east-1.amazonaws.com/dev/api/webhooks/ingest/
```

> **Note:** `zappa_settings.json` contains environment variables (secrets) and is **gitignored**. Each developer creates their own from `.env.example`.

### SQS Consumer → EC2

The consumer is a long-running process that polls SQS — it runs on an EC2 instance as a systemd service.

**1. Launch EC2**
- Instance type: `t3.micro` (sufficient for low-moderate traffic)
- AMI: Ubuntu 22.04
- Security group: Allow SSH (port 22) from your IP
- Attach an IAM role with `AmazonSQSFullAccess` (so the consumer can read/delete SQS messages)

**2. SSH in and set up the project**
```bash
# Install Python and Git
sudo apt update && sudo apt install -y python3.12 python3.12-venv git

# Clone repo
git clone <your-repo-url> ~/ai_webhook_service
cd ~/ai_webhook_service

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
nano .env   # fill in: SECRET_KEY, AWS keys, SQS_QUEUE_URL, OPENAI_API_KEY

# Run migrations and create vendor user
python manage.py migrate
python manage.py createsuperuser
```

**3. Install as a systemd service**
```bash
# Copy the service file
sudo cp webhook-consumer.service /etc/systemd/system/

# Reload systemd, enable auto-start, and start the service
sudo systemctl daemon-reload
sudo systemctl enable webhook-consumer
sudo systemctl start webhook-consumer
```

**4. Manage the service**
```bash
# Check if running
sudo systemctl status webhook-consumer

# View live logs
sudo journalctl -u webhook-consumer -f

# View recent logs
sudo journalctl -u webhook-consumer --since "1 hour ago"

# Restart (after code changes)
sudo systemctl restart webhook-consumer

# Stop
sudo systemctl stop webhook-consumer
```

The service auto-restarts on crash (after 10s) and starts on boot.

---

## CI/CD Pipeline (GitHub Actions)

The pipeline is defined in `.github/workflows/ci-cd.yml` and triggers on every push/PR to `main`.

### Pipeline Flow

```
  Push to main
       │
       ▼
  ┌─────────┐
  │  TEST    │  Install deps → migrate → run 35 tests
  └────┬─────┘
       │ (pass)
       ├──────────────────────┐
       ▼                      ▼
  ┌──────────────┐    ┌────────────────┐
  │  DEPLOY API  │    │ DEPLOY CONSUMER│
  │  Zappa →     │    │ SSH → EC2      │
  │  Lambda      │    │ git pull       │
  └──────────────┘    │ pip install    │
                      │ restart service│
                      └────────────────┘
```

### Three Jobs

| Job | Trigger | What It Does |
|---|---|---|
| `test` | Every push & PR | Runs all 35 tests on Python 3.12 |
| `deploy-api` | Push to `main` only | Deploys Django API to AWS Lambda via `zappa update dev` |
| `deploy-consumer` | Push to `main` only | SSHs into EC2, pulls latest code, restarts the SQS consumer service |

### Required GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret | How to get it | Used By |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | From your IAM user credentials (same as in `.env` file) | `deploy-api` |
| `AWS_SECRET_ACCESS_KEY` | From your IAM user credentials (same as in `.env` file) | `deploy-api` |
| `EC2_HOST` | AWS Console → EC2 → Instances → copy **Public IPv4 address** | `deploy-consumer` |
| `EC2_USER` | Default SSH user for the AMI (e.g., `ubuntu` for Ubuntu AMI) | `deploy-consumer` |
| `EC2_SSH_KEY` | AWS Console → EC2 → **Key Pairs** → Create key pair (.pem) → paste the full `.pem` file contents | `deploy-consumer` |

> **Note:** The `test` job requires no secrets — all tests are fully mocked. Secrets are only needed for the two deploy jobs.

---

## Complete Request Flow

```
1. Vendor sends POST /api/webhooks/ingest/ with BasicAuth + JSON body
2. API authenticates vendor via BasicAuth
3. API computes payload_hash = SHA-256(username + canonical_json)
4. API saves RawWebhook(status=RECEIVED, payload, payload_hash) to DB
5. API pushes {"webhook_id": N} to SQS queue
6. API returns {"status": "received", "webhook_id": N}
                        ─── async boundary ───
7. Consumer long-polls SQS, receives message
8. Consumer loads RawWebhook from DB
9. Consumer checks for duplicate (same payload_hash already PROCESSED/PROCESSING)
   → If duplicate: mark DUPLICATE, skip
10. Consumer calls OpenAI LLM to classify payload (Shipment / Invoice / Unclassified)
11. Consumer checks confidence score
    → Below 0.7: mark UNCLASSIFIED, skip
12. Consumer validates + normalizes extracted data
    → Shipment: maps status to TRANSIT/DELIVERED/EXCEPTION, parses timestamp
    → Invoice: validates amount, parses currency
13. Consumer saves ShipmentUpdate or InvoiceRecord, marks RawWebhook as PROCESSED
14. Consumer deletes SQS message
15. On any error: marks RawWebhook as FAILED, logs traceback
```

---

## Tradeoffs & Production Considerations

| Decision | Current | Production Alternative |
|---|---|---|
| Database | SQLite (ephemeral on Lambda) | Amazon RDS (PostgreSQL) |
| Queue | AWS SQS | Already production-ready |
| Auth | HTTP BasicAuth | OAuth2 + API keys |
| Consumer hosting | EC2 systemd service | ECS Fargate / Auto-scaling group |
| Monitoring | Python logging | CloudWatch + OpenTelemetry |
| Secrets | `.env` file / `zappa_settings.json` | AWS Secrets Manager |

### What I'd Add for Production
- **Dead Letter Queue** — failed SQS messages go to a DLQ after N retries
- **Circuit breaker** — for LLM calls (prevent cascade failures)
- **Rate limiting** — per vendor, to prevent abuse
- **Webhook signature verification** — HMAC validation per vendor
- **Horizontal scaling** — multiple consumer instances on ECS
- **Database on RDS** — persistent, not ephemeral like Lambda's /tmp SQLite
- **Structured logging** — JSON logs to CloudWatch for easy searching
