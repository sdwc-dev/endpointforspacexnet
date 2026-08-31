# AI Lead Enrichment Service

A production-ready FastAPI service that enriches Specxnet ERP market leads using **Perplexity sonar-pro**, deployed on **GCP Cloud Run** with **Firebase Firestore** for state management.

---

## Architecture

```
ERP → POST /api/v1/enrich → FastAPI (Cloud Run)
                                  │
                                  ├── Validates api_key + expires_at
                                  ├── Creates job in Firestore
                                  ├── Returns {job_id} immediately
                                  │
                                  └── BackgroundTask: process_enrichment_job()
                                            │
                                            ├── sonar-pro per lead
                                            ├── Progress callbacks every 10%
                                            └── Completion / Failure callback
```

---

## Quick Start (Local)

### 1. Set up environment
```bash
cp .env.example .env
# Edit .env and fill in your values:
#   PERPLEXITY_API_KEY=pplx-...
#   FIREBASE_PROJECT_ID=your-project-id
#   GOOGLE_APPLICATION_CREDENTIALS=/path/to/serviceAccountKey.json
```

### 2. Install dependencies
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Run locally
```bash
uvicorn app.main:app --reload --port 8000
```

### 4. Test with sample request
```bash
curl -X POST http://localhost:8000/api/v1/enrich \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk_live_your_generated_key" \
  -d @tests/fixtures/sample_request.json
```

---

## API Reference

### `POST /api/v1/enrich`
Queues a lead enrichment batch job.

**Header:** `X-API-Key: sk_live_...`

**Request body:**
```json
{
  "data": { "leads": [ { "id": "...", "company_name": "...", ... } ] },
  "callback_url": "https://specxnet.com/api/market_leads/callback",
  "auth_key": "...",
  "file_key": "...",
  "request_id": "REQ-...",
  "expires_at": "2026-05-16T00:00:00Z"
}
```

**Response (immediate):**
```json
{ "status": "success", "message": "Job queued successfully", "job_id": "JOB-..." }
```

---

### `GET /api/v1/status/{job_id}`
Poll job progress.

**Header:** `X-API-Key: sk_live_...`

**Response:**
```json
{
  "job_id": "JOB-...",
  "status": "researching",
  "total_leads": 100,
  "processed_leads": 40,
  "progress_percent": 40.0,
  "avg_confidence": null
}
```

---

### `GET /health`
Liveness probe for Cloud Run.

---

## Error Codes

| HTTP | Error | Cause |
|---|---|---|
| 401 | `invalid_api_key` | `X-API-Key` is missing or invalid |
| 403 | `api_key_revoked` | `X-API-Key` is revoked |
| 400 | `request_expired` | `expires_at` is in the past |
| 422 | Validation error | Malformed JSON / missing required fields |
| 500 | Internal error | Unhandled exception |

---

## Running Tests
```bash
source venv/bin/activate
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

---

## Docker (Local)
```bash
docker build -t ai-lead-enrichment .
docker run -p 8000:8000 --env-file .env ai-lead-enrichment
```

---

## GCP Cloud Run Deployment

### API Keys
Generate API keys for clients using the admin script:
```bash
python scripts/generate_api_key.py "Client Name"
```
Give the key to the client, and the hash will be securely stored in Firestore.

### Prerequisites
1. Enable APIs: Cloud Build, Cloud Run, Artifact Registry, Secret Manager
2. Create Artifact Registry repo: `ai-lead-enrichment`
3. Store secrets in Secret Manager:
   - `PERPLEXITY_API_KEY`
   - `FIREBASE_PROJECT_ID`
4. Grant Cloud Run Service Account access to Firebase

### Deploy
```bash
# One-time setup: create Artifact Registry repo
gcloud artifacts repositories create ai-lead-enrichment \
  --repository-format=docker \
  --location=us-central1

# Deploy via Cloud Build
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=us-central1,_SERVICE_NAME=ai-lead-enrichment,_ARTIFACT_REGISTRY=us-central1-docker.pkg.dev/YOUR_PROJECT_ID/ai-lead-enrichment
```

### Firebase + Cloud Run Auth
On Cloud Run, set the Cloud Run service account as a Firebase/Firestore editor in IAM.  
No `GOOGLE_APPLICATION_CREDENTIALS` file needed — uses Workload Identity automatically.

---

## Firestore Collections

| Collection | Purpose |
|---|---|
| `enrichment_jobs/{job_id}` | Job state, progress counters |
| `enrichment_jobs/{job_id}/lead_results/{lead_id}` | Per-lead enriched data + confidence |
| `audit_log/{auto_id}` | Append-only event log |

---

## Cost Estimate (1,000 leads)
- Perplexity sonar-pro: ~$19.90
- Firebase Firestore reads/writes: ~$0.10
- Cloud Run compute: ~$0.50
- **Total: ~$20.50 per 1,000-lead batch**
