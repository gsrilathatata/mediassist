import re, logging
audit_logger = logging.getLogger("mediassist.audit")
audit_logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s | PHI_AUDIT | %(message)s"))
audit_logger.addHandler(handler)
PHI_PATTERNS = [("NHS_NUMBER", r'\b(?:NHS[-\s]?)?\d{3}[-\s]?\d{3}[-\s]?\d{4}\b'), ("NHS_NUMBER", r'\bNHS[-\s]?\d{5,10}\b'), ("PHONE_UK", r'\b(?:0\d{4}[\s-]?\d{6}|0\d{3}[\s-]?\d{3}[\s-]?\d{4}|07\d{3}[\s-]?\d{6})\b'), ("EMAIL", r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), ("POSTCODE_UK", r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b'), ("DOB", r'\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b'), ("IP_ADDRESS", r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')]
REPLACEMENTS = {"NHS_NUMBER": "<NHS_NUMBER>", "PHONE_UK": "<PHONE>", "EMAIL": "<EMAIL>", "POSTCODE_UK": "<POSTCODE>", "DOB": "<DOB>", "IP_ADDRESS": "<IP>"}
def scrub_phi(text: str) -> dict:
    scrubbed, detected = text, []
    for et, p in PHI_PATTERNS:
        for m in re.finditer(p, scrubbed, re.IGNORECASE): detected.append({"type": et, "value": m.group(), "start": m.start(), "end": m.end()})
    for et, p in PHI_PATTERNS: scrubbed = re.sub(p, REPLACEMENTS.get(et, "<PHI_REDACTED>"), scrubbed, flags=re.IGNORECASE)
    if detected: audit_logger.info(f"PHI detected: {len(detected)} entities | types: {[d['type'] for d in detected]}")
    return {"scrubbed_text": scrubbed, "original_text": text, "phi_detected": detected, "phi_count": len(detected)}
