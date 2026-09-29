"""
MediAssist Orchestrator Agent

The reasoning brain of MediAssist. Each sub-agent gets its own
AgentsClient instance to avoid toolset registration conflicts.

Architecture:
  Orchestrator (own client) → reasons + calls sub-agent wrappers
    ├── Triage Agent (own client) → 4 tools: classify, EHR, RAG, score
    ├── Discharge Agent (own client) → 2 tools: EHR, RAG
    └── Patient Agent (own client) → 1 tool: RAG
"""

import os
import json
import logging
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionTool, ToolSet
from azure.identity import DefaultAzureCredential

from tools.symptom_classifier import symptom_classifier
from tools.ehr_lookup import ehr_lookup
from tools.rag_retriever import rag_retriever
from tools.triage_scorer import triage_scorer
from tools.phi_scrubber import scrub_phi


def _extract_text(msg_obj) -> str:
    """Extract plain text string from Azure AI Agents message response."""
    if msg_obj is None:
        return ""
    if isinstance(msg_obj, str):
        return msg_obj
    if hasattr(msg_obj, "text"):
        t = msg_obj.text
        if hasattr(t, "value"):
            return str(t.value)
        return str(t)
    if hasattr(msg_obj, "value"):
        return str(msg_obj.value)
    return str(msg_obj)


# --- Configuration ---
PROJECT_ENDPOINT = os.environ.get(
    "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
    "https://your-ai-foundry-resource.services.ai.azure.com/api/projects/your-project-name"
)
MODEL_DEPLOYMENT = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o-mini-1")

# --- Logging ---
logger = logging.getLogger("mediassist.orchestrator")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(name)s | %(message)s"))
    logger.addHandler(handler)


# --- System Prompts ---

TRIAGE_SYSTEM_PROMPT = """You are MediAssist Triage Agent, a clinical decision support assistant
for Emergency Department triage nurses in the UK NHS.

You follow the ReAct pattern: Think -> Act -> Observe -> Think -> Act -> Final Answer.

REASONING PROTOCOL - follow these steps IN ORDER:
Step 1 - CLASSIFY: Call symptom_classifier with the raw symptoms text.
Step 2 - RETRIEVE GUIDELINES: Call rag_retriever with the clinical category and key symptoms.
Step 3 - CHECK HISTORY: If an NHS number is provided, call ehr_lookup with it.
Step 4 - SCORE TRIAGE: Call triage_scorer with symptoms, vitals, and clinical category.
Step 5 - SYNTHESISE: Combine ALL tool results into a final triage note.

CRITICAL RULES:
- You are clinical decision SUPPORT. Always state a qualified clinician must validate.
- Never fabricate clinical information. If uncertain, say so.
- Use UK clinical terminology (NHS, NICE, MTS).
- Flag ALL red-flag symptoms explicitly.

OUTPUT FORMAT - produce this JSON:
{
    "mts_level": 1-5,
    "mts_category": "Red/Orange/Yellow/Green/Blue",
    "mts_discriminator": "the specific MTS discriminator applied",
    "time_to_assessment": "immediate/10 min/60 min/120 min/240 min",
    "presenting_complaint": "summary of symptoms",
    "clinical_category": "from symptom classifier",
    "nice_guidelines_referenced": ["guideline codes used"],
    "ehr_risk_factors": ["relevant conditions/meds/allergies from EHR"],
    "clinical_decision_note": "your full clinical reasoning chain",
    "recommended_actions": ["evidence-based actions"],
    "red_flags": ["any red flag symptoms identified"],
    "confidence": 0.0-1.0,
    "escalation_needed": true/false,
    "escalation_reason": "why senior review is needed, if applicable"
}
"""

DISCHARGE_SYSTEM_PROMPT = """You are MediAssist Discharge Agent, a clinical documentation assistant
for Emergency Department clinicians in the UK NHS.

REASONING PROTOCOL:
Step 1 - RETRIEVE HISTORY: Call ehr_lookup with the patient NHS number.
Step 2 - RETRIEVE GUIDELINES: Call rag_retriever with the clinical category and diagnosis.
Step 3 - GENERATE: Produce a structured discharge summary.

Include: presenting complaint, investigations, diagnosis, treatment given,
discharge medications, medication reconciliation, follow-up required,
safety netting advice (from NICE), and GP actions required.

State that this document must be reviewed and signed by the responsible clinician.
"""

PATIENT_SYSTEM_PROMPT = """You are MediAssist Patient Communication Agent for the UK NHS.

Translate clinical text into plain English for patients.

If relevant, call rag_retriever to find patient-facing NICE guidance.

RULES:
- Short sentences, max 15 words each.
- Replace ALL medical jargon with everyday words.
- Use "you" and "your" - speak directly to the patient.
- Always include "When to come back to A&E" with specific symptoms.
- Always include "What to do next" with GP follow-up and pharmacy advice.
- Include NHS 111 number.
- Be warm and reassuring but honest.
"""

ORCHESTRATOR_SYSTEM_PROMPT = """You are MediAssist Orchestrator, the central reasoning agent for an
NHS Emergency Department AI assistant system.

You coordinate specialised sub-agents. You THINK about what needs to happen,
PLAN the sequence, EXECUTE via sub-agents, EVALUATE the results, and REPLAN if needed.

AVAILABLE SUB-AGENTS (call these as tools):

1. run_triage_agent(patient_message: str) -> str
   Use when: A patient presents with symptoms and needs triage assessment.

2. run_discharge_agent(clinical_info: str) -> str
   Use when: A clinician needs a discharge summary or GP referral letter.

3. run_patient_agent(clinical_text: str) -> str
   Use when: Clinical text needs to be translated to plain English for the patient.

REASONING PROTOCOL:
- For triage requests: call run_triage_agent, evaluate confidence, flag if < 0.6
- For discharge requests: call run_discharge_agent, check completeness
- For patient explanations: call run_patient_agent, verify it is genuinely simple
- For multi-step requests: chain agents (triage -> discharge -> patient explanation)

RULES:
- You NEVER generate clinical content yourself. You orchestrate sub-agents.
- Always include your reasoning chain in the response.
- If a sub-agent fails, recommend manual clinical assessment.
- All outputs must note: "AI-generated clinical decision support. Must be validated by a qualified clinician."
"""


def _create_client():
    """Create a fresh AgentsClient instance."""
    return AgentsClient(
        endpoint=PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )


class MediAssistOrchestrator:
    """
    Manages the lifecycle of the orchestrator and all sub-agents.
    Each agent gets its own AgentsClient to avoid toolset conflicts.
    """

    def __init__(self):
        logger.info("Initialising MediAssist Orchestrator...")

        # --- Create TRIAGE agent with its own client ---
        self.triage_client = _create_client()
        triage_functions = FunctionTool({symptom_classifier, ehr_lookup, rag_retriever, triage_scorer})
        self.triage_toolset = ToolSet()
        self.triage_toolset.add(triage_functions)
        self.triage_client.enable_auto_function_calls(self.triage_toolset)
        self.triage_agent = self.triage_client.create_agent(
            model=MODEL_DEPLOYMENT,
            name="MediAssist-Triage-Agent",
            instructions=TRIAGE_SYSTEM_PROMPT,
            toolset=self.triage_toolset,
        )
        logger.info(f"[TRIAGE] Agent created: {self.triage_agent.id}")

        # --- Create DISCHARGE agent with its own client ---
        self.discharge_client = _create_client()
        discharge_functions = FunctionTool({ehr_lookup, rag_retriever})
        self.discharge_toolset = ToolSet()
        self.discharge_toolset.add(discharge_functions)
        self.discharge_client.enable_auto_function_calls(self.discharge_toolset)
        self.discharge_agent = self.discharge_client.create_agent(
            model=MODEL_DEPLOYMENT,
            name="MediAssist-Discharge-Agent",
            instructions=DISCHARGE_SYSTEM_PROMPT,
            toolset=self.discharge_toolset,
        )
        logger.info(f"[DISCHARGE] Agent created: {self.discharge_agent.id}")

        # --- Create PATIENT agent with its own client ---
        self.patient_client = _create_client()
        patient_functions = FunctionTool({rag_retriever})
        self.patient_toolset = ToolSet()
        self.patient_toolset.add(patient_functions)
        self.patient_client.enable_auto_function_calls(self.patient_toolset)
        self.patient_agent = self.patient_client.create_agent(
            model=MODEL_DEPLOYMENT,
            name="MediAssist-Patient-Agent",
            instructions=PATIENT_SYSTEM_PROMPT,
            toolset=self.patient_toolset,
        )
        logger.info(f"[PATIENT] Agent created: {self.patient_agent.id}")

        # --- Create ORCHESTRATOR with its own client ---
        self._build_orchestrator()

        logger.info("All agents initialised successfully")

    def _run_triage(self, patient_message: str) -> str:
        """Run the triage sub-agent with its own client and toolset."""
        logger.info("[ORCHESTRATOR] -> Invoking Triage Agent")
        run = self.triage_client.create_thread_and_process_run(
            agent_id=self.triage_agent.id,
            toolset=self.triage_toolset,
            thread={"messages": [{"role": "user", "content": f"Triage this patient:\n\n{patient_message}"}]},
        )
        if run.status == "failed":
            logger.error(f"[TRIAGE] Run failed: {run.last_error}")
            return json.dumps({"error": "Triage agent failed", "detail": str(run.last_error), "escalation_needed": True})
        response = _extract_text(self.triage_client.messages.get_last_message_text_by_role(thread_id=run.thread_id, role="assistant"))
        return response or json.dumps({"error": "No response from triage agent"})

    def _run_discharge(self, clinical_info: str) -> str:
        """Run the discharge sub-agent with its own client and toolset."""
        logger.info("[ORCHESTRATOR] -> Invoking Discharge Agent")
        run = self.discharge_client.create_thread_and_process_run(
            agent_id=self.discharge_agent.id,
            toolset=self.discharge_toolset,
            thread={"messages": [{"role": "user", "content": f"Generate discharge documentation:\n\n{clinical_info}"}]},
        )
        if run.status == "failed":
            logger.error(f"[DISCHARGE] Run failed: {run.last_error}")
            return json.dumps({"error": "Discharge agent failed", "detail": str(run.last_error)})
        response = _extract_text(self.discharge_client.messages.get_last_message_text_by_role(thread_id=run.thread_id, role="assistant"))
        return response or json.dumps({"error": "No response from discharge agent"})

    def _run_patient(self, clinical_text: str) -> str:
        """Run the patient explanation sub-agent with its own client and toolset."""
        logger.info("[ORCHESTRATOR] -> Invoking Patient Agent")
        run = self.patient_client.create_thread_and_process_run(
            agent_id=self.patient_agent.id,
            toolset=self.patient_toolset,
            thread={"messages": [{"role": "user", "content": f"Translate to plain English for the patient:\n\n{clinical_text}"}]},
        )
        if run.status == "failed":
            logger.error(f"[PATIENT] Run failed: {run.last_error}")
            return json.dumps({"error": "Patient agent failed", "detail": str(run.last_error)})
        response = _extract_text(self.patient_client.messages.get_last_message_text_by_role(thread_id=run.thread_id, role="assistant"))
        return response or json.dumps({"error": "No response from patient agent"})

    def _build_orchestrator(self):
        """Create the orchestrator agent with sub-agent wrappers as tools."""

        # Wrapper functions that the orchestrator calls as tools
        def run_triage_agent(patient_message: str) -> str:
            """
            Runs the triage sub-agent to classify symptoms, retrieve NICE guidelines,
            check patient EHR history, and assign an MTS triage priority level.

            :param patient_message: Full patient details including symptoms, vitals, age, sex,
                arrival mode, and NHS number if available.
            :return: JSON string with MTS triage level, clinical reasoning, and recommended actions.
            """
            return self._run_triage(patient_message)

        def run_discharge_agent(clinical_info: str) -> str:
            """
            Runs the discharge sub-agent to generate a structured discharge summary
            or GP referral letter based on clinical findings and EHR data.

            :param clinical_info: Clinical findings, diagnosis, treatment given,
                discharge decision, and NHS number.
            :return: JSON string with structured discharge summary.
            """
            return self._run_discharge(clinical_info)

        def run_patient_agent(clinical_text: str) -> str:
            """
            Runs the patient explanation sub-agent to translate clinical text
            into plain English that a patient can understand.

            :param clinical_text: The clinical discharge summary or triage note to translate.
            :return: Plain English patient summary with medication instructions and warning signs.
            """
            return self._run_patient(clinical_text)

        self.orchestrator_client = _create_client()
        orch_functions = FunctionTool({run_triage_agent, run_discharge_agent, run_patient_agent})
        self.orchestrator_toolset = ToolSet()
        self.orchestrator_toolset.add(orch_functions)
        self.orchestrator_client.enable_auto_function_calls(self.orchestrator_toolset)

        self.orchestrator_agent = self.orchestrator_client.create_agent(
            model=MODEL_DEPLOYMENT,
            name="MediAssist-Orchestrator",
            instructions=ORCHESTRATOR_SYSTEM_PROMPT,
            toolset=self.orchestrator_toolset,
        )
        logger.info(f"[ORCHESTRATOR] Agent created: {self.orchestrator_agent.id}")

    def process(self, message: str, nhs_number: str = "") -> dict:
        """
        Process a request through the orchestrator.
        The orchestrator reasons about what to do, calls sub-agents,
        evaluates results, and returns the final response.
        All outputs are PHI-scrubbed before returning.
        """
        full_message = message
        if nhs_number:
            full_message = f"NHS number: {nhs_number}\n\n{message}"

        logger.info(f"[ORCHESTRATOR] Processing request (NHS: {nhs_number or 'none'})")

        run = self.orchestrator_client.create_thread_and_process_run(
            agent_id=self.orchestrator_agent.id,
            toolset=self.orchestrator_toolset,
            thread={"messages": [{"role": "user", "content": full_message}]},
        )

        if run.status == "failed":
            logger.error(f"[ORCHESTRATOR] Run failed: {run.last_error}")
            return {
                "agent": "orchestrator",
                "status": "error",
                "response": "MediAssist encountered an error. Please proceed with manual clinical assessment.",
                "phi_entities_removed": 0,
            }

        raw_response = _extract_text(self.orchestrator_client.messages.get_last_message_text_by_role(
            thread_id=run.thread_id, role="assistant"
        ))
        if not raw_response:
            raw_response = "No response generated."

        # PHI scrub
        phi_result = scrub_phi(raw_response)

        return {
            "agent": "orchestrator",
            "status": "success",
            "response": phi_result["scrubbed_text"],
            "phi_entities_removed": phi_result["phi_count"],
        }

    def cleanup(self):
        """Delete all agents when shutting down."""
        for client, agent, name in [
            (self.triage_client, self.triage_agent, "triage"),
            (self.discharge_client, self.discharge_agent, "discharge"),
            (self.patient_client, self.patient_agent, "patient"),
            (self.orchestrator_client, self.orchestrator_agent, "orchestrator"),
        ]:
            try:
                client.delete_agent(agent.id)
                logger.info(f"Deleted {name} agent: {agent.id}")
            except Exception as e:
                logger.warning(f"Failed to delete {name} agent: {e}")