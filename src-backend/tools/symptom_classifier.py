"""
MediAssist Tool 1: symptom_classifier

Maps raw patient symptom text to a clinical category and subcategory.
Used by the ReAct agent to determine which RAG guidelines to retrieve
and which clinical pathway to follow.
"""

import json


# Clinical category mappings based on Manchester Triage System discriminators
CLINICAL_CATEGORIES = {
    "cardiac": {
        "keywords": [
            "chest pain", "crushing", "radiating", "palpitations", "cardiac",
            "heart", "angina", "myocardial", "arrhythmia", "tachycardia",
            "bradycardia", "shortness of breath", "diaphoresis", "sweating",
            "left arm pain", "jaw pain", "syncope", "collapse"
        ],
        "subcategories": ["ACS", "arrhythmia", "heart failure", "chest pain NOS"]
    },
    "respiratory": {
        "keywords": [
            "breathing", "cough", "wheeze", "asthma", "pneumonia", "dyspnea",
            "respiratory", "oxygen", "spo2", "stridor", "bronchitis", "copd",
            "inhaler", "pleuritic", "hemoptysis", "lung","cold", "sneezing", "runny nose", "nasal", "congestion", "nose block", "flu", "sore throat", "throat pain", "blocked nose"
        ],
        "subcategories": ["asthma_exacerbation", "pneumonia", "COPD", "respiratory_distress"]
    },
    "neurological": {
        "keywords": [
            "headache", "seizure", "stroke", "weakness", "numbness", "confusion",
            "slurred speech", "facial droop", "vision loss", "dizziness",
            "vertigo", "unconscious", "unresponsive", "gcs", "meningitis",
            "tingling", "paralysis"
        ],
        "subcategories": ["stroke", "seizure", "meningitis", "head_injury"]
    },
    "trauma": {
        "keywords": [
            "fall", "fell", "accident", "injury", "fracture", "broken", "wound",
            "laceration", "bleeding", "burn", "crush injury", "collision", "assault",
            "sprain", "dislocation", "swollen", "deformity", "rta", "hit by",
            "twisted", "knocked"
        ],
        "subcategories": ["fracture", "laceration", "head_injury", "burns", "polytrauma"]
    },
    "abdominal": {
        "keywords": [
            "abdominal pain", "vomiting", "nausea", "diarrhoea", "constipation",
            "appendicitis", "bowel", "stomach", "gi bleed", "melena",
            "hematemesis", "bloating", "peritonitis", "obstruction", "hernia"
        ],
        "subcategories": ["appendicitis", "obstruction", "GI_bleed", "acute_abdomen"]
    },
    "mental_health": {
        "keywords": [
            "anxiety", "depression", "self harm", "suicidal", "overdose",
            "psychosis", "hallucination", "agitation", "panic", "mental health",
            "psychiatric", "deliberate", "ingestion", "tablets", "took",
            "end it", "kill myself", "harm", "cutting", "paracetamol"
        ],
        "subcategories": ["self_harm", "overdose", "psychosis", "crisis"]
    },
    "paediatric": {
        "keywords": [
            "child", "infant", "baby", "neonate", "fever child", "rash child",
            "crying", "not feeding", "fontanelle", "croup", "bronchiolitis"
        ],
        "subcategories": ["febrile_child", "respiratory_paediatric", "NAI_concern"]
    },
    "general_medicine": {
        "keywords": [
            "fever", "infection", "sepsis", "rash", "allergy", "anaphylaxis",
            "diabetic", "hyperglycemia", "hypoglycemia", "dehydration",
            "urinary", "uti", "renal", "kidney", "sore throat", "cellulitis"
        ],
        "subcategories": ["sepsis", "allergic_reaction", "diabetic_emergency", "infection"]
    }
}


def symptom_classifier(symptoms: str) -> str:
    """
    Classifies raw patient symptom text into a clinical category and subcategory.
    Used to determine which clinical pathway and guidelines to retrieve.

    :param symptoms: Raw text describing patient symptoms, e.g.
        "crushing chest pain radiating to left arm, sweating, nausea"
    :return: JSON string with category, subcategory, confidence, and matched keywords.
    """
    symptoms_lower = symptoms.lower()

    # Score each category by keyword matches
    scores = {}
    matched = {}
    for category, data in CLINICAL_CATEGORIES.items():
        matches = [kw for kw in data["keywords"] if kw in symptoms_lower]
        scores[category] = len(matches)
        matched[category] = matches

    if not any(scores.values()):
        return json.dumps({
            "category": "unclassified",
            "subcategory": "none",
            "confidence": 0.0,
            "matched_keywords": [],
            "recommendation": "Unable to classify. Escalate to senior clinician."
        })

    # Primary category = highest score
    primary = max(scores, key=scores.get)
    total_keywords = sum(scores.values())
    confidence = round(scores[primary] / max(total_keywords, 1), 2)

    # Pick most likely subcategory based on keyword overlap
    subcategories = CLINICAL_CATEGORIES[primary]["subcategories"]
    subcategory = subcategories[0]  # Default to first; in production, use NLP model

    # Check for secondary category (multi-system presentation)
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    secondary = None
    if len(sorted_scores) > 1 and sorted_scores[1][1] > 0:
        secondary = sorted_scores[1][0]

    result = {
        "category": primary,
        "subcategory": subcategory,
        "confidence": confidence,
        "matched_keywords": matched[primary],
        "secondary_category": secondary,
        "recommendation": f"Retrieve {primary} guidelines. "
                         f"{'Also consider ' + secondary + ' pathway.' if secondary else ''}"
    }

    return json.dumps(result)


# Quick test
if __name__ == "__main__":
    test_cases = [
        "crushing chest pain radiating to left arm, sweating, nausea, dizzy",
        "fell off bike, right wrist very swollen, can't move fingers",
        "bad abdominal pain lower right, vomiting, getting worse since last night",
        "sore throat for 3 days, difficulty swallowing",
        "patient took 20 paracetamol tablets, says wants to end it all",
    ]

    for symptoms in test_cases:
        result = json.loads(symptom_classifier(symptoms))
        print(f"\nSymptoms: {symptoms}")
        print(f"  Category: {result['category']}")
        print(f"  Subcategory: {result['subcategory']}")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Matched: {result['matched_keywords']}")
        print(f"  Secondary: {result.get('secondary_category')}")