"""
MediAssist Discharge Agent

ReAct agent built on Azure AI Foundry Agent Service.
Generates structured discharge summaries and GP referral letters
grounded in clinical findings, EHR data, and NICE guidelines.

Tools available:
  1. ehr_lookup      — retrieves patient history from FHIR
  2. rag_retriever   — fetches relevant NICE guidelines
"""

import os
import json
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionTool, ToolSet
from azure.identity import DefaultAzureCredential

from tools.ehr_lookup import ehr_lookup
from tools.rag_retriever import rag_retriever


# --- Configuration ---
PROJECT_ENDPOINT = os.environ.get(
    "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
    "https://your-ai-foundry-resource.services.ai.azure.com/api/projects/your-project-name"
)
MODEL_DEPLOYMENT = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "Llama-3.2-3B-Instruct")


# --- System prompt: ReAct reasoning for discharge ---
DISCHARGE_SYSTEM_PROMPT = """You are MediAssist Discharge Agent, a clinical documentation assistant
for Emergency Department clinicians in the UK NHS.

You follow the ReAct pattern: Think → Act → Observe → Think → ... → Final Answer.

REASONING PROTOCOL:

Step 1 — RETRIEVE HISTORY: Call ehr_lookup with the patient's NHS number.
  Think: "What is the patient's baseline — conditions, medications, allergies?"
  → This informs what is NEW from this ED visit vs pre-existing.

Step 2 — RETRIEVE GUIDELINES: Call rag_retriever with the clinical category and diagnosis.
  Think: "What does NICE recommend for follow-up, safety netting, and GP actions?"
  → Use this to generate evidence-based discharge advice.

Step 3 — GENERATE DOCUMENT: Based on the clinician's findings + EHR + guidelines, produce
  the discharge summary OR GP referral letter.

For DISCHARGE SUMMARY, use this structure:
{
    "document_type": "discharge_summary",
    "patient_name": "from EHR",
    "nhs_number": "from input",
    "date_of_attendance": "today's date",
    "presenting_complaint": "from triage/clinician input",
    "investigations_performed": "list of tests and results",
    "diagnosis": "final ED diagnosis",
    "treatment_given": "medications/procedures in ED",
    "discharge_medications": "new prescriptions with doses and duration",
    "medication_changes": "any changes to regular medications",
    "follow_up_required": "GP/outpatient/specialist follow-up",
    "safety_netting_advice": "when to return to ED — from NICE guidelines",
    "gp_actions_required": "specific tasks for GP",
    "nice_guidelines_referenced": ["guideline codes"],
    "clinician_name": "from input",
    "clinician_grade": "from input"
}

For GP REFERRAL LETTER, use formal NHS letter format with:
- Structured header (patient details, NHS number, GP practice)
- Reason for referral
- Clinical findings and investigations
- Current medications (from EHR)
- Specific request to GP (follow-up bloods, review appointment, specialist referral)
- Safety netting advice given to patient

CRITICAL RULES:
- Base everything on evidence from the clinician's input and NICE guidelines.
- Never fabricate investigation results or clinical findings.
- Always include medication reconciliation — compare EHR meds with discharge meds.
- Flag any allergy conflicts between EHR allergies and prescribed treatments.
- Include specific NICE guideline references for follow-up recommendations.
- Do NOT include red flags from RAG guidelines that are unrelated to the patient's actual presenting complaint. Only include safety netting advice relevant to their diagnosis.
- State that this document must be reviewed and signed by the responsible clinician.
"""


# --- Tools ---
user_functions = {ehr_lookup, rag_retriever}


def create_discharge_agent(client: AgentsClient):
    """Create the discharge agent in Azure AI Foundry Agent Service."""

    functions = FunctionTool(user_functions)
    toolset = ToolSet()
    toolset.add(functions)
    client.enable_auto_function_calls(toolset)

    agent = client.create_agent(
        model=MODEL_DEPLOYMENT,
        name="MediAssist-Discharge-Agent",
        instructions=DISCHARGE_SYSTEM_PROMPT,
        toolset=toolset,
    )

    print(f"[DISCHARGE] Agent created: {agent.id}")
    return agent, toolset


def run_discharge(client: AgentsClient, agent, toolset, clinical_input: str) -> str:
    """
    Run the discharge agent with clinical findings.
    The agent retrieves EHR and guidelines autonomously,
    then generates the discharge document.
    """

    run = client.create_thread_and_process_run(
        agent_id=agent.id,
        toolset=toolset,
        thread={
            "messages": [
                {
                    "role": "user",
                    "content": f"Generate discharge documentation:\n\n{clinical_input}"
                }
            ]
        },
    )

    if run.status == "failed":
        print(f"[DISCHARGE] Run failed: {run.last_error}")
        return json.dumps({
            "error": "Discharge agent failed",
            "detail": str(run.last_error)
        })

    response = client.messages.get_last_message_text_by_role(
        thread_id=run.thread_id, role="assistant"
    )
    return response or json.dumps({"error": "No response from discharge agent"})
