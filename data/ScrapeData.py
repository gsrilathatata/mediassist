# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import time
from tqdm import tqdm

BASE_URL = "https://www.mtsamples.com"

TARGET_SPECIALTIES = [
    {"name": "Emergency Room Reports",   "type": "93-Emergency Room Reports"},
    {"name": "Cardiovascular Pulmonary", "type": "6-Cardiovascular / Pulmonary"},
    {"name": "Discharge Summary",        "type": "89-Discharge Summary"},
    {"name": "Neurology",                "type": "42-Neurology"},
    {"name": "General Medicine",         "type": "98-General Medicine"},
    {"name": "Gastroenterology",         "type": "24-Gastroenterology"},
    {"name": "Nephrology",               "type": "41-Nephrology"},
    {"name": "SOAP Notes",               "type": "91-SOAP / Chart / Progress Notes"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def get_sample_links(specialty):
    url = BASE_URL + "/site/pages/browse.asp"
    params = {"Type": specialty["type"]}
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "sample.asp" in href and "Sample=" in href:
            full = href if href.startswith("http") else BASE_URL + "/" + href.lstrip("/")
            if full not in links:
                links.append(full)
    return links

def scrape_sample(url, specialty_name):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # Get title
        title = "Unknown"
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(separator=" ", strip=True)
            title = title.replace("Sample Name:", "").replace("Medical Specialty:", "").strip()
            title = title.split("Emergency Room")[0].split("Discharge Summary")[0].strip()

        # Find hilightBold div - this contains everything
        hilight = soup.find("div", class_="hilightBold")
        if not hilight:
            return None

        # Remove all child divs (disclaimers, headers, alerts, related, keywords)
        for div in hilight.find_all("div"):
            div.decompose()

        # Now only raw text and inline tags remain - this is the clinical content
        content = hilight.get_text(separator="\n", strip=True)

        # Clean empty lines
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        content = "\n".join(lines)

        if len(content) < 100:
            return None

        content = content[:3000]

        if "Emergency" in specialty_name:
            instruction = "[TASK: TRIAGE_NOTE] You are an ED triage nurse. Based on the clinical note, generate a structured triage assessment with priority level."
            task = "triage"
        elif "Discharge" in specialty_name:
            instruction = "[TASK: DISCHARGE_SUMMARY] You are a clinician. Generate a structured discharge summary from the clinical note."
            task = "discharge"
        elif "SOAP" in specialty_name:
            instruction = "[TASK: CLINICAL_NOTE] You are a clinician. Structure this note in SOAP format."
            task = "soap"
        else:
            instruction = "[TASK: CLINICAL_NOTE] You are a clinical documentation assistant. Structure the following clinical note properly."
            task = "general"

        return {
            "instruction": instruction,
            "input": "Specialty: {}\nTitle: {}\n\nClinical Note:\n{}".format(specialty_name, title, content),
            "output": content,
            "metadata": {
                "source": "mtsamples",
                "specialty": specialty_name,
                "title": title,
                "task": task,
                "url": url
            }
        }
    except Exception as e:
        return None

def main():
    output_file = "mtsamples_training_data.jsonl"
    results = []
    failed = 0
    stats = {}

    print("MTSamples Scraper - Final Version")
    print("=" * 50)

    for specialty in TARGET_SPECIALTIES:
        name = specialty["name"]
        print("\nScraping: {}".format(name))
        sample_links = get_sample_links(specialty)
        print("Found {} sample links".format(len(sample_links)))

        if not sample_links:
            continue

        specialty_count = 0
        for link in tqdm(sample_links):
            sample = scrape_sample(link, name)
            if sample:
                results.append(sample)
                specialty_count += 1
            else:
                failed += 1
            time.sleep(0.5)

        stats[name] = specialty_count
        print("  Saved: {}".format(specialty_count))

    with open(output_file, "w", encoding="utf-8") as f:
        for record in results:
            f.write(json.dumps(record) + "\n")

    print("\n" + "=" * 50)
    print("COMPLETE")
    print("Total saved : {}".format(len(results)))
    print("Failed      : {}".format(failed))
    print("\nBy specialty:")
    for n, c in stats.items():
        print("  {:<30} {}".format(n, c))
    print("\nFile: {}".format(output_file))

if __name__ == "__main__":
    main()
