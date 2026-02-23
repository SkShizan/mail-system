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
    # 3️⃣ Send Email with Automatic Port/Protocol Fallback
    # ─────────────────────────────────────────────
    def try_send(p, use_ssl=False):
        if use_ssl:
            s = smtplib.SMTP_SSL(smtp_server, p, timeout=15)
        else:
            s = smtplib.SMTP(smtp_server, p, timeout=15)
            s.ehlo()
            try:
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            except:
                pass # Continue if STARTTLS fails
        s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_sender, [recipient], msg.as_string())
        s.quit()
        return True

    try:
        # Try the configured port first
        return try_send(smtp_port, use_ssl=(smtp_port == 465))
    except Exception as e:
        print(f"⚠️ Initial SMTP attempt failed (Port {smtp_port}): {e}")
        
        # Fallback sequence: 465 -> 587 -> 25
        for fallback_port in [465, 587, 25]:
            if fallback_port == smtp_port: continue
            try:
                print(f"🔄 Trying fallback Port {fallback_port}...")
                return try_send(fallback_port, use_ssl=(fallback_port == 465))
            except Exception as fe:
                print(f"❌ Fallback Port {fallback_port} failed: {fe}")
        
        return False
