import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.models import SMTPSettings, User


def send_system_email(recipient, subject, body):
    """
    Sends a system email (OTP, notifications, etc.)
    using the admin user's SMTP settings or fallback to .env (Gmail).
    """

    # ─────────────────────────────────────────────
    # 1️⃣ Get SMTP Settings from DB or .env
    # ─────────────────────────────────────────────
    admin = User.query.filter_by(is_admin=True).first()

    smtp_settings = None
    if admin:
        smtp_settings = SMTPSettings.query.filter_by(user_id=admin.id).first()

    # Use database settings if present, else fallback to .env
    smtp_server = (smtp_settings.server if smtp_settings and smtp_settings.server
                   else os.getenv("SYSTEM_MAIL_SERVER"))
    smtp_port = (smtp_settings.port if smtp_settings and smtp_settings.port
                 else int(os.getenv("SYSTEM_MAIL_PORT", 587)))
    smtp_user = (smtp_settings.username if smtp_settings and smtp_settings.username
                 else os.getenv("SYSTEM_MAIL_USERNAME"))
    smtp_pass = (smtp_settings.password if smtp_settings and smtp_settings.password
                 else os.getenv("SYSTEM_MAIL_PASSWORD"))
    smtp_sender = (smtp_settings.default_sender if smtp_settings and smtp_settings.default_sender
                   else os.getenv("SYSTEM_MAIL_SENDER", smtp_user))

    if not all([smtp_server, smtp_port, smtp_user, smtp_pass, smtp_sender]):
        print("❌ SMTP configuration incomplete.")
        return False

    # ─────────────────────────────────────────────
    # 2️⃣ Build Email
    # ─────────────────────────────────────────────
    msg = MIMEMultipart()
    msg["From"] = smtp_sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))

    # ─────────────────────────────────────────────
    # 3️⃣ Send Email over TLS (Port 587)
    # ─────────────────────────────────────────────
    try:
        context = ssl.create_default_context()
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
        server.set_debuglevel(1)  # Optional: prints SMTP debug info
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_sender, [recipient], msg.as_string())
        server.quit()
        print(f"✅ System email sent to {recipient}")
        return True

    except Exception as e:
        print(f"❌ SMTP send failed: {e}")
        return False
