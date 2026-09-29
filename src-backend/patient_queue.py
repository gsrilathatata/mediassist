"""
MediAssist Patient Queue — Azure Table Storage

Persists the patient queue across role screens and browser refreshes.
Flow: Patient kiosk → Nurse triage → Clinician

Table: PatientQueue
  PartitionKey: "ED" (single ED for now)
  RowKey: patient queue ID (e.g. "Q-052")
  Fields: age, sex, symptoms, vitals, arrival, ctas, status, 
          triage_result, discharge_summary, patient_summary, 
          nhs_number, created_at, updated_at
"""

import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("mediassist.queue")

# Try to import Azure Table Storage
try:
    from azure.data.tables import TableServiceClient, TableClient
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    HAS_TABLE_STORAGE = True
except ImportError:
    HAS_TABLE_STORAGE = False
    logger.warning("azure-data-tables not installed — using in-memory queue fallback")


# --- Configuration ---
TABLE_CONNECTION_STRING = os.environ.get(
    "AZURE_TABLE_STORAGE_CONNECTION",
    ""
)
TABLE_NAME = "PatientQueue"
PARTITION_KEY = "ED"


class PatientQueue:
    """
    Manages the patient queue with Azure Table Storage persistence.
    Falls back to in-memory dict if Table Storage is unavailable.
    """

    def __init__(self):
        self._memory_store = {}
        self._table_client = None

        if HAS_TABLE_STORAGE and TABLE_CONNECTION_STRING:
            try:
                service = TableServiceClient.from_connection_string(TABLE_CONNECTION_STRING)
                try:
                    service.create_table(TABLE_NAME)
                    logger.info(f"Created table: {TABLE_NAME}")
                except ResourceExistsError:
                    logger.info(f"Table already exists: {TABLE_NAME}")
                self._table_client = service.get_table_client(TABLE_NAME)
                logger.info("Azure Table Storage connected")
            except Exception as e:
                logger.warning(f"Table Storage init failed, using in-memory: {e}")
        else:
            logger.info("Using in-memory queue (no Table Storage configured)")

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def add_patient(self, patient_data: dict) -> dict:
        """Add a new patient from the kiosk to the queue."""
        queue_id = patient_data.get("id", f"Q-{int(datetime.now().timestamp()) % 10000}")

        entity = {
            "PartitionKey": PARTITION_KEY,
            "RowKey": queue_id,
            "age": str(patient_data.get("age", "")),
            "sex": patient_data.get("sex", ""),
            "symptoms": patient_data.get("symptoms", ""),
            "pain": str(patient_data.get("pain", "")),
            "allergies": patient_data.get("allergies", ""),
            "meds": patient_data.get("meds", ""),
            "arrival": patient_data.get("arrival", "Walk-in"),
            "handover": patient_data.get("handover", ""),
            "pre_hospital": patient_data.get("pre_hospital", ""),
            "nhs_number": patient_data.get("nhs_number", ""),
            "ctas": "pending",
            "status": "waiting",  # waiting → in_triage → triaged → with_clinician → discharged
            "triage_result": "",
            "discharge_summary": "",
            "patient_summary": "",
            "created_at": self._now(),
            "updated_at": self._now(),
        }

        if self._table_client:
            try:
                self._table_client.upsert_entity(entity)
                logger.info(f"Patient {queue_id} added to Table Storage")
            except Exception as e:
                logger.error(f"Failed to add patient to Table Storage: {e}")
                self._memory_store[queue_id] = entity
        else:
            self._memory_store[queue_id] = entity

        return entity

    def update_triage(self, queue_id: str, triage_result: str, ctas: str, nhs_number: str = "") -> dict:
        """Nurse confirms triage — update the patient record."""
        updates = {
            "PartitionKey": PARTITION_KEY,
            "RowKey": queue_id,
            "triage_result": triage_result,
            "ctas": ctas,
            "status": "triaged",
            "updated_at": self._now(),
        }
        if nhs_number:
            updates["nhs_number"] = nhs_number

        if self._table_client:
            try:
                entity = self._table_client.get_entity(PARTITION_KEY, queue_id)
                entity.update(updates)
                self._table_client.upsert_entity(entity)
                logger.info(f"Patient {queue_id} triage updated")
                return entity
            except Exception as e:
                logger.error(f"Failed to update triage in Table Storage: {e}")
                if queue_id in self._memory_store:
                    self._memory_store[queue_id].update(updates)
                    return self._memory_store[queue_id]
        else:
            if queue_id in self._memory_store:
                self._memory_store[queue_id].update(updates)
                return self._memory_store[queue_id]

        return updates

    def assign_to_clinician(self, queue_id: str) -> dict:
        """Move patient from triaged to clinician queue."""
        return self._update_status(queue_id, "with_clinician")

    def update_discharge(self, queue_id: str, discharge_summary: str, patient_summary: str = "") -> dict:
        """Clinician approves discharge — save summaries."""
        updates = {
            "PartitionKey": PARTITION_KEY,
            "RowKey": queue_id,
            "discharge_summary": discharge_summary,
            "patient_summary": patient_summary,
            "status": "discharged",
            "updated_at": self._now(),
        }

        if self._table_client:
            try:
                entity = self._table_client.get_entity(PARTITION_KEY, queue_id)
                entity.update(updates)
                self._table_client.upsert_entity(entity)
                logger.info(f"Patient {queue_id} discharged")
                return entity
            except Exception as e:
                logger.error(f"Failed to update discharge: {e}")
                if queue_id in self._memory_store:
                    self._memory_store[queue_id].update(updates)
                    return self._memory_store[queue_id]
        else:
            if queue_id in self._memory_store:
                self._memory_store[queue_id].update(updates)
                return self._memory_store[queue_id]

        return updates

    def get_patient(self, queue_id: str) -> dict:
        """Get a single patient record."""
        if self._table_client:
            try:
                entity = self._table_client.get_entity(PARTITION_KEY, queue_id)
                return dict(entity)
            except ResourceNotFoundError:
                pass
            except Exception as e:
                logger.error(f"Failed to get patient: {e}")

        return self._memory_store.get(queue_id, None)

    def get_queue(self, status: str = None) -> list:
        """Get all patients, optionally filtered by status."""
        patients = []

        if self._table_client:
            try:
                if status:
                    query = f"PartitionKey eq '{PARTITION_KEY}' and status eq '{status}'"
                else:
                    query = f"PartitionKey eq '{PARTITION_KEY}'"
                entities = self._table_client.query_entities(query)
                patients = [dict(e) for e in entities]
            except Exception as e:
                logger.error(f"Failed to query queue: {e}")
                patients = list(self._memory_store.values())
                if status:
                    patients = [p for p in patients if p.get("status") == status]
        else:
            patients = list(self._memory_store.values())
            if status:
                patients = [p for p in patients if p.get("status") == status]

        # Sort by created_at descending (newest first)
        patients.sort(key=lambda p: p.get("created_at", ""), reverse=True)
        return patients

    def get_clinician_queue(self) -> list:
        """Get patients ready for clinician (triaged or with_clinician)."""
        patients = []
        if self._table_client:
            try:
                query = f"PartitionKey eq '{PARTITION_KEY}' and (status eq 'triaged' or status eq 'with_clinician')"
                entities = self._table_client.query_entities(query)
                patients = [dict(e) for e in entities]
            except Exception as e:
                logger.error(f"Failed to query clinician queue: {e}")
                patients = [p for p in self._memory_store.values() if p.get("status") in ("triaged", "with_clinician")]
        else:
            patients = [p for p in self._memory_store.values() if p.get("status") in ("triaged", "with_clinician")]

        patients.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
        return patients

    def _update_status(self, queue_id: str, new_status: str) -> dict:
        """Generic status update helper."""
        if self._table_client:
            try:
                entity = self._table_client.get_entity(PARTITION_KEY, queue_id)
                entity["status"] = new_status
                entity["updated_at"] = self._now()
                self._table_client.upsert_entity(entity)
                return dict(entity)
            except Exception as e:
                logger.error(f"Failed to update status: {e}")

        if queue_id in self._memory_store:
            self._memory_store[queue_id]["status"] = new_status
            self._memory_store[queue_id]["updated_at"] = self._now()
            return self._memory_store[queue_id]

        return {"RowKey": queue_id, "status": new_status}
