"""
MediAssist FHIR Write-Back

Writes triage results and discharge summaries back to
Azure Health Data Services (FHIR R4).
"""

import os
import json
import logging
import base64
from datetime import datetime, timezone

logger = logging.getLogger("mediassist.fhir")

try:
    import requests
    from azure.identity import DefaultAzureCredential
    HAS_FHIR = True
except ImportError:
    HAS_FHIR = False

FHIR_ENDPOINT = os.environ.get(
    "FHIR_ENDPOINT",
    "you_fhir_api_path"
)


def _fhir_post(resource_path, data):
    """Make an authenticated POST to FHIR."""
    if not HAS_FHIR:
        return {"status": "skipped", "reason": "FHIR deps not available"}
    try:
        credential = DefaultAzureCredential()
        token = credential.get_token(f"{FHIR_ENDPOINT}/.default").token
        response = requests.post(
            f"{FHIR_ENDPOINT}/{resource_path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/fhir+json",
            },
            json=data,
            verify=True,
        )
        if response.status_code in (200, 201):
            return {"status": "success", "id": response.json().get("id", "")}
        else:
            logger.warning(f"FHIR write failed: {response.status_code}")
            return {"status": "error", "code": response.status_code, "detail": response.text[:200]}
    except Exception as e:
        logger.warning(f"FHIR write-back failed: {e}")
        return {"status": "error", "message": str(e)}


def write_triage(nhs_number: str, triage_result: str, ctas: str, queue_id: str = "") -> dict:
    """Write triage as Encounter + DocumentReference."""
    now = datetime.now(timezone.utc).isoformat()

    priority_map = {
        "ctas1": {"code": "em", "display": "Emergency"},
        "ctas2": {"code": "ur", "display": "Urgent"},
        "ctas3": {"code": "ur", "display": "Urgent"},
        "ctas4": {"code": "r", "display": "Routine"},
        "ctas5": {"code": "r", "display": "Routine"},
    }
    priority = priority_map.get(ctas, {"code": "r", "display": "Routine"})

    encounter = {
        "resourceType": "Encounter",
        "status": "in-progress",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER", "display": "Emergency"},
        "priority": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority", "code": priority["code"], "display": priority["display"]}]},
        "subject": {"identifier": {"system": "https://fhir.nhs.uk/Id/nhs-number", "value": nhs_number}},
        "period": {"start": now},
    }

    enc_result = _fhir_post("Encounter", encounter)
    encounter_id = enc_result.get("id", "")

    if encounter_id:
        encoded = base64.b64encode(triage_result.encode()).decode()
        doc_ref = {
            "resourceType": "DocumentReference",
            "status": "current",
            "type": {"coding": [{"system": "http://loinc.org", "code": "34878-9", "display": "Emergency medicine Note"}]},
            "subject": {"identifier": {"system": "https://fhir.nhs.uk/Id/nhs-number", "value": nhs_number}},
            "date": now,
            "description": f"MediAssist AI Triage - {queue_id}",
            "content": [{"attachment": {"contentType": "text/plain", "data": encoded, "title": f"Triage {ctas}"}}],
            "context": {"encounter": [{"reference": f"Encounter/{encounter_id}"}]},
        }
        _fhir_post("DocumentReference", doc_ref)

    logger.info(f"FHIR triage written: encounter={encounter_id}")
    return {"status": "success", "encounter_id": encounter_id}


def write_discharge(nhs_number: str, discharge_summary: str, encounter_id: str = "") -> dict:
    """Write discharge summary as DocumentReference."""
    now = datetime.now(timezone.utc).isoformat()
    encoded = base64.b64encode(discharge_summary.encode()).decode()

    doc_ref = {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {"coding": [{"system": "http://loinc.org", "code": "18842-5", "display": "Discharge summary"}]},
        "subject": {"identifier": {"system": "https://fhir.nhs.uk/Id/nhs-number", "value": nhs_number}},
        "date": now,
        "description": "MediAssist AI Discharge Summary",
        "content": [{"attachment": {"contentType": "text/plain", "data": encoded, "title": "Discharge Summary"}}],
    }
    if encounter_id:
        doc_ref["context"] = {"encounter": [{"reference": f"Encounter/{encounter_id}"}]}

    result = _fhir_post("DocumentReference", doc_ref)
    logger.info(f"FHIR discharge written: {result.get('id', '')}")
    return result
