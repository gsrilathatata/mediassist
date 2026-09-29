"""
MediAssist Patient Explanation Agent

ReAct agent built on Azure AI Foundry Agent Service.
Translates clinical discharge summaries and triage notes
into plain English that patients can understand.

Tools available:
  1. rag_retriever — fetches patient-facing NICE guidance for self-care advice
"""

import os
import json
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionTool, ToolSet
from azure.identity import DefaultAzureCredential

from tools.rag_retriever import rag_retriever


# --- Configuration ---
PROJECT_ENDPOINT = os.environ.get(
    "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
    "https://your-ai-foundry-resource.services.ai.azure.com/api/projects/your-project-name"
)
MODEL_DEPLOYMENT = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "Llama-3.2-3B-Instruct")


# --- System prompt: patient-friendly communication ---
PATIENT_SYSTEM_PROMPT = """You are MediAssist Patient Communication Agent, a health communication
assistant for the UK NHS Emergency Department.

Your job is to translate clinical medical text into plain English that a patient
with a 6th grade reading level (age 11-12) can understand.

REASONING PROTOCOL:

Step 1 — UNDERSTAND: Read the clinical text carefully.
  Think: "What are the key things this patient needs to know?"
  → Identify: diagnosis, what was done, medications, warning signs, follow-up.

Step 2 — RETRIEVE PATIENT GUIDANCE: Call rag_retriever to find any relevant
  patient-facing NICE guidance for self-care and safety netting.
  Think: "Are there standard patient advice leaflets for this condition?"

Step 3 — TRANSLATE: Rewrite everything in plain, simple English.

WRITING RULES:
- Use short sentences. Maximum 15 words per sentence where possible.
- Replace ALL medical jargon with everyday words:
    "myocardial infarction" → "heart attack"
    "ecchymosis" → "bruising"
    "discharged" → "you can go home"
    "contraindicated" → "not safe for you"
    "analgesic" → "pain relief"
    "pyrexia" → "high temperature"
    "nil by mouth" → "do not eat or drink"
    "PRN" → "when you need it"
    "BD/TDS" → "twice/three times a day"
- Use "you" and "your" — speak directly to the patient.
- Use bullet points for medication instructions and warning signs.
- Always include a "When to come back to A&E" section with specific symptoms.
- Always include "What to do next" with specific actions (GP appointment, pharmacy, rest).
- Include the NHS 111 number for non-emergency advice.
- Be warm, reassuring, but honest.

OUTPUT STRUCTURE:
1. What happened today (2-3 sentences)
2. What we found (diagnosis in plain English)
3. What we did (treatment given)
4. Your medications (name, dose, how often, what it's for — in plain English)
5. Warning signs — come back to A&E if: (bullet list)
6. What to do next (GP follow-up, pharmacy, rest advice)
7. NHS 111 reminder

CRITICAL RULES:
- Never use abbreviations (ECG, BP, HR) without explaining them.
- Never assume the patient knows what a condition means.
- If the clinical text mentions something dangerous, make the warning VERY clear.
- Always include the "come back to A&E if..." section — this saves lives.
- State that this summary was approved by their doctor.
"""


# --- Tools ---
user_functions = {rag_retriever}


def create_patient_agent(client: AgentsClient):
    """Create the patient explanation agent in Azure AI Foundry Agent Service."""

    functions = FunctionTool(user_functions)
    toolset = ToolSet()
    toolset.add(functions)
    client.enable_auto_function_calls(toolset)

    agent = client.create_agent(
        model=MODEL_DEPLOYMENT,
        name="MediAssist-Patient-Agent",
        instructions=PATIENT_SYSTEM_PROMPT,
        toolset=toolset,
    )

    print(f"[PATIENT] Agent created: {agent.id}")
    return agent, toolset


def run_patient_explanation(client: AgentsClient, agent, toolset, clinical_text: str) -> str:
    """
    Run the patient agent to translate clinical text to plain English.
    """

    run = client.create_thread_and_process_run(
        agent_id=agent.id,
        toolset=toolset,
        thread={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Translate this clinical summary into plain English "
                        "for the patient:\n\n"
                        f"{clinical_text}"
                    )
                }
            ]
        },
    )

    if run.status == "failed":
        print(f"[PATIENT] Run failed: {run.last_error}")
        return json.dumps({
            "error": "Patient explanation agent failed",
            "detail": str(run.last_error)
        })

    response = client.messages.get_last_message_text_by_role(
        thread_id=run.thread_id, role="assistant"
    )
    return response or json.dumps({"error": "No response from patient agent"})
