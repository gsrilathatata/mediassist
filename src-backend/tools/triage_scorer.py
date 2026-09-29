"""
MediAssist Tool 3: triage_scorer

Assigns a triage priority level based on symptoms, vitals, and clinical category.
Supports both CTAS (Canadian Triage and Acuity Scale) and MTS (Manchester Triage System).

CTAS Levels:
  I   = Resuscitation (immediate)
  II  = Emergent (within 15 min)
  III = Urgent (within 30 min)
  IV  = Less urgent (within 60 min)
  V   = Non-urgent (within 120 min)

MTS Levels:
  1 = Red (immediate)
  2 = Orange (within 10 min)
  3 = Yellow (within 60 min)
  4 = Green (within 120 min)
  5 = Blue (within 240 min)
"""

import json
import re


# --- CTAS discriminators ---
CTAS_LEVEL_I = [
    "cardiac arrest", "respiratory arrest", "unresponsive", "airway compromise",
    "inadequate breathing", "shock", "severe haemorrhage", "major trauma",
    "unconscious", "gcs below 9", "anaphylaxis", "active seizure"
]

CTAS_LEVEL_II = [
    "chest pain", "cardiac pain", "acute neurological deficit", "stroke signs",
    "severe pain", "pain score 8", "pain score 9", "pain score 10",
    "acute shortness of breath", "overdose", "self harm", "sepsis",
    "high risk history", "hemodynamic compromise", "altered mental status",
    "meningism", "acute psychosis"
]

CTAS_LEVEL_III = [
    "moderate pain", "pain score 5", "pain score 6", "pain score 7",
    "persistent vomiting", "acute onset", "fever above 38.5", "hot child",
    "deformity", "unable to weight bear", "abdominal pain",
    "headache with vomiting", "pleuritic pain", "asthma exacerbation"
]

CTAS_LEVEL_IV = [
    "mild pain", "pain score 3", "pain score 4", "minor wound",
    "sore throat", "urinary symptoms", "mild fever", "earache",
    "minor allergic reaction", "chronic complaint worsening"
]

# --- MTS discriminators ---
MTS_RED = CTAS_LEVEL_I
MTS_ORANGE = CTAS_LEVEL_II
MTS_YELLOW = CTAS_LEVEL_III
MTS_GREEN = CTAS_LEVEL_IV


# --- CTAS output labels ---
CTAS_LABELS = {
    1: {"level": "I", "name": "Resuscitation", "time": "immediate"},
    2: {"level": "II", "name": "Emergent", "time": "15 minutes"},
    3: {"level": "III", "name": "Urgent", "time": "30 minutes"},
    4: {"level": "IV", "name": "Less urgent", "time": "60 minutes"},
    5: {"level": "V", "name": "Non-urgent", "time": "120 minutes"},
}

# --- MTS output labels ---
MTS_LABELS = {
    1: {"level": "1", "name": "Red", "time": "immediate"},
    2: {"level": "2", "name": "Orange", "time": "10 minutes"},
    3: {"level": "3", "name": "Yellow", "time": "60 minutes"},
    4: {"level": "4", "name": "Green", "time": "120 minutes"},
    5: {"level": "5", "name": "Blue", "time": "240 minutes"},
}


def _check_critical_vitals(text: str) -> dict:
    """Parse vitals and check for critical/warning thresholds."""
    result = {"critical": False, "warning": False, "details": []}

    hr_match = re.search(r'hr\s*(\d+)', text)
    if hr_match:
        hr = int(hr_match.group(1))
        if hr > 130 or hr < 40:
            result["critical"] = True
            result["details"].append(f"Critical HR: {hr}")
        elif hr > 110 or hr < 50:
            result["warning"] = True
            result["details"].append(f"Abnormal HR: {hr}")

    spo2_match = re.search(r'spo2\s*(\d+)', text)
    if spo2_match:
        spo2 = int(spo2_match.group(1))
        if spo2 < 92:
            result["critical"] = True
            result["details"].append(f"Critical SpO2: {spo2}%")
        elif spo2 < 95:
            result["warning"] = True
            result["details"].append(f"Low SpO2: {spo2}%")

    rr_match = re.search(r'rr\s*(\d+)', text)
    if rr_match:
        rr = int(rr_match.group(1))
        if rr > 30 or rr < 8:
            result["critical"] = True
            result["details"].append(f"Critical RR: {rr}")
        elif rr > 24:
            result["warning"] = True
            result["details"].append(f"Elevated RR: {rr}")

    bp_match = re.search(r'bp\s*(\d+)/(\d+)', text)
    if bp_match:
        sys_bp = int(bp_match.group(1))
        if sys_bp < 90:
            result["critical"] = True
            result["details"].append(f"Hypotension: SBP {sys_bp}")
        elif sys_bp > 180:
            result["warning"] = True
            result["details"].append(f"Severe hypertension: SBP {sys_bp}")

    return result


def triage_scorer(symptoms: str, vitals: str, clinical_category: str, triage_standard: str = "CTAS") -> str:
    """
    Assigns a triage priority level based on patient symptoms, vital signs,
    and clinical category. Supports CTAS and MTS scoring standards.

    :param symptoms: Description of patient symptoms and pain score,
        e.g. 'crushing chest pain, pain score 8/10, diaphoresis'
    :param vitals: Patient vital signs,
        e.g. 'HR 112, BP 165/95, SpO2 96%, RR 22'
    :param clinical_category: The clinical category from symptom classification,
        e.g. 'cardiac'
    :param triage_standard: Triage standard to use, either 'CTAS' or 'MTS'. Defaults to 'CTAS'.
    :return: JSON string with triage level, category name, discriminator, time target, and rationale.
    """
    combined = f"{symptoms} {vitals} {clinical_category}".lower()
    standard = triage_standard.upper()

    if standard == "MTS":
        labels = MTS_LABELS
        level_1_disc = MTS_RED
        level_2_disc = MTS_ORANGE
        level_3_disc = MTS_YELLOW
        level_4_disc = MTS_GREEN
    else:
        labels = CTAS_LABELS
        level_1_disc = CTAS_LEVEL_I
        level_2_disc = CTAS_LEVEL_II
        level_3_disc = CTAS_LEVEL_III
        level_4_disc = CTAS_LEVEL_IV

    # Check vitals first
    vital_check = _check_critical_vitals(combined)

    if vital_check["critical"]:
        info = labels[1]
        return json.dumps({
            "triage_level": info["level"],
            "triage_category": info["name"],
            "triage_standard": standard,
            "discriminator": "Critical vital signs",
            "time_to_assessment": info["time"],
            "vital_flags": vital_check["details"],
            "rationale": "Vital signs indicate life-threatening compromise"
        })

    # Check discriminators from most urgent to least
    for disc in level_1_disc:
        if disc in combined:
            info = labels[1]
            return json.dumps({
                "triage_level": info["level"],
                "triage_category": info["name"],
                "triage_standard": standard,
                "discriminator": disc,
                "time_to_assessment": info["time"],
                "vital_flags": vital_check["details"],
                "rationale": f"Level 1 discriminator matched: {disc}"
            })

    for disc in level_2_disc:
        if disc in combined:
            info = labels[2]
            # Upgrade if warning vitals present
            if vital_check["warning"]:
                info = labels[1]
                return json.dumps({
                    "triage_level": info["level"],
                    "triage_category": info["name"],
                    "triage_standard": standard,
                    "discriminator": f"{disc} + abnormal vitals",
                    "time_to_assessment": info["time"],
                    "vital_flags": vital_check["details"],
                    "rationale": f"Level 2 discriminator with abnormal vitals upgraded to Level 1"
                })
            return json.dumps({
                "triage_level": info["level"],
                "triage_category": info["name"],
                "triage_standard": standard,
                "discriminator": disc,
                "time_to_assessment": info["time"],
                "vital_flags": vital_check["details"],
                "rationale": f"Level 2 discriminator matched: {disc}"
            })

    for disc in level_3_disc:
        if disc in combined:
            info = labels[3]
            return json.dumps({
                "triage_level": info["level"],
                "triage_category": info["name"],
                "triage_standard": standard,
                "discriminator": disc,
                "time_to_assessment": info["time"],
                "vital_flags": vital_check["details"],
                "rationale": f"Level 3 discriminator matched: {disc}"
            })

    for disc in level_4_disc:
        if disc in combined:
            info = labels[4]
            return json.dumps({
                "triage_level": info["level"],
                "triage_category": info["name"],
                "triage_standard": standard,
                "discriminator": disc,
                "time_to_assessment": info["time"],
                "vital_flags": vital_check["details"],
                "rationale": f"Level 4 discriminator matched: {disc}"
            })

    # Default: Level 5 (non-urgent)
    info = labels[5]
    return json.dumps({
        "triage_level": info["level"],
        "triage_category": info["name"],
        "triage_standard": standard,
        "discriminator": "No urgent discriminator identified",
        "time_to_assessment": info["time"],
        "vital_flags": vital_check["details"],
        "rationale": "No high-priority discriminators matched"
    })


# Quick test
if __name__ == "__main__":
    test_cases = [
        {
            "symptoms": "crushing chest pain, pain score 8/10, diaphoresis, nausea",
            "vitals": "HR 112, BP 165/95, SpO2 96%, RR 22",
            "category": "cardiac"
        },
        {
            "symptoms": "fell off bike, right wrist swollen, pain score 5/10",
            "vitals": "HR 88, BP 130/80, SpO2 99%, RR 16",
            "category": "trauma"
        },
        {
            "symptoms": "sore throat for 3 days, difficulty swallowing",
            "vitals": "HR 76, BP 120/75, SpO2 99%, RR 14",
            "category": "general_medicine"
        },
    ]

    for tc in test_cases:
        print(f"\nSymptoms: {tc['symptoms']}")

        # Test CTAS
        result = json.loads(triage_scorer(tc["symptoms"], tc["vitals"], tc["category"], "CTAS"))
        print(f"  CTAS: Level {result['triage_level']} ({result['triage_category']}) - {result['time_to_assessment']}")
        print(f"  Discriminator: {result['discriminator']}")

        # Test MTS
        result = json.loads(triage_scorer(tc["symptoms"], tc["vitals"], tc["category"], "MTS"))
        print(f"  MTS:  Level {result['triage_level']} ({result['triage_category']}) - {result['time_to_assessment']}")