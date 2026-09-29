import { useState, useEffect, useCallback } from "react";

const API_URL = "http://localhost:8000";

const COLORS = {
  ctas1: { bg: "#FEE2E2", text: "#991B1B", border: "#EF4444", label: "CTAS I" },
  ctas2: { bg: "#FEF3C7", text: "#92400E", border: "#F59E0B", label: "CTAS II" },
  ctas3: { bg: "#FEF9C3", text: "#854D0E", border: "#EAB308", label: "CTAS III" },
  ctas4: { bg: "#DCFCE7", text: "#166534", border: "#22C55E", label: "CTAS IV" },
  ctas5: { bg: "#DBEAFE", text: "#1E40AF", border: "#3B82F6", label: "CTAS V" },
  pending: { bg: "#F3F4F6", text: "#6B7280", border: "#D1D5DB", label: "Pending" },
};

// --- API helpers ---

async function callMediAssist(message, visitStage, nhsNumber = "") {
  const res = await fetch(`${API_URL}/api/mediassist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, nhs_number: nhsNumber }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

async function queueAPI(path, method = "GET", body = null) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${API_URL}${path}`, opts);
  if (!res.ok) throw new Error(`Queue API error: ${res.status}`);
  return res.json();
}

// --- Components ---

function Badge({ ctas }) {
  const c = COLORS[ctas] || COLORS.pending;
  return (
    <span style={{ background: c.bg, color: c.text, fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 6, minWidth: 52, textAlign: "center", display: "inline-block" }}>
      {c.label}
    </span>
  );
}

function RoleSelector({ onSelect }) {
  const [counts, setCounts] = useState({ nurse: 0, clinician: 0 });

  useEffect(() => {
    const fetchCounts = async () => {
      try {
        const [nurse, clin] = await Promise.all([
          queueAPI("/api/queue/nurse"),
          queueAPI("/api/queue/clinician"),
        ]);
        // FIX 6: guard against NaN when API returns undefined/null
        const nurseCount = (Number(nurse.waiting) || 0) + (Number(nurse.in_triage) || 0);
        const clinCount = Number(clin.count) || 0;
        setCounts({ nurse: nurseCount, clinician: clinCount });
      } catch (e) { /* ignore on load */ }
    };
    fetchCounts();
  }, []);

  return (
    <div style={{ maxWidth: 440, margin: "0 auto", padding: "60px 20px", textAlign: "center" }}>
      <h1 style={{ fontSize: 28, fontWeight: 700, margin: "0 0 8px", color: "#1a1a1a", letterSpacing: -0.5 }}>MediAssist</h1>
      <p style={{ fontSize: 15, color: "#888", margin: "0 0 40px" }}>Emergency Department AI assistant</p>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {[
          ["patient", "Patient kiosk", "Check in and describe your symptoms"],
          ["nurse", "Nurse triage", `AI-assisted triage and priority assessment (${counts.nurse} waiting)`],
          ["clinician", "Clinician", `Discharge summaries and GP referrals (${counts.clinician} ready)`],
        ].map(([key, title, desc]) => (
          <button key={key} onClick={() => onSelect(key)} style={{ padding: "20px", borderRadius: 12, border: "1px solid #E5E3DD", background: "#fff", cursor: "pointer", textAlign: "left" }}>
            <p style={{ fontSize: 16, fontWeight: 600, margin: "0 0 4px", color: "#1a1a1a" }}>{title}</p>
            <p style={{ fontSize: 13, color: "#888", margin: 0 }}>{desc}</p>
          </button>
        ))}
      </div>
      <p style={{ fontSize: 11, color: "#aaa", marginTop: 24 }}>Select your role to continue</p>
    </div>
  );
}

// ============================================================
// PATIENT KIOSK
// ============================================================

function PatientScreen({ onBack }) {
  const [mode, setMode] = useState("walkin");
  const [symptoms, setSymptoms] = useState("");
  const [pain, setPain] = useState(null);
  const [allergies, setAllergies] = useState("");
  const [meds, setMeds] = useState("");
  const [handover, setHandover] = useState("");
  const [preHospital, setPreHospital] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [queueNumber, setQueueNumber] = useState(null);
  const [patientSummary, setPatientSummary] = useState(null);
  // FIX 1: rejection message state for inline error banner
  const [rejectionMessage, setRejectionMessage] = useState(null);

  // FIX 2 + 5: unified submit using direct fetch (handles validation errors),
  // works for both walk-in and ambulance modes
  const handleSubmit = async () => {
    if (!symptoms.trim()) return;
    setSubmitting(true);
    setRejectionMessage(null);
    const qNum = `Q-${String(Math.floor(Math.random() * 900) + 100)}`;
    try {
      const res = await fetch(`${API_URL}/api/queue/patient`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: qNum,
          symptoms,
          pain: pain != null ? String(pain) : "",
          allergies,
          meds,
          arrival: mode === "ambulance" ? "Ambulance" : "Walk-in",
          handover,
          pre_hospital: preHospital,
        }),
      });
      if (!res.ok) {
        const errData = await res.json();
        setRejectionMessage(errData.detail || "Submission rejected. Please describe your medical symptoms.");
        setSubmitting(false);
        return;
      }
      setQueueNumber(qNum);
      setSubmitted(true);
    } catch (e) {
      alert("Failed to submit. Please try again.");
    }
    setSubmitting(false);
  };

  // Poll for patient summary after submission
  useEffect(() => {
    if (!submitted || !queueNumber) return;
    const interval = setInterval(async () => {
      try {
        const data = await queueAPI(`/api/queue/patient/${queueNumber}/summary`);
        if (data.status === "ready") {
          setPatientSummary(data.patient_summary);
          clearInterval(interval);
        }
      } catch (e) { /* keep polling */ }
    }, 5000);
    return () => clearInterval(interval);
  }, [submitted, queueNumber]);

  if (patientSummary) {
    return (
      <div style={{ maxWidth: 440, margin: "0 auto", padding: "40px 20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <h2 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: "#1a1a1a" }}>Your visit summary</h2>
          <button onClick={onBack} style={{ padding: "6px 12px", fontSize: 12, border: "1px solid #ddd", borderRadius: 6, background: "transparent", cursor: "pointer" }}>Back</button>
        </div>
        <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #E5E3DD", padding: 16 }}>
          <div style={{ background: "#DCFCE7", borderRadius: 8, padding: 12, marginBottom: 12 }}>
            <p style={{ fontSize: 13, fontWeight: 600, margin: 0, color: "#166534" }}>Your doctor has approved this summary</p>
          </div>
          <div style={{ fontSize: 14, color: "#555", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{patientSummary}</div>
          <p style={{ fontSize: 12, color: "#888", marginTop: 12 }}>If you feel unwell after leaving, call NHS 111 or return to A&E.</p>
        </div>
      </div>
    );
  }

  if (submitted) {
    return (
      <div style={{ maxWidth: 440, margin: "0 auto", padding: "40px 20px", textAlign: "center" }}>
        <button onClick={onBack} style={{ position: "absolute", top: 20, left: 20, padding: "6px 12px", fontSize: 12, border: "1px solid #ddd", borderRadius: 6, background: "transparent", cursor: "pointer" }}>Switch role</button>
        <div style={{ width: 64, height: 64, borderRadius: "50%", background: "#DCFCE7", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px", fontSize: 28, color: "#166534" }}>✓</div>
        <h2 style={{ fontSize: 22, fontWeight: 600, margin: "0 0 8px", color: "#1a1a1a" }}>Submitted</h2>
        <p style={{ fontSize: 15, color: "#666", margin: "0 0 24px", lineHeight: 1.6 }}>Your information has been received. A triage nurse will call you shortly.</p>
        <div style={{ background: "#F8F7F4", borderRadius: 12, padding: 20, textAlign: "left" }}>
          <p style={{ fontSize: 13, color: "#888", margin: "0 0 4px" }}>Your queue number</p>
          <p style={{ fontSize: 32, fontWeight: 700, margin: 0, color: "#1a1a1a", letterSpacing: 1 }}>{queueNumber}</p>
        </div>
        <p style={{ fontSize: 12, color: "#888", marginTop: 16 }}>Your summary will appear here once your doctor completes your visit.</p>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 440, margin: "0 auto", padding: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div style={{ textAlign: "center", flex: 1 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 4px", color: "#1a1a1a", letterSpacing: -0.5 }}>MediAssist</h1>
          <p style={{ fontSize: 14, color: "#888", margin: 0 }}>Emergency Department check-in</p>
        </div>
        <button onClick={onBack} style={{ padding: "6px 12px", fontSize: 12, border: "1px solid #ddd", borderRadius: 6, background: "transparent", cursor: "pointer" }}>Switch role</button>
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <button onClick={() => setMode("walkin")} style={{ flex: 1, padding: "10px", fontSize: 13, fontWeight: mode === "walkin" ? 600 : 400, background: mode === "walkin" ? "#1a1a1a" : "transparent", color: mode === "walkin" ? "#fff" : "#666", border: "1px solid #ddd", borderRadius: 8, cursor: "pointer" }}>Walk-in patient</button>
        <button onClick={() => setMode("ambulance")} style={{ flex: 1, padding: "10px", fontSize: 13, fontWeight: mode === "ambulance" ? 600 : 400, background: mode === "ambulance" ? "#1a1a1a" : "transparent", color: mode === "ambulance" ? "#fff" : "#666", border: "1px solid #ddd", borderRadius: 8, cursor: "pointer" }}>Ambulance arrival</button>
      </div>
      <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #E5E3DD", padding: 20 }}>
        {mode === "ambulance" && (<>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 13, color: "#888", display: "block", marginBottom: 4 }}>Paramedic handover notes</label>
            <textarea rows={3} value={handover} onChange={e => setHandover(e.target.value)} placeholder="Verbal handover summary from paramedic crew..." style={{ width: "100%", fontSize: 14, padding: 10, border: "1px solid #E5E3DD", borderRadius: 8, resize: "vertical", fontFamily: "inherit" }} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 13, color: "#888", display: "block", marginBottom: 4 }}>Pre-hospital treatment given</label>
            <textarea rows={2} value={preHospital} onChange={e => setPreHospital(e.target.value)} placeholder="e.g. oxygen 15L NRB, IV access, morphine 5mg..." style={{ width: "100%", fontSize: 14, padding: 10, border: "1px solid #E5E3DD", borderRadius: 8, resize: "vertical", fontFamily: "inherit" }} />
          </div>
        </>)}
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 13, color: "#888", display: "block", marginBottom: 4 }}>{mode === "walkin" ? "What brought you to the Emergency Department today?" : "Presenting complaint"}</label>
          <textarea rows={3} value={symptoms} onChange={e => setSymptoms(e.target.value)} placeholder={mode === "walkin" ? "Describe your symptoms in your own words..." : "Chief complaint and relevant symptoms..."} style={{ width: "100%", fontSize: 14, padding: 10, border: "1px solid #E5E3DD", borderRadius: 8, resize: "vertical", fontFamily: "inherit" }} />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 13, color: "#888", display: "block", marginBottom: 6 }}>Pain level (0-10)</label>
          <div style={{ display: "flex", gap: 4 }}>
            {[...Array(11)].map((_, i) => (
              <button key={i} onClick={() => setPain(i)} style={{ flex: 1, padding: "8px 0", fontSize: 13, fontWeight: pain === i ? 600 : 400, background: pain === i ? (i <= 3 ? "#DCFCE7" : i <= 6 ? "#FEF9C3" : "#FEE2E2") : "transparent", color: pain === i ? (i <= 3 ? "#166534" : i <= 6 ? "#854D0E" : "#991B1B") : "#666", border: `1px solid ${pain === i ? (i <= 3 ? "#22C55E" : i <= 6 ? "#EAB308" : "#EF4444") : "#ddd"}`, borderRadius: 6, cursor: "pointer" }}>{i}</button>
            ))}
          </div>
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 13, color: "#888", display: "block", marginBottom: 4 }}>Allergies</label>
          <input type="text" value={allergies} onChange={e => setAllergies(e.target.value)} placeholder="e.g. penicillin, nuts, latex..." style={{ width: "100%", fontSize: 14, padding: 10, border: "1px solid #E5E3DD", borderRadius: 8, fontFamily: "inherit" }} />
        </div>
        <div style={{ marginBottom: 20 }}>
          <label style={{ fontSize: 13, color: "#888", display: "block", marginBottom: 4 }}>Current medications</label>
          <input type="text" value={meds} onChange={e => setMeds(e.target.value)} placeholder="e.g. paracetamol, insulin, amlodipine..." style={{ width: "100%", fontSize: 14, padding: 10, border: "1px solid #E5E3DD", borderRadius: 8, fontFamily: "inherit" }} />
        </div>

        {/* FIX 1: inline rejection error banner */}
        {rejectionMessage && (
          <div style={{ background: "#FEE2E2", border: "1px solid #EF4444", borderRadius: 8, padding: 12, marginBottom: 12 }}>
            <p style={{ fontSize: 13, color: "#991B1B", margin: 0, fontWeight: 500 }}>{rejectionMessage}</p>
          </div>
        )}

        {/* FIX 5: single Submit button works for both walk-in and ambulance */}
        <button onClick={handleSubmit} disabled={submitting || !symptoms.trim()} style={{ width: "100%", padding: 14, fontSize: 15, fontWeight: 600, background: submitting ? "#666" : "#1a1a1a", color: "#fff", border: "none", borderRadius: 8, cursor: submitting ? "wait" : "pointer" }}>{submitting ? "Submitting..." : "Submit"}</button>
      </div>
      <p style={{ fontSize: 11, color: "#aaa", textAlign: "center", marginTop: 16, lineHeight: 1.5 }}>Your data is encrypted and processed in compliance with healthcare data protection standards.</p>
    </div>
  );
}

// ============================================================
// NURSE TRIAGE
// ============================================================

function NurseScreen({ onBack }) {
  const [queue, setQueue] = useState([]);
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [showResult, setShowResult] = useState(false);
  const [triageResult, setTriageResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [vitals, setVitals] = useState({ hr: "", bp: "", spo2: "", rr: "", temp: "", pain: "" });
  const [triageConfirmed, setTriageConfirmed] = useState(false);
  const [nhsNumber, setNhsNumber] = useState("NHS-7234891");

  // FIX 7: track waiting and in-triage counts separately
  const [waitingCount, setWaitingCount] = useState(0);
  const [inTriageCount, setInTriageCount] = useState(0);

  // Fetch nurse queue from API
  const fetchQueue = useCallback(async () => {
    try {
      const data = await queueAPI("/api/queue/nurse");
      setQueue(data.patients || []);
      // FIX 7: use the actual API counts instead of deriving from selectedPatient
      setWaitingCount(Number(data.waiting) || 0);
      setInTriageCount(Number(data.in_triage) || 0);
    } catch (e) { /* silent */ }
  }, []);

  useEffect(() => {
    fetchQueue();
    const interval = setInterval(fetchQueue, 5000);
    return () => clearInterval(interval);
  }, [fetchQueue]);

  const handleSelectPatient = async (p) => {
    setSelectedPatient(p);
    try {
      await queueAPI(`/api/queue/triage/start/${p.RowKey || p.id}`, "POST");
    } catch (e) { /* non-critical */ }
  };

  const handleRunTriage = async () => {
    setLoading(true); setError(null);
    try {
      const vitalsStr = [vitals.hr && `HR ${vitals.hr}`, vitals.bp && `BP ${vitals.bp}`, vitals.spo2 && `SpO2 ${vitals.spo2}`, vitals.rr && `RR ${vitals.rr}`, vitals.temp && `Temp ${vitals.temp}`, vitals.pain && `Pain ${vitals.pain}/10`].filter(Boolean).join(", ");
      const message = `Patient: ${selectedPatient.sex || "Unknown sex"}, ${selectedPatient.age || "Unknown age"} years old, arrival: ${selectedPatient.arrival || "Walk-in"}. Symptoms: ${selectedPatient.symptoms}. Vitals: ${vitalsStr}. Allergies: ${selectedPatient.allergies || "none"}. Medications: ${selectedPatient.meds || "none"}.`;
      const data = await callMediAssist(message, "triage", nhsNumber);
      setTriageResult(data.response); setShowResult(true);
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  };

  // Extract CTAS level from AI triage response text
  const extractCtas = (text) => {
    if (!text) return "pending";
    const lower = text.toLowerCase();
    const ctasMatch = lower.match(/ctas_score:\s*(\d)/);
    if (ctasMatch) return `ctas${ctasMatch[1]}`;
    // Match patterns like "triage level: 3", "ctas 2", "ctas ii", "level 5", "category 1"
    // Also match MTS colors: "red", "orange", "yellow", "green", "blue"
    const levelMatch = lower.match(/(?:triage\s*level|ctas|level|category)\s*[:,-]?\s*(\d)/i);
    if (levelMatch) return `ctas${levelMatch[1]}`;
    const romanMatch = lower.match(/(?:triage\s*level|ctas|level|category)\s*[:,-]?\s*(i{1,3}|iv|v)\b/i);
    if (romanMatch) {
      const romanMap = { "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5 };
      const num = romanMap[romanMatch[1].toLowerCase()];
      if (num) return `ctas${num}`;
    }
    // MTS color mapping
    if (/\bred\b.*(?:immediate|category|level)/i.test(lower) || /(?:immediate|category|level).*\bred\b/i.test(lower)) return "ctas1";
    if (/\borange\b/i.test(lower)) return "ctas2";
    if (/\byellow\b/i.test(lower)) return "ctas3";
    if (/\bgreen\b/i.test(lower)) return "ctas4";
    if (/\bblue\b/i.test(lower)) return "ctas5";
    return "pending";
  };

  const handleConfirmTriage = async () => {
    const pid = selectedPatient.RowKey || selectedPatient.id;
    const detectedCtas = extractCtas(triageResult);
    try {
      await queueAPI("/api/queue/triage", "POST", {
        queue_id: pid,
        triage_result: triageResult,
        ctas: detectedCtas,
        nhs_number: nhsNumber,
      });
      setTriageConfirmed(true);
      fetchQueue();
    } catch (e) {
      setTriageConfirmed(true);
    }
  };

  if (triageConfirmed) {
    return (
      <div style={{ padding: 20, textAlign: "center" }}>
        <div style={{ width: 64, height: 64, borderRadius: "50%", background: "#DCFCE7", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px", fontSize: 28, color: "#166534" }}>✓</div>
        <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 8px", color: "#1a1a1a" }}>Triage confirmed — {selectedPatient.RowKey || selectedPatient.id}</h2>
        <p style={{ fontSize: 14, color: "#666", margin: "0 0 20px" }}>Patient assigned to clinician queue.</p>
        <button onClick={() => { setTriageConfirmed(false); setSelectedPatient(null); setShowResult(false); setTriageResult(null); fetchQueue(); }} style={{ padding: "10px 24px", fontSize: 14, border: "1px solid #ddd", borderRadius: 8, background: "transparent", cursor: "pointer" }}>Back to queue</button>
      </div>
    );
  }

  const queueId = (p) => p.RowKey || p.id;

  return (
    <div style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: "0 0 2px", color: "#1a1a1a", letterSpacing: -0.5 }}>MediAssist — Nurse triage</h1>
          <p style={{ fontSize: 13, color: "#888", margin: 0 }}>ED dashboard — sorted by AI-estimated urgency</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {/* FIX 7: use API-sourced counts, not derived from UI state */}
          {[["Waiting", String(waitingCount)], ["In triage", String(inTriageCount)]].map(([label, val]) => (
            <div key={label} style={{ background: "#F8F7F4", borderRadius: 8, padding: "8px 14px", textAlign: "center" }}>
              <p style={{ fontSize: 11, color: "#888", margin: 0 }}>{label}</p>
              <p style={{ fontSize: 18, fontWeight: 600, margin: "2px 0 0", color: "#1a1a1a" }}>{val}</p>
            </div>
          ))}
          <button onClick={onBack} style={{ padding: "6px 12px", fontSize: 12, border: "1px solid #ddd", borderRadius: 6, background: "transparent", cursor: "pointer" }}>Switch role</button>
        </div>
      </div>

      {!selectedPatient && (
        <div>
          {queue.length === 0 && <p style={{ fontSize: 14, color: "#888", textAlign: "center", padding: 40 }}>No patients in queue — waiting for kiosk submissions</p>}
          {queue.map((p) => {
            const c = COLORS[p.ctas] || COLORS.pending;
            return (
              <div key={queueId(p)} onClick={() => handleSelectPatient(p)} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px", marginBottom: 6, border: "1px solid #E5E3DD", borderLeftWidth: 3, borderLeftColor: c.border, cursor: "pointer", background: "#fff" }}>
                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                  <Badge ctas={p.ctas} />
                  <div>
                    <p style={{ fontSize: 14, fontWeight: 500, margin: 0, color: "#1a1a1a" }}>{queueId(p)} — {p.sex || "New patient"}{p.age ? `, ${p.age}` : ""}</p>
                    <p style={{ fontSize: 12, color: "#888", margin: "2px 0 0" }}>{p.symptoms}</p>
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <p style={{ fontSize: 11, color: "#888", margin: 0 }}>{p.arrival || "Walk-in"}</p>
                  <p style={{ fontSize: 11, color: "#aaa", margin: "2px 0 0" }}>{p.status || "waiting"}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {selectedPatient && !showResult && (
        <div>
          <button onClick={() => setSelectedPatient(null)} style={{ padding: "6px 12px", fontSize: 13, marginBottom: 16, border: "1px solid #ddd", borderRadius: 6, background: "transparent", cursor: "pointer" }}>← Back to queue</button>
          <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #E5E3DD", padding: 20, marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0, color: "#1a1a1a" }}>Triage — {queueId(selectedPatient)}</h2>
              <Badge ctas={selectedPatient.ctas} />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 13, color: "#888", display: "block", marginBottom: 4 }}>Symptoms (from kiosk)</label>
              <textarea rows={3} defaultValue={selectedPatient.symptoms} style={{ width: "100%", fontSize: 13, padding: 10, border: "1px solid #E5E3DD", borderRadius: 8, fontFamily: "inherit" }} />
            </div>
            {selectedPatient.allergies && (
              <div style={{ marginBottom: 12 }}>
                <span style={{ fontSize: 12, background: "#FEE2E2", padding: "3px 8px", borderRadius: 4, color: "#991B1B" }}>Allergies: {selectedPatient.allergies}</span>
                {selectedPatient.meds && <span style={{ fontSize: 12, background: "#DBEAFE", padding: "3px 8px", borderRadius: 4, color: "#1E40AF", marginLeft: 8 }}>Meds: {selectedPatient.meds}</span>}
              </div>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 16 }}>
              {[["HR", "hr", "bpm"], ["BP", "bp", "mmHg"], ["SpO2", "spo2", "%"], ["RR", "rr", "/min"], ["Temp", "temp", "°C"], ["Pain", "pain", "/10"]].map(([label, key, unit]) => (
                <div key={key}>
                  <label style={{ fontSize: 12, color: "#888", display: "block", marginBottom: 4 }}>{label} ({unit})</label>
                  <input type="text" value={vitals[key]} onChange={e => setVitals({...vitals, [key]: e.target.value})} placeholder={selectedPatient.pain != null && key === "pain" ? String(selectedPatient.pain) : "—"} style={{ width: "100%", fontSize: 14, padding: 8, border: "1px solid #E5E3DD", borderRadius: 6, fontFamily: "inherit" }} />
                </div>
              ))}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 16 }}>
              <div>
                <label style={{ fontSize: 12, color: "#888", display: "block", marginBottom: 4 }}>NHS number</label>
                <input type="text" value={nhsNumber} onChange={e => setNhsNumber(e.target.value)} style={{ width: "100%", fontSize: 13, padding: 8, border: "1px solid #E5E3DD", borderRadius: 6, fontFamily: "inherit" }} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: "#888", display: "block", marginBottom: 4 }}>Age / Sex</label>
                <input type="text" value={[selectedPatient.age, selectedPatient.sex].filter(Boolean).join(" / ") || "From kiosk"} readOnly style={{ width: "100%", fontSize: 13, padding: 8, border: "1px solid #E5E3DD", borderRadius: 6, fontFamily: "inherit", background: "#F8F7F4" }} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: "#888", display: "block", marginBottom: 4 }}>Arrival</label>
                <input type="text" value={selectedPatient.arrival || "Walk-in"} readOnly style={{ width: "100%", fontSize: 13, padding: 8, border: "1px solid #E5E3DD", borderRadius: 6, fontFamily: "inherit", background: "#F8F7F4" }} />
              </div>
            </div>
            <button onClick={handleRunTriage} disabled={loading} style={{ width: "100%", padding: 12, fontSize: 15, fontWeight: 600, background: loading ? "#666" : "#1a1a1a", color: "#fff", border: "none", borderRadius: 8, cursor: loading ? "wait" : "pointer" }}>{loading ? "Running AI triage..." : "Run AI triage"}</button>
            {error && <p style={{ color: "#991B1B", fontSize: 13, marginTop: 8 }}>Error: {error}</p>}
          </div>
        </div>
      )}

      {selectedPatient && showResult && triageResult && (
        <div>
          <button onClick={() => { setShowResult(false); setTriageResult(null); }} style={{ padding: "6px 12px", fontSize: 13, marginBottom: 16, border: "1px solid #ddd", borderRadius: 6, background: "transparent", cursor: "pointer" }}>← Back to form</button>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0, color: "#1a1a1a" }}>Triage result — {queueId(selectedPatient)}</h2>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Badge ctas={extractCtas(triageResult)} />
              <span style={{ background: "#FEE2E2", color: "#991B1B", fontSize: 13, fontWeight: 600, padding: "6px 16px", borderRadius: 8 }}>AI Triage Complete</span>
            </div>
          </div>
          <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #E5E3DD", padding: 16, marginBottom: 12 }}>
            <p style={{ fontSize: 14, fontWeight: 600, margin: "0 0 8px", color: "#1a1a1a" }}>AI Triage Assessment</p>
            <div style={{ fontSize: 13, color: "#666", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{triageResult}</div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button style={{ flex: 1, padding: 12, fontSize: 14, border: "1px solid #ddd", borderRadius: 8, background: "transparent", cursor: "pointer" }}>Override triage level</button>
            <button onClick={handleConfirmTriage} style={{ flex: 1, padding: 12, fontSize: 14, fontWeight: 600, background: "#1a1a1a", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer" }}>Confirm triage + assign</button>
          </div>
        </div>
      )}
      <p style={{ fontSize: 11, color: "#aaa", marginTop: 16 }}>AI-generated clinical decision support. All decisions must be validated by a qualified clinician.</p>
    </div>
  );
}

// ============================================================
// CLINICIAN
// ============================================================

function ClinicianScreen({ onBack }) {
  const [clinicianQueue, setClinicianQueue] = useState([]);
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [decision, setDecision] = useState(null);
  const [dischargeSummary, setDischargeSummary] = useState(null);
  const [patientExplanation, setPatientExplanation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingExplain, setLoadingExplain] = useState(false);
  const [error, setError] = useState(null);
  const [approved, setApproved] = useState(false);
  const [findings, setFindings] = useState("");

  // Fetch clinician queue from API
  const fetchClinicianQueue = useCallback(async () => {
    try {
      const data = await queueAPI("/api/queue/clinician");
      setClinicianQueue(data.patients || []);
    } catch (e) { /* silent */ }
  }, []);

  useEffect(() => {
    fetchClinicianQueue();
    const interval = setInterval(fetchClinicianQueue, 5000);
    return () => clearInterval(interval);
  }, [fetchClinicianQueue]);

  const handleSelectPatient = async (p) => {
    setSelectedPatient(p);
    setFindings("");
    setDischargeSummary(null);
    setPatientExplanation(null);
    setDecision(null);
    setApproved(false);
    try {
      await queueAPI(`/api/queue/clinician/assign/${p.RowKey || p.id}`, "POST");
    } catch (e) { /* non-critical */ }
  };

  const handleGenerate = async (type) => {
    setLoading(true); setError(null);
    const pid = selectedPatient.RowKey || selectedPatient.id;
    const nhsNum = selectedPatient.nhs_number || "NHS-7234891";
    try {
      const message = type === "discharge"
        ? `Patient ${pid}. Triage result: ${selectedPatient.triage_result || "See notes"}. Clinical findings: ${findings}. Decision: Discharge. Generate a discharge summary.`
        : `Patient ${pid}. Triage result: ${selectedPatient.triage_result || "See notes"}. Clinical findings: ${findings}. Decision: Discharge. Generate a GP referral letter.`;
      const data = await callMediAssist(message, "discharge", nhsNum);
      setDischargeSummary(data.response);
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  };

  const handleApprove = async () => {
    setLoadingExplain(true); setError(null);
    const pid = selectedPatient.RowKey || selectedPatient.id;
    const nhsNum = selectedPatient.nhs_number || "NHS-7234891";
    try {
      const data = await callMediAssist(
        `Discharge summary: ${dischargeSummary}. Please explain this to the patient in simple plain English.`,
        "patient_explanation", nhsNum
      );
      setPatientExplanation(data.response);

      // FIX 3: include patient_email and patient_name in discharge POST
      await queueAPI("/api/queue/discharge", "POST", {
        queue_id: pid,
        discharge_summary: dischargeSummary,
        patient_summary: data.response,
        patient_email: "patient@example.com",
        patient_name: `Patient ${pid}`,
      });

      setApproved(true);
      fetchClinicianQueue();
    } catch (err) { setError(err.message); } finally { setLoadingExplain(false); }
  };

  const queueId = (p) => p.RowKey || p.id;

  // No patient selected — show clinician queue
  if (!selectedPatient) {
    return (
      <div style={{ padding: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: "0 0 2px", color: "#1a1a1a", letterSpacing: -0.5 }}>MediAssist — Clinician</h1>
            <p style={{ fontSize: 13, color: "#888", margin: 0 }}>Patients ready for clinical review</p>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ background: "#EFF6FF", color: "#1E40AF", fontSize: 12, padding: "4px 12px", borderRadius: 6 }}>Dr. S. Patel</span>
            <button onClick={onBack} style={{ padding: "6px 12px", fontSize: 12, border: "1px solid #ddd", borderRadius: 6, background: "transparent", cursor: "pointer" }}>Switch role</button>
          </div>
        </div>
        {clinicianQueue.length === 0 && <p style={{ fontSize: 14, color: "#888", textAlign: "center", padding: 40 }}>No patients in clinician queue — waiting for nurse triage</p>}
        {clinicianQueue.map((p) => (
          <div key={queueId(p)} onClick={() => handleSelectPatient(p)} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px", marginBottom: 6, border: "1px solid #E5E3DD", borderLeftWidth: 3, borderLeftColor: "#EF4444", cursor: "pointer", background: "#fff", borderRadius: 8 }}>
            <div>
              <p style={{ fontSize: 14, fontWeight: 500, margin: 0, color: "#1a1a1a" }}>{queueId(p)} — {p.sex || "Patient"}{p.age ? `, ${p.age}` : ""}</p>
              <p style={{ fontSize: 12, color: "#888", margin: "2px 0 0" }}>{p.symptoms}</p>
            </div>
            <div style={{ textAlign: "right" }}>
              <Badge ctas={p.ctas} />
              <p style={{ fontSize: 11, color: "#888", margin: "4px 0 0" }}>NHS: {p.nhs_number || "—"}</p>
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (approved) {
    return (
      <div style={{ padding: 20, textAlign: "center" }}>
        <div style={{ width: 64, height: 64, borderRadius: "50%", background: "#DCFCE7", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px", fontSize: 28, color: "#166534" }}>✓</div>
        <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 8px", color: "#1a1a1a" }}>Discharge approved and signed</h2>
        <p style={{ fontSize: 14, color: "#666", margin: "0 0 8px" }}>Patient: {queueId(selectedPatient)} (NHS: {selectedPatient.nhs_number || "—"})</p>
        {/* FIX 4: changed from "sent to patient kiosk" to "email sent" */}
        <p style={{ fontSize: 14, color: "#666", margin: "0 0 12px" }}>Discharge summary emailed to patient.</p>
        {patientExplanation && (
          <div style={{ background: "#F0FDF4", borderRadius: 12, border: "1px solid #22C55E", padding: 16, marginBottom: 16, textAlign: "left" }}>
            {/* FIX 4: updated label to reflect email delivery */}
            <p style={{ fontSize: 13, fontWeight: 600, margin: "0 0 8px", color: "#166534" }}>Patient summary (emailed to patient)</p>
            <div style={{ fontSize: 13, color: "#555", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{patientExplanation}</div>
          </div>
        )}
        <button onClick={() => { setApproved(false); setSelectedPatient(null); setDischargeSummary(null); setPatientExplanation(null); setDecision(null); fetchClinicianQueue(); }} style={{ padding: "10px 24px", fontSize: 14, border: "1px solid #ddd", borderRadius: 8, background: "transparent", cursor: "pointer" }}>Next patient</button>
      </div>
    );
  }

  return (
    <div style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: "0 0 2px", color: "#1a1a1a", letterSpacing: -0.5 }}>MediAssist — Clinician</h1>
          <p style={{ fontSize: 13, color: "#888", margin: 0 }}>Discharge summary and GP referral generator</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ background: "#EFF6FF", color: "#1E40AF", fontSize: 12, padding: "4px 12px", borderRadius: 6 }}>Dr. S. Patel</span>
          <button onClick={() => setSelectedPatient(null)} style={{ padding: "6px 12px", fontSize: 12, border: "1px solid #ddd", borderRadius: 6, background: "transparent", cursor: "pointer" }}>Back to queue</button>
        </div>
      </div>

      <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #E5E3DD", padding: 16, marginBottom: 12 }}>
        <p style={{ fontSize: 14, fontWeight: 600, margin: "0 0 10px", color: "#1a1a1a" }}>Patient summary (from triage)</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 10 }}>
          {[["Patient", `${queueId(selectedPatient)}${selectedPatient.age ? `, ${selectedPatient.age}${selectedPatient.sex ? selectedPatient.sex[0] : ""}` : ""}`], ["NHS number", selectedPatient.nhs_number || "—"], ["Triage", selectedPatient.ctas || "pending"], ["Arrival", selectedPatient.arrival || "Walk-in"]].map(([label, val]) => (
            <div key={label} style={{ background: "#F8F7F4", borderRadius: 8, padding: 8 }}>
              <p style={{ fontSize: 11, color: "#888", margin: 0 }}>{label}</p>
              <p style={{ fontSize: 13, fontWeight: 500, margin: "2px 0 0", color: "#1a1a1a" }}>{val}</p>
            </div>
          ))}
        </div>
        <p style={{ fontSize: 12, color: "#888", margin: "0 0 8px" }}>Symptoms: {selectedPatient.symptoms}</p>
        {selectedPatient.triage_result && (
          <details style={{ fontSize: 12, color: "#666" }}>
            <summary style={{ cursor: "pointer", color: "#1E40AF" }}>View AI triage result</summary>
            <div style={{ whiteSpace: "pre-wrap", marginTop: 8, padding: 12, background: "#F8F7F4", borderRadius: 8 }}>{selectedPatient.triage_result}</div>
          </details>
        )}
      </div>

      <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #E5E3DD", padding: 16, marginBottom: 12 }}>
        <p style={{ fontSize: 14, fontWeight: 600, margin: "0 0 10px", color: "#1a1a1a" }}>Clinician decision</p>
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <button onClick={() => setDecision("admit")} style={{ flex: 1, padding: 10, fontSize: 13, fontWeight: 500, background: decision === "admit" ? "#FEE2E2" : "transparent", color: decision === "admit" ? "#991B1B" : "#666", border: `1px solid ${decision === "admit" ? "#EF4444" : "#ddd"}`, borderRadius: 8, cursor: "pointer" }}>Admit</button>
          <button onClick={() => setDecision("discharge")} style={{ flex: 1, padding: 10, fontSize: 13, fontWeight: 500, background: decision === "discharge" ? "#DCFCE7" : "transparent", color: decision === "discharge" ? "#166534" : "#666", border: `1px solid ${decision === "discharge" ? "#22C55E" : "#ddd"}`, borderRadius: 8, cursor: "pointer" }}>Discharge</button>
        </div>
        <div>
          <label style={{ fontSize: 13, color: "#888", display: "block", marginBottom: 4 }}>Clinical findings and plan</label>
          <textarea rows={4} value={findings} onChange={e => setFindings(e.target.value)} placeholder="Enter clinical findings, investigations, and plan..." style={{ width: "100%", fontSize: 13, padding: 10, border: "1px solid #E5E3DD", borderRadius: 8, fontFamily: "inherit", lineHeight: 1.6 }} />
        </div>
      </div>

      {decision === "discharge" && (
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <button onClick={() => handleGenerate("discharge")} disabled={loading} style={{ flex: 1, padding: 12, fontSize: 14, fontWeight: 600, background: loading ? "#666" : "#1a1a1a", color: "#fff", border: "none", borderRadius: 8, cursor: loading ? "wait" : "pointer" }}>{loading ? "Generating..." : "Generate discharge summary"}</button>
          <button onClick={() => handleGenerate("referral")} disabled={loading} style={{ flex: 1, padding: 12, fontSize: 14, fontWeight: 600, background: loading ? "#555" : "#166534", color: "#fff", border: "none", borderRadius: 8, cursor: loading ? "wait" : "pointer" }}>{loading ? "Generating..." : "Generate GP referral"}</button>
        </div>
      )}

      {error && <p style={{ color: "#991B1B", fontSize: 13, marginBottom: 12 }}>Error: {error}</p>}

      {dischargeSummary && (
        <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #E5E3DD", padding: 16, marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <p style={{ fontSize: 14, fontWeight: 600, margin: 0, color: "#1a1a1a" }}>AI-generated document</p>
            <span style={{ fontSize: 11, color: "#888" }}>Powered by MediAssist Agent</span>
          </div>
          <div style={{ background: "#F8F7F4", borderRadius: 8, padding: 14, fontSize: 13, color: "#555", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{dischargeSummary}</div>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button onClick={() => setDischargeSummary(null)} style={{ flex: 1, padding: 10, fontSize: 13, border: "1px solid #ddd", borderRadius: 8, background: "transparent", cursor: "pointer" }}>Regenerate</button>
            <button onClick={handleApprove} disabled={loadingExplain} style={{ flex: 1, padding: 10, fontSize: 13, fontWeight: 600, background: loadingExplain ? "#666" : "#1a1a1a", color: "#fff", border: "none", borderRadius: 8, cursor: loadingExplain ? "wait" : "pointer" }}>{loadingExplain ? "Generating patient summary..." : "Approve and sign"}</button>
          </div>
        </div>
      )}
      <p style={{ fontSize: 11, color: "#aaa", marginTop: 16 }}>AI-generated clinical document. Must be reviewed and approved by the responsible clinician before issuing.</p>
    </div>
  );
}

// ============================================================
// MAIN APP
// ============================================================

export default function App() {
  const [screen, setScreen] = useState(null);

  if (!screen) return <RoleSelector onSelect={setScreen} />;

  return (
    <div style={{ fontFamily: "'DM Sans', sans-serif", maxWidth: 780, margin: "0 auto", minHeight: "100vh", background: "#FAFAF8" }}>
      {screen === "patient" && <PatientScreen onBack={() => setScreen(null)} />}
      {screen === "nurse" && <NurseScreen onBack={() => setScreen(null)} />}
      {screen === "clinician" && <ClinicianScreen onBack={() => setScreen(null)} />}
    </div>
  );
}
