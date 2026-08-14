from __future__ import annotations

import getpass
import smtplib
import ssl


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

sender_email = input("Sender Gmail address: ").strip()
app_password = getpass.getpass("Gmail App Password: ").strip()

context = ssl.create_default_context()

print("Connecting to Gmail SMTP...")

with smtplib.SMTP_SSL(
    SMTP_HOST,
    SMTP_PORT,
    context=context,
    timeout=30,
) as smtp:
    smtp.login(sender_email, app_password)

print("SMTP authentication successful.")