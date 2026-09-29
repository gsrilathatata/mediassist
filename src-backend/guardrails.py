"""
MediAssist Guardrails

Uses Azure AI Content Safety for content moderation
plus custom clinical safety checks for healthcare-specific guardrails.
"""

import os
import re
import json
import logging

logger = logging.getLogger("mediassist.guardrails")

# --- Azure AI Content Safety ---
CONTENT_SAFETY_ENDPOINT = os.environ.get(
    "AZURE_CONTENT_SAFETY_ENDPOINT",
    "https://your-region.api.cognitive.microsoft.com/"
)
CONTENT_SAFETY_KEY = os.environ.get("AZURE_CONTENT_SAFETY_KEY", "")

try:
    from azure.ai.contentsafety import ContentSafetyClient
    from azure.ai.contentsafety.models import AnalyzeTextOptions
    from azure.core.credentials import AzureKeyCredential
    HAS_CONTENT_SAFETY = True
except ImportError:
    HAS_CONTENT_SAFETY = False
    logger.warning("azure-ai-contentsafety not installed — using fallback guardrails")


def _get_safety_client():
    if HAS_CONTENT_SAFETY and CONTENT_SAFETY_KEY:
        return ContentSafetyClient(
            endpoint=CONTENT_SAFETY_ENDPOINT,
            credential=AzureKeyCredential(CONTENT_SAFETY_KEY),
        )
    return None


# --- Clinical safety patterns (custom, not in Azure Content Safety) ---

INJECTION_PATTERNS = [
    r"\b(ignore|disregard|override|bypass)\b.*(instructions|rules|prompt|guidelines)",
    r"\b(you are now|from now on|new instructions|forget everything)\b",
    r"\bjailbreak\b",
    r"\b(admin|root|sudo)\s*(access|mode|override)\b",
    r"\b(system prompt|reveal your|show me your instructions)\b",
]

NON_CLINICAL_PATTERNS = [
    r"\b(write|compose|create)\b.*(poem|song|story|essay|joke|code)",
    r"\b(weather|stock|price|recipe|movie|game|sport)\b",
    r"\bhow to (hack|break|steal|cheat)\b",
]

HIGH_RISK_KEYWORDS = [
    "suicidal", "suicide", "kill myself", "end it all", "self harm",
    "self-harm", "overdose", "took tablets", "want to die",
    "child abuse", "NAI", "non-accidental injury", "safeguarding",
]

RED_FLAG_SYMPTOMS = [
    "chest pain", "cardiac arrest", "unresponsive",
    "stroke", "facial droop", "slurred speech",
    "anaphylaxis", "not breathing",
    "severe bleeding", "haemorrhage",
    "meningitis", "neck stiffness",
    "seizure", "unconscious",
    "worst headache", "thunderclap",
    "sepsis",
]


# --- INPUT GUARDRAILS ---

def validate_input(message: str) -> dict:
    """
    Validate input using Azure AI Content Safety + custom clinical checks.
    Returns: {"valid": bool, "reason": str, "flags": list}
    """
    if not message or not message.strip():
        return {"valid": False, "reason": "Empty message", "flags": []}

    if len(message.strip()) < 10:
        return {"valid": False, "reason": "Message too short — please provide more clinical detail", "flags": []}

    if len(message) > 5000:
        return {"valid": False, "reason": "Message too long — please summarise", "flags": []}

    msg_lower = message.lower()
    flags = []

    # 1. Check prompt injection (custom — Content Safety doesn't cover this)
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, msg_lower):
            logger.warning(f"Prompt injection blocked")
            return {"valid": False, "reason": "Invalid request detected", "flags": ["injection_blocked"]}

    # 2. Azure AI Content Safety — check harmful content + custom blocklist (non-clinical terms)
    client = _get_safety_client()
    if client:
        try:
            request = AnalyzeTextOptions(
                text=message[:1000],
                blocklist_names=["non-clinical"],
                halt_on_blocklist_hit=True,
            )
            response = client.analyze_text(request)

            # Check blocklist hits
            if response.blocklists_match:
                blocked_terms = [m.blocklist_item_text for m in response.blocklists_match]
                logger.warning(f"Blocklist hit: {blocked_terms}")
                return {"valid": False, "reason": "MediAssist is a clinical decision support system. Please describe patient symptoms, vitals, or clinical findings.", "flags": ["blocklist_hit"]}

            for category_result in response.categories_analysis:
                if category_result.severity and category_result.severity >= 4:
                    logger.warning(f"Content Safety flagged: {category_result.category} severity={category_result.severity}")
                    flags.append(f"content_safety:{category_result.category}")

            logger.info(f"Content Safety check passed (flags: {len(flags)})")
        except Exception as e:
            logger.warning(f"Content Safety check failed: {e}")
    else:
        flags.append("content_safety:unavailable")

    # 4. Flag high-risk presentations (valid but flagged for escalation)
    for keyword in HIGH_RISK_KEYWORDS:
        if keyword in msg_lower:
            flags.append(f"high_risk:{keyword}")

    # 5. Flag red-flag symptoms
    for symptom in RED_FLAG_SYMPTOMS:
        if symptom in msg_lower:
            flags.append(f"red_flag:{symptom}")

    return {"valid": True, "reason": "", "flags": flags}


# --- OUTPUT GUARDRAILS ---

def validate_output(response: str, input_flags: list = None) -> dict:
    """
    Validate agent output using Azure AI Content Safety + clinical safety checks.
    Returns: {"safe": bool, "modified_response": str, "warnings": list}
    """
    warnings = []
    modified = response

    # 1. Azure AI Content Safety on output
    client = _get_safety_client()
    if client:
        try:
            request = AnalyzeTextOptions(text=response[:1000])
            result = client.analyze_text(request)

            for category_result in result.categories_analysis:
                if category_result.severity and category_result.severity >= 6:
                    warnings.append(f"output_safety:{category_result.category}")
                    logger.warning(f"Output flagged by Content Safety: {category_result.category}")
        except Exception as e:
            logger.warning(f"Output Content Safety check failed: {e}")

    # 2. High-risk escalation notice
    if input_flags:
        high_risk = [f for f in input_flags if f.startswith("high_risk:")]
        if high_risk:
            escalation = "\n\n⚠️ HIGH RISK PRESENTATION — Immediate senior clinician review required. Do not delay assessment."
            if "HIGH RISK" not in modified:
                modified = modified + escalation
                warnings.append("high_risk_escalation_added")

        red_flags = [f for f in input_flags if f.startswith("red_flag:")]
        if red_flags:
            flag_names = [f.split(":")[1] for f in red_flags]
            flag_notice = f"\n\n🔴 Red flags: {', '.join(flag_names)}. Ensure immediate clinical assessment."
            if "red flag" not in modified.lower() and "Red flag" not in modified:
                modified = modified + flag_notice
                warnings.append("red_flag_notice_added")

    # 3. Ensure clinician validation disclaimer
    if "clinician" not in modified.lower():
        modified = modified + "\n\nAI-generated clinical decision support. Must be validated by a qualified clinician."
        warnings.append("disclaimer_added")

    return {"safe": True, "modified_response": modified, "warnings": warnings}