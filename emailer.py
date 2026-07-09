"""
Sends the finished brief to your Gmail using an app password (see README).
Nothing here stores your password; it is read from a GitHub secret at runtime.
"""
import os
import smtplib
from email.message import EmailMessage

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
RECIPIENT = os.environ.get("RECIPIENT", GMAIL_ADDRESS).strip()


def send_brief(subject, html_body, attachment_path):
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD):
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set (see README).")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT
    msg.set_content("Your market brief is in HTML. Attachment included.")
    msg.add_alternative(html_body, subtype="html")

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=os.path.basename(attachment_path),
        )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        s.send_message(msg)
