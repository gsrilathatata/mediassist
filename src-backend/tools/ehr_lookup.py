"""
MediAssist Tool 2: ehr_lookup

Queries Azure Health Data Services (FHIR R4) to retrieve patient history,
conditions, allergies, and medications.
Uses the FHIR REST API with Azure credential authentication.
"""

import os
import json
import requests
from azure.identity import DefaultAzureCredential


FHIR_ENDPOINT = os.environ.get(
    "FHIR_ENDPOINT",
    "your_fhir_api_path"
)


def _get_fhir_token():
    """Get an access token for the FHIR service."""
    credential = DefaultAzureCredential()
    token = credential.get_token(f"{FHIR_ENDPOINT}/.default")
    return token.token


def _fhir_get(resource_path: str) -> dict:
    """Make an authenticated GET request to the FHIR service."""
    token = _get_fhir_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/fhir+json"
    }
    response = requests.get(
        f"{FHIR_ENDPOINT}/{resource_path}",
        headers=headers,
        verify=True
    )
    if response.status_code == 200:
        return response.json()
    else:
        return {"error": f"FHIR request failed: {response.status_code}", "detail": response.text}


def ehr_lookup(nhs_number: str) -> str:
    """
    Looks up a patient's medical history from the Electronic Health Record
    using Azure Health Data Services FHIR API.
    Returns patient demographics, conditions, allergies, and current medications.

    :param nhs_number: The patient's NHS number, e.g. 'NHS-7234891'
    :return: JSON string with patient history including conditions, allergies, and medications.
    """

    result = {
        "patient": None,
        "conditions": [],
        "allergies": [],
        "medications": [],
        "status": "success"
    }

    # Step 1: Find the patient by NHS number
    patient_bundle = _fhir_get(f"Patient?identifier=https://fhir.nhs.uk/Id/nhs-number|{nhs_number}")

    if "error" in patient_bundle:
        return json.dumps({"status": "error", "message": patient_bundle["error"]})

    entries = patient_bundle.get("entry", [])
    if not entries:
        return json.dumps({"status": "not_found", "message": f"No patient found with NHS number {nhs_number}"})

    patient = entries[0]["resource"]
    patient_id = patient["id"]

    # Extract patient demographics
    name = patient.get("name", [{}])[0]
    result["patient"] = {
        "id": patient_id,
        "nhs_number": nhs_number,
        "name": f"{' '.join(name.get('given', []))} {name.get('family', '')}",
        "gender": patient.get("gender", "unknown"),
        "birth_date": patient.get("birthDate", "unknown")
    }

    # Step 2: Get conditions
    conditions_bundle = _fhir_get(f"Condition?subject=Patient/{patient_id}")
    for entry in conditions_bundle.get("entry", []):
        resource = entry["resource"]
        coding = resource.get("code", {}).get("coding", [{}])[0]
        clinical = resource.get("clinicalStatus", {}).get("coding", [{}])[0]
        result["conditions"].append({
            "condition": coding.get("display", "Unknown"),
            "code": coding.get("code", ""),
            "status": clinical.get("code", "unknown")
        })

    # Step 3: Get allergies
    allergies_bundle = _fhir_get(f"AllergyIntolerance?patient=Patient/{patient_id}")
    for entry in allergies_bundle.get("entry", []):
        resource = entry["resource"]
        coding = resource.get("code", {}).get("coding", [{}])[0]
        result["allergies"].append({
            "allergy": coding.get("display", "Unknown"),
            "code": coding.get("code", "")
        })

    # Step 4: Get medications
    meds_bundle = _fhir_get(f"MedicationRequest?subject=Patient/{patient_id}")
    for entry in meds_bundle.get("entry", []):
        resource = entry["resource"]
        coding = resource.get("medicationCodeableConcept", {}).get("coding", [{}])[0]
        result["medications"].append({
            "medication": coding.get("display", "Unknown"),
            "status": resource.get("status", "unknown")
        })

    return json.dumps(result)


# Quick test
if __name__ == "__main__":
    print("Looking up patient NHS-7234891...")
    result = ehr_lookup("NHS-7234891")
    parsed = json.loads(result)
    print(json.dumps(parsed, indent=2))