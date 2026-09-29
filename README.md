# MediAssist

**AI-Powered Emergency Department Clinical Decision Support System**

A multi-agent clinical AI system that supports NHS Emergency Department workflows -- from patient self-check-in through AI-assisted triage, clinician review, discharge documentation, and plain-English patient communication.

> **Disclaimer**: This is an AI-assisted clinical decision support tool. All outputs must be validated by a qualified clinician before any clinical action is taken.

---

## Architecture

```
Patient Kiosk (React)
        |
        v
   FastAPI Backend
        |
        v
  Orchestrator Agent  ------>  Azure AI Foundry Agent Service
   /      |       \
  v       v        v
Triage  Discharge  Patient
Agent    Agent     Agent
  |        |         |
  v        v         v
Tools:   Tools:    Tools:
- Symptom  - EHR     - RAG
  Classifier Lookup    Retriever
- EHR      - RAG
  Lookup     Retriever
- RAG
  Retriever
- Triage
  Scorer

Supporting Services:
- Azure AI Search (NICE guidelines RAG)
- Azure Health Data Services (FHIR R4)
- Azure Table Storage (patient queue)
- Azure Content Safety (guardrails)
- Azure Communication Services (email)
```

### Agent Design

All agents use the **ReAct (Reasoning + Acting)** pattern via the Azure AI Foundry Agent Service SDK. The orchestrator delegates to specialised sub-agents, each with its own `AgentsClient` instance to avoid toolset registration conflicts.

| Agent | Role | Tools |
|-------|------|-------|
| **Orchestrator** | Routes requests, evaluates sub-agent outputs, chains multi-step workflows | `run_triage_agent`, `run_discharge_agent`, `run_patient_agent` |
| **Triage** | Classifies symptoms, retrieves NICE guidelines, checks EHR, assigns MTS/CTAS priority | `symptom_classifier`, `ehr_lookup`, `rag_retriever`, `triage_scorer` |
| **Discharge** | Generates structured discharge summaries and GP referral letters | `ehr_lookup`, `rag_retriever` |
| **Patient** | Translates clinical text into plain English (6th-grade reading level) | `rag_retriever` |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React + Tailwind CSS |
| Backend | Python / FastAPI |
| Agent Framework | Azure AI Foundry Agent Service (SDK v2) |
| LLM | Configurable (default: GPT-4o-mini / Llama 3.2 3B Instruct) |
| Fine-tuning | QLoRA on BioMistral 7B + Llama 3.3 70B |
| RAG | Azure AI Search over NICE clinical guidelines |
| EHR Integration | FHIR R4 via Azure Health Data Services |
| Queue | Azure Table Storage |
| Guardrails | Azure AI Content Safety + custom clinical checks |
| Email | Azure Communication Services |
| PHI Protection | Regex-based scrubber (NHS numbers, phones, postcodes, DOBs) |
| Auth | Azure Managed Identity / DefaultAzureCredential |

---

## Repository Structure

```
MediAssist/
  src-backend/
    app.py                     # FastAPI REST API
    orchestrator_agent.py      # Central orchestrator agent
    triage_agent.py            # Triage sub-agent
    discharge_agent.py         # Discharge sub-agent
    patient_agent.py           # Patient communication sub-agent
    guardrails.py              # Input/output content safety
    patient_queue.py           # Queue state machine (Table Storage)
    fhir_writeback.py          # FHIR R4 write-back
    email_service.py           # Discharge email via ACS
    tools/
      symptom_classifier.py    # Keyword-based MTS symptom classification
      ehr_lookup.py            # FHIR patient history retrieval
      rag_retriever.py         # NICE guidelines from Azure AI Search
      triage_scorer.py         # CTAS/MTS dual-standard scoring
      phi_scrubber.py          # PHI detection and redaction
  src-frontend/
    src/
      App.jsx                  # React single-page application
  src-training/
    train_adapter.py           # QLoRA fine-tuning script
    submit_training.py         # Azure ML training job submission
  data/
    ScrapeData.py              # Training data preparation
  .github/
    workflows/
      deploy.yml               # CI/CD pipeline
```

---

## Key Features

### 1. Patient Self-Check-In Kiosk
Patients enter symptoms, demographics, and NHS number via a React frontend. The system auto-triages on submission.

### 2. AI Triage (5-Step ReAct)
1. **Classify** -- Maps symptoms to clinical category (cardiac, respiratory, neurological, etc.)
2. **Retrieve guidelines** -- Fetches relevant NICE guidelines via RAG
3. **Check history** -- Pulls EHR data (conditions, allergies, medications) via FHIR
4. **Score** -- Assigns MTS (1-5) and CTAS (I-V) priority with discriminator reasoning
5. **Synthesise** -- Produces structured triage note with confidence score and escalation flag

### 3. Nurse Triage Screen
Nurses review AI triage recommendations, confirm or override priority, and advance patients to clinician review.

### 4. Clinician Discharge
Clinicians review the full patient record, generate a structured discharge summary, and trigger:
- FHIR write-back (Encounter + DocumentReference)
- Plain-English patient summary
- Discharge email to the patient

### 5. Guardrails
- **Input**: prompt injection detection, content safety screening, high-risk keyword flagging (suicidal ideation, safeguarding concerns), red-flag symptom escalation
- **Output**: content safety check, auto-appended clinician validation disclaimer, escalation notices

### 6. PHI Scrubbing
All orchestrator outputs are scrubbed for NHS numbers, phone numbers, emails, postcodes, dates of birth, and IP addresses before returning to the frontend.

---

## Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- Azure subscription with:
  - Azure AI Foundry project
  - Azure AI Search service (with NICE guidelines index)
  - Azure Health Data Services (FHIR R4)
  - Azure Content Safety
  - Azure Communication Services (optional, for email)
  - Azure Table Storage (optional, falls back to in-memory)

### Environment Variables

```bash
# Azure AI Foundry
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-resource.services.ai.azure.com/api/projects/your-project
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4o-mini-1

# Azure AI Search (NICE guidelines RAG)
AZURE_SEARCH_ENDPOINT=https://your-search-service.search.windows.net
AZURE_SEARCH_API_KEY=your-search-api-key
AZURE_SEARCH_INDEX=nice-guidelines

# Azure Health Data Services (FHIR)
FHIR_SERVER_URL=https://your-fhir-service.fhir.azurehealthcareapis.com

# Azure Content Safety
CONTENT_SAFETY_ENDPOINT=https://your-region.api.cognitive.microsoft.com/
CONTENT_SAFETY_KEY=your-content-safety-key

# Azure Communication Services (email)
AZURE_COMMUNICATION_CONNECTION_STRING=your-acs-connection-string
SENDER_EMAIL=DoNotReply@your-acs-domain.azurecomm.net

# Azure Table Storage (patient queue)
AZURE_STORAGE_CONNECTION_STRING=your-storage-connection-string

# Frontend
REACT_APP_API_URL=http://localhost:8000
```

### Run Locally

```bash
# Backend
cd src-backend
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000

# Frontend
cd src-frontend
npm install
npm start
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/mediassist` | Main agentic endpoint (triage, discharge, patient explanation) |
| POST | `/api/queue/patient` | Patient self-check-in (kiosk) |
| GET | `/api/queue/nurse` | Nurse triage queue |
| POST | `/api/queue/triage` | Confirm/override triage |
| GET | `/api/queue/clinician` | Clinician review queue |
| POST | `/api/queue/discharge` | Discharge patient |
| GET | `/api/queue/{id}` | Get patient by queue ID |
| GET | `/health` | Health check |

---

## Deployment

### Azure App Service

```bash
# Backend
az webapp up --name your-app-name --resource-group your-resource-group --runtime "PYTHON:3.11"

# Frontend (static web app or App Service)
cd src-frontend
npm run build
az webapp up --name your-frontend-app --resource-group your-resource-group --html
```

Set all environment variables in the App Service Configuration blade.

---

## Fine-Tuning

The `src-training/` directory contains scripts for QLoRA fine-tuning of clinical language models:

- **BioMistral 7B** -- Fine-tuned on medical transcription data for clinical terminology
- **Llama 3.3 70B** -- Fine-tuned for structured triage output generation

Training jobs are submitted to Azure ML via `submit_training.py`.

---

## Security & Compliance

- All credentials loaded from environment variables (no hardcoded secrets)
- Azure Managed Identity (DefaultAzureCredential) for service-to-service auth
- PHI scrubbing on all agent outputs
- Input/output guardrails via Azure Content Safety
- FHIR R4 standard for clinical data interoperability
- Prompt injection detection on all user inputs

---

## Disclaimer

This system is designed as **clinical decision support only**. It does not replace clinical judgement. All AI-generated outputs must be reviewed and validated by a qualified clinician before any clinical action is taken.

---

## License

MIT