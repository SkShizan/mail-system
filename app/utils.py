import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.models import SMTPSettings, User
from flask import current_app

def send_system_email(recipient, subject, body):
    """
    Sends a system email (like OTP) using the admin's SMTP settings
    or a fallback configuration.
    """
    # 1. Try to get admin SMTP settings
    admin = User.query.filter_by(is_admin=True).first()
    if not admin:
        print("❌ No admin user found for system email.")
        return False
        
    smtp_settings = SMTPSettings.query.filter_by(user_id=admin.id).first()
    if not smtp_settings or not smtp_settings.server:
        print(f"❌ No SMTP settings found for admin {admin.username}.")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_settings.default_sender or smtp_settings.username
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        # Use Port 465 for SSL or 587 for STARTTLS based on common settings
        # Some servers close connection if EHLO isn't handled correctly or port is wrong
        port = smtp_settings.port or 587
        
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_settings.server, port, timeout=30)
        else:
            server = smtplib.SMTP(smtp_settings.server, port, timeout=30)
            server.ehlo()
            if smtp_settings.use_tls:
                server.starttls()
                server.ehlo()
            
        server.login(smtp_settings.username, smtp_settings.password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"❌ Failed to send system email: {e}")
        return False
