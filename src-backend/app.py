"""
MediAssist API — Agentic Backend v2.1

FastAPI service with:
  1. Agentic orchestrator (ReAct multi-agent)
  2. Patient queue persistence (Azure Table Storage / in-memory fallback)
  
Full flow: Patient kiosk → Nurse triage → Clinician discharge → Patient summary
"""

import logging
import os
import threading
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from orchestrator_agent import MediAssistOrchestrator
from patient_queue import PatientQueue
from email_service import send_discharge_email
from guardrails import validate_input, validate_output
from fhir_writeback import write_triage, write_discharge
import json as _json
import re



# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("mediassist.api")


# --- Global instances ---
orchestrator: MediAssistOrchestrator = None
queue: PatientQueue = None
_init_lock = threading.Lock()
_init_error: str = None


def get_orchestrator():
    global orchestrator, _init_error
    if orchestrator is not None:
        return orchestrator
    with _init_lock:
        if orchestrator is not None:
            return orchestrator
        if _init_error:
            raise HTTPException(status_code=503, detail=f"Agent init failed: {_init_error}")
        try:
            logger.info("Initialising orchestrator (first request)...")
            orchestrator = MediAssistOrchestrator()
            logger.info("Orchestrator and all sub-agents ready")
            return orchestrator
        except Exception as e:
            _init_error = str(e)
            logger.error(f"Failed to initialise orchestrator: {e}")
            raise HTTPException(status_code=503, detail=f"Agent init failed: {e}")


def get_queue():
    global queue
    if queue is None:
        queue = PatientQueue()
    return queue


# --- FastAPI app ---
app = FastAPI(
    title="MediAssist API",
    description="Agentic AI clinical decision support for Emergency Departments",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# REQUEST / RESPONSE MODELS
# ============================================================

class MediAssistRequest(BaseModel):
    message: str
    nhs_number: str = ""

class MediAssistResponse(BaseModel):
    agent: str
    status: str
    response: str
    phi_entities_removed: int = 0

class PatientSubmitRequest(BaseModel):
    id: str = ""
    age: str = ""
    sex: str = ""
    symptoms: str
    pain: Optional[str] = ""
    allergies: str = ""
    meds: str = ""
    arrival: str = "Walk-in"
    handover: str = ""
    pre_hospital: str = ""
    nhs_number: str = ""

class TriageUpdateRequest(BaseModel):
    queue_id: str
    triage_result: str
    ctas: str
    nhs_number: str = ""

class DischargeUpdateRequest(BaseModel):
    queue_id: str
    discharge_summary: str
    patient_summary: str = ""
    patient_email: str = ""
    patient_name: str = ""


# ============================================================
# AGENT ENDPOINT
# ============================================================

@app.post("/api/mediassist", response_model=MediAssistResponse)
def process_request(req: MediAssistRequest):
    """Main agentic endpoint with input/output guardrails."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # INPUT GUARDRAILS
    input_check = validate_input(req.message)
    if not input_check["valid"]:
        return MediAssistResponse(
            agent="guardrails",
            status="blocked",
            response=input_check["reason"],
            phi_entities_removed=0,
        )

    orch = get_orchestrator()
    logger.info(f"Request received (NHS: {req.nhs_number or 'none'}, flags: {input_check['flags']})")

    try:
        result = orch.process(message=req.message, nhs_number=req.nhs_number)

        # OUTPUT GUARDRAILS
        output_check = validate_output(result["response"], input_check["flags"])
        result["response"] = output_check["modified_response"]

        return MediAssistResponse(**result)
    except Exception as e:
        logger.error(f"Request processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="MediAssist encountered an error.")


# ============================================================
# QUEUE ENDPOINTS — Patient → Nurse → Clinician → Patient
# ============================================================

# --- 1. PATIENT KIOSK ---

@app.post("/api/queue/patient")
def add_patient(req: PatientSubmitRequest):
    """Patient kiosk: submit new patient to the queue.
    Validates input with guardrails before running AI triage."""

    # INPUT GUARDRAILS — block non-clinical submissions
    input_check = validate_input(req.symptoms)
    if not input_check["valid"]:
        raise HTTPException(status_code=400, detail=input_check["reason"])

    q = get_queue()
    
    entity = q.add_patient(req.dict())
    queue_id = entity["RowKey"]
    
    # Run AI triage automatically
    try:
        orch = get_orchestrator()
        message = f"Patient: {req.sex or 'Unknown'}, {req.age or 'Unknown'} years old, arrival: {req.arrival}. Symptoms: {req.symptoms}. Pain: {req.pain or 'not stated'}/10. Allergies: {req.allergies or 'none'}. Medications: {req.meds or 'none'}."
        
        result_text = orch._run_triage(message)
        response_text = result_text if isinstance(result_text, str) else _json.dumps(result_text)
        result = {"response": response_text}
        
        ctas = "pending"
        try:
            response_json = _json.loads(result['response'])
            mts = str(response_json.get("mts_level", ""))
            if mts in {"1", "2", "3", "4", "5"}:
                ctas = f"ctas{mts}"
        except Exception as e:
            logger.exception(e)
            
        logger.info(f"CTAS parse for {queue_id}: detected={ctas}, response_snippet={result}")
        
        q.update_triage(queue_id, response_text, ctas, req.nhs_number)
        logger.info(f"Auto-triage complete for {queue_id}: {ctas}")
    except Exception as e:
        logger.warning(f"Auto-triage failed for {queue_id}: {e}")

    return {
        "status": "ok",
        "queue_id": queue_id,
        "message": "Patient added to queue"
    }


@app.get("/api/queue/patient/{queue_id}/summary")
def get_patient_summary(queue_id: str):
    """Patient kiosk: poll for discharge summary.
    Returns the plain English summary once clinician approves discharge."""
    q = get_queue()
    patient = q.get_patient(queue_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {queue_id} not found")
    if patient.get("status") == "discharged" and patient.get("patient_summary"):
        return {
            "status": "ready",
            "queue_id": queue_id,
            "patient_summary": patient["patient_summary"],
            "discharge_summary": patient.get("discharge_summary", ""),
        }
    return {
        "status": "pending",
        "queue_id": queue_id,
        "current_status": patient.get("status", "unknown"),
        "message": "Your summary is not ready yet. Please wait."
    }


# --- 2. NURSE TRIAGE ---

@app.get("/api/queue/nurse")
def get_nurse_queue():
    """Nurse screen: get all patients that need nurse attention.
    Includes waiting, auto-triaged (need vitals + confirmation), and in_triage."""
    q = get_queue()
    waiting = q.get_queue(status="waiting")
    triaged = q.get_queue(status="triaged")
    in_triage = q.get_queue(status="in_triage")
    all_patients = waiting + triaged + in_triage
    # Sort by CTAS urgency: ctas1 first, pending last
    ctas_order = {"ctas1": 0, "ctas2": 1, "ctas3": 2, "ctas4": 3, "ctas5": 4, "pending": 5}
    all_patients.sort(key=lambda p: ctas_order.get(p.get("ctas", "pending"), 5))
    return {
        "status": "ok",
        "total": len(all_patients),
        "waiting": len(waiting) + len(triaged),
        "in_triage": len(in_triage),
        "patients": all_patients
    }


@app.post("/api/queue/triage/start/{queue_id}")
def start_triage(queue_id: str):
    """Nurse selects a patient — mark as in_triage."""
    q = get_queue()
    entity = q._update_status(queue_id, "in_triage")
    return {"status": "ok", "queue_id": queue_id, "message": "Patient moved to in_triage"}


@app.post("/api/queue/triage")
def confirm_triage(req: TriageUpdateRequest):
    """Nurse confirms triage result — saves to queue + writes to FHIR."""
    q = get_queue()
    entity = q.update_triage(req.queue_id, req.triage_result, req.ctas, req.nhs_number)

    # FHIR write-back
    fhir_result = None
    if req.nhs_number:
        try:
            fhir_result = write_triage(req.nhs_number, req.triage_result, req.ctas, req.queue_id)
        except Exception as e:
            logger.warning(f"FHIR triage write-back failed: {e}")

    return {
        "status": "ok",
        "queue_id": req.queue_id,
        "message": "Triage confirmed — patient moved to clinician queue",
        "fhir": fhir_result,
    }


# --- 3. CLINICIAN ---

@app.get("/api/queue/clinician")
def get_clinician_queue():
    """Clinician screen: get patients ready for clinical review (triaged or with_clinician)."""
    q = get_queue()
    patients = q.get_clinician_queue()
    return {
        "status": "ok",
        "count": len(patients),
        "patients": patients
    }


@app.post("/api/queue/clinician/assign/{queue_id}")
def assign_to_clinician(queue_id: str):
    """Clinician picks up a patient — mark as with_clinician."""
    q = get_queue()
    entity = q.assign_to_clinician(queue_id)
    return {"status": "ok", "queue_id": queue_id, "message": "Patient assigned to clinician"}


@app.post("/api/queue/discharge")
def update_discharge(req: DischargeUpdateRequest):
    """Clinician approves discharge — saves summaries and emails patient."""
    q = get_queue()
    entity = q.update_discharge(req.queue_id, req.discharge_summary, req.patient_summary)

    email_result = None
    if req.patient_email and req.patient_summary:
        email_result = send_discharge_email(
            to_email=req.patient_email,
            patient_name=req.patient_name,
            patient_summary=req.patient_summary,
            queue_id=req.queue_id,
        )

    # FHIR write-back
    fhir_result = None
    nhs = req.patient_name  # Using patient_name field; ideally would have nhs_number
    q_patient = q.get_patient(req.queue_id)
    nhs_num = q_patient.get("nhs_number", "") if q_patient else ""
    if nhs_num and req.discharge_summary:
        try:
            fhir_result = write_discharge(nhs_num, req.discharge_summary)
        except Exception as e:
            logger.warning(f"FHIR discharge write-back failed: {e}")

    return {
        "status": "ok",
        "queue_id": req.queue_id,
        "message": "Discharge approved — patient summary available",
        "email": email_result,
        "fhir": fhir_result,
    }


# --- GENERAL QUEUE ---

@app.get("/api/queue")
def get_full_queue(status: str = None):
    """Admin/debug: get full queue optionally filtered by status."""
    q = get_queue()
    patients = q.get_queue(status=status)
    return {"status": "ok", "count": len(patients), "patients": patients}


@app.delete("/api/queue/{queue_id}")
def delete_patient(queue_id: str):
    """Delete a patient from the queue."""
    q = get_queue()
    if q._table_client:
        try:
            q._table_client.delete_entity("ED", queue_id)
        except Exception:
            pass
    q._memory_store.pop(queue_id, None)
    return {"status": "ok", "message": f"Patient {queue_id} deleted"}


@app.delete("/api/queue")
def clear_queue():
    """Clear all patients from the queue (demo reset)."""
    q = get_queue()
    if q._table_client:
        try:
            entities = q._table_client.query_entities("PartitionKey eq 'ED'")
            for e in entities:
                q._table_client.delete_entity(e["PartitionKey"], e["RowKey"])
        except Exception as ex:
            logger.warning(f"Failed to clear table: {ex}")
    q._memory_store.clear()
    return {"status": "ok", "message": "Queue cleared"}


@app.get("/api/queue/{queue_id}")
def get_patient(queue_id: str):
    """Get a single patient record by queue ID."""
    q = get_queue()
    patient = q.get_patient(queue_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {queue_id} not found")
    return {"status": "ok", "patient": patient}


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "2.1.0",
        "architecture": "agentic",
        "agents_ready": orchestrator is not None,
        "queue_backend": "table_storage" if (queue and queue._table_client) else "in_memory",
        "agents": ["orchestrator", "triage", "discharge", "patient"],
        "tools": ["symptom_classifier", "ehr_lookup", "rag_retriever", "triage_scorer"],
        "phi_scrubber": "active",
        "queue_endpoints": [
            "POST /api/queue/patient",
            "GET /api/queue/nurse",
            "POST /api/queue/triage",
            "GET /api/queue/clinician",
            "POST /api/queue/discharge",
            "GET /api/queue/patient/{id}/summary",
        ],
    }


@app.get("/")
def root():
    return {
        "service": "MediAssist API",
        "version": "2.1.0",
        "architecture": "Multi-agent ReAct with dynamic orchestration + persistent queue",
        "stack": "Azure AI Foundry Agent Service + gpt-4o-mini",
    }