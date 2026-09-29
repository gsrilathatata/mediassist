"""
MediAssist Email Service

Sends discharge summaries and patient explanations via
Azure Communication Services Email.
"""

import os
import logging

logger = logging.getLogger("mediassist.email")

try:
    from azure.communication.email import EmailClient
    HAS_EMAIL = True
except ImportError:
    HAS_EMAIL = False
    logger.warning("azure-communication-email not installed — email disabled")


CONNECTION_STRING = os.environ.get("AZURE_COMMUNICATION_CONNECTION", "")
SENDER = os.environ.get("AZURE_EMAIL_SENDER", "DoNotReply@your-acs-domain.azurecomm.net")


def send_discharge_email(to_email: str, patient_name: str, patient_summary: str, queue_id: str = "") -> dict:
    """
    Send the plain English discharge summary to the patient's email.
    """
    if not HAS_EMAIL or not CONNECTION_STRING:
        logger.warning("Email not configured — skipping send")
        return {"status": "skipped", "reason": "Email not configured"}

    try:
        client = EmailClient.from_connection_string(CONNECTION_STRING)

        message = {
            "senderAddress": SENDER,
            "recipients": {
                "to": [{"address": to_email, "displayName": patient_name or "Patient"}]
            },
            "content": {
                "subject": f"MediAssist — Your visit summary{' (' + queue_id + ')' if queue_id else ''}",
                "plainText": patient_summary,
                "html": _build_html(patient_name, patient_summary, queue_id),
            }
        }

        poller = client.begin_send(message)
        result = poller.result()

        logger.info(f"Email sent to {to_email} — message ID: {result['id']}")
        return {"status": "sent", "message_id": result["id"], "to": to_email}

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return {"status": "error", "message": str(e)}


def _build_html(patient_name: str, summary: str, queue_id: str) -> str:
    """Build a simple HTML email."""
    name = patient_name or "there"
    lines = summary.replace("\n", "<br/>")
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: #005EB8; padding: 16px 20px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 20px;">MediAssist — NHS Emergency Department</h1>
        </div>
        <div style="border: 1px solid #ddd; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
            <p style="font-size: 16px; color: #333;">Hello {name},</p>
            <p style="font-size: 14px; color: #555;">Here is the summary from your visit today{' (ref: ' + queue_id + ')' if queue_id else ''}:</p>
            <div style="background: #F0F4F5; padding: 16px; border-radius: 8px; margin: 16px 0; font-size: 14px; color: #333; line-height: 1.7;">
                {lines}
            </div>
            <p style="font-size: 14px; color: #555;"><strong>If you feel unwell after leaving, call NHS 111 or return to A&amp;E immediately.</strong></p>
            <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;"/>
            <p style="font-size: 11px; color: #888;">This summary was approved by your doctor. AI-generated clinical decision support — validated by a qualified clinician.</p>
        </div>
    </div>
    """
