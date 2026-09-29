"""
MediAssist Tool 4: rag_retriever

Retrieves relevant NICE guidelines and OpenFDA references from
Azure AI Search based on clinical category and symptoms.
Used by the agent to ground clinical decisions in evidence-based guidelines.
"""

import os
import json
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential


SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "https://your-search-service.search.windows.net")
SEARCH_API_KEY = os.environ.get("AZURE_SEARCH_API_KEY", " ")
INDEX_NAME = "nice-guidelines"


def rag_retriever(clinical_category: str, symptoms: str) -> str:
    """
    Retrieves relevant NICE clinical guidelines from Azure AI Search
    based on the clinical category and patient symptoms.
    Returns guideline summaries, key actions, and red flags to ground
    the triage decision in evidence-based references.

    :param clinical_category: The clinical category from symptom classification,
        e.g. 'cardiac', 'respiratory', 'trauma', 'neurological', 'mental_health'
    :param symptoms: Key symptoms to search for relevant guidelines,
        e.g. 'chest pain radiating to left arm'
    :return: JSON string with matching guidelines including title, summary, key actions, and red flags.
    """
    try:
        client = SearchClient(
            endpoint=SEARCH_ENDPOINT,
            index_name=INDEX_NAME,
            credential=AzureKeyCredential(SEARCH_API_KEY),
        )

        # Search combining category filter with symptom text
        search_text = f"{clinical_category} {symptoms}"
        results = client.search(
            search_text=search_text,
            filter=f"clinical_category eq '{clinical_category}'",
            top=3,
        )

        guidelines = []
        for r in results:
            guidelines.append({
                "guideline_code": r["guideline_code"],
                "title": r["title"],
                "summary": r["summary"],
                "key_actions": r["key_actions"],
                "red_flags": r["red_flags"],
            })

        # If no category-specific results, try broader search
        if not guidelines:
            results = client.search(search_text=search_text, top=3)
            for r in results:
                guidelines.append({
                    "guideline_code": r["guideline_code"],
                    "title": r["title"],
                    "summary": r["summary"],
                    "key_actions": r["key_actions"],
                    "red_flags": r["red_flags"],
                })

        if not guidelines:
            return json.dumps({
                "status": "no_results",
                "message": f"No guidelines found for category '{clinical_category}'",
                "guidelines": []
            })

        return json.dumps({
            "status": "success",
            "category": clinical_category,
            "guidelines_found": len(guidelines),
            "guidelines": guidelines
        })

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": str(e),
            "guidelines": []
        })


# Quick test
if __name__ == "__main__":
    test_cases = [
        ("cardiac", "chest pain radiating to left arm"),
        ("respiratory", "asthma shortness of breath"),
        ("mental_health", "overdose self harm"),
        ("trauma", "head injury fall"),
    ]

    for category, symptoms in test_cases:
        print(f"\nCategory: {category} | Symptoms: {symptoms}")
        result = json.loads(rag_retriever(category, symptoms))
        print(f"  Found: {result['guidelines_found']} guidelines")
        for g in result["guidelines"]:
            print(f"  [{g['guideline_code']}] {g['title']}")