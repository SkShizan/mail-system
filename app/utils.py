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

        port = smtp_settings.port or 587
        
        # Use a more robust connection logic with automatic port/protocol fallback
        def try_send(p, use_ssl=False):
            if use_ssl:
                s = smtplib.SMTP_SSL(smtp_settings.server, p, timeout=15)
            else:
                s = smtplib.SMTP(smtp_settings.server, p, timeout=15)
                s.ehlo()
                try:
                    s.starttls()
                    s.ehlo()
                except:
                    pass
            s.login(smtp_settings.username, smtp_settings.password)
            s.send_message(msg)
            s.quit()
            return True

        # Attempt 1: User's preferred port
        try:
            return try_send(port, use_ssl=(port == 465))
        except Exception as e:
            print(f"⚠️ Attempt 1 failed (Port {port}): {e}")
            
        # Attempt 2: Fallback to common secure ports
        fallbacks = [465, 587, 25]
        for f_port in fallbacks:
            if f_port == port: continue
            try:
                print(f"🔄 Trying fallback Port {f_port}...")
                return try_send(f_port, use_ssl=(f_port == 465))
            except Exception as fe:
                print(f"❌ Port {f_port} failed: {fe}")
                
        return False
    except Exception as e:
        print(f"❌ System email critical failure: {e}")
        return False
