"""
MediAssist Triage Agent

ReAct agent built on Azure AI Foundry Agent Service.
Uses autonomous tool calling to classify symptoms, retrieve EHR,
pull NICE guidelines via RAG, and generate triage notes.

Tools available:
  1. symptom_classifier  — maps symptoms to clinical category
  2. ehr_lookup          — retrieves patient history from FHIR
  3. rag_retriever       — fetches NICE guidelines from Azure AI Search
  4. triage_scorer       — assigns MTS/CTAS priority level
"""

import os
import json
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionTool, ToolSet
from azure.identity import DefaultAzureCredential

from tools.symptom_classifier import symptom_classifier
from tools.ehr_lookup import ehr_lookup
from tools.rag_retriever import rag_retriever
from tools.triage_scorer import triage_scorer


# --- Configuration ---
PROJECT_ENDPOINT = os.environ.get(
    "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
    "https://your-ai-foundry-resource.services.ai.azure.com/api/projects/your-project-name"
)
MODEL_DEPLOYMENT = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "Llama-3.2-3B-Instruct")


# --- System prompt: ReAct reasoning for triage ---
TRIAGE_SYSTEM_PROMPT = """You are MediAssist Triage Agent, a clinical decision support assistant
for Emergency Department triage nurses in the UK NHS.

You follow the ReAct pattern strictly: Think → Act → Observe → Think → Act → ... → Final Answer.

REASONING PROTOCOL:
For every patient, you MUST reason through these steps. Do NOT skip steps.

Step 1 — CLASSIFY: Call symptom_classifier with the raw symptoms.
  Think: "What clinical category does this presentation fall into?"
  → Observe the category and confidence score.
  → If confidence < 0.5 or category is "unclassified", state uncertainty explicitly.

Step 2 — RETRIEVE GUIDELINES: Call rag_retriever with the clinical category and key symptoms.
  Think: "What do NICE guidelines say about this presentation?"
  → Observe the guideline actions and red flags.

Step 3 — CHECK HISTORY: If an NHS number is provided, call ehr_lookup.
  Think: "Does the patient history change my clinical reasoning?"
  → Observe conditions, allergies, medications.
  → Flag any drug interactions or contraindications.

Step 4 — SCORE TRIAGE: Call triage_scorer with symptoms, vitals, and category.
  Think: "Does the MTS level match my clinical judgement from steps 1-3?"
  → If the score seems too low given red flags or history, EXPLAIN why you disagree.
  → If the score seems appropriate, confirm with reasoning.

Step 5 — SYNTHESISE: Produce the final triage note combining ALL gathered evidence.

CRITICAL RULES:
- You are clinical decision SUPPORT. Always state a qualified clinician must validate.
- Never fabricate clinical information. If uncertain, say so.
- Use UK clinical terminology (NHS, NICE, MTS).
- Flag ALL red-flag symptoms explicitly.
- If you find drug interactions between current medications and likely ED treatments, flag them.
- If the patient has allergies relevant to standard treatments, flag them.

OUTPUT FORMAT — always produce this JSON structure:
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
    "recommended_actions": ["evidence-based actions from NICE guidelines"],
    "red_flags": ["any red flag symptoms identified"],
    "confidence": 0.0-1.0,
    "escalation_needed": true/false,
    "escalation_reason": "why senior review is needed, if applicable"
}
IMPORTANT: Always include this exact line as the very last line of your response:
CTAS_SCORE: <number 1-5>
"""


# --- All 4 tools ---
user_functions = {symptom_classifier, ehr_lookup, rag_retriever, triage_scorer}


def create_triage_agent(client: AgentsClient):
    """Create the triage agent in Azure AI Foundry Agent Service."""

    functions = FunctionTool(user_functions)
    toolset = ToolSet()
    toolset.add(functions)
    client.enable_auto_function_calls(toolset)

    agent = client.create_agent(
        model=MODEL_DEPLOYMENT,
        name="MediAssist-Triage-Agent",
        instructions=TRIAGE_SYSTEM_PROMPT,
        toolset=toolset,
    )

    print(f"[TRIAGE] Agent created: {agent.id}")
    return agent, toolset


def run_triage(client: AgentsClient, agent, toolset, patient_input: str) -> str:
    """
    Run the triage agent with patient data.
    The agent autonomously decides which tools to call and in what order.
    Returns the agent's final triage note.
    """

    run = client.create_thread_and_process_run(
        agent_id=agent.id,
        toolset=toolset,
        thread={
            "messages": [
                {
                    "role": "user",
                    "content": f"Triage this patient:\n\n{patient_input}"
                }
            ]
        },
    )

    if run.status == "failed":
        print(f"[TRIAGE] Run failed: {run.last_error}")
        return json.dumps({
            "error": "Triage agent failed",
            "detail": str(run.last_error),
            "escalation_needed": True,
            "escalation_reason": "Agent execution failure — escalate to senior clinician"
        })

    response = client.messages.get_last_message_text_by_role(
        thread_id=run.thread_id, role="assistant"
    )
    return response or json.dumps({"error": "No response from triage agent"})
