import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import current_app
from app import db
from app.models import Email, SMTPSettings
import time
from datetime import datetime
import threading
import schedule

# Helper to try multiple possible attribute names
def get_setting(obj, *names, default=None):
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default

def send_email(subject, recipient, body):
    with current_app.app_context():
        settings = SMTPSettings.query.first()
        if not settings:
            print("No SMTP settings found.")
            return False

        # fetch settings with fallbacks
        smtp_server = get_setting(settings, 'smtp_server', 'server', 'host')
        smtp_port = get_setting(settings, 'smtp_port', 'port')
        smtp_username = get_setting(settings, 'smtp_username', 'username', 'smtp_user')
        smtp_password = get_setting(settings, 'smtp_password', 'password', 'smtp_pass')
        from_email = get_setting(settings, 'from_email', 'default_sender', 'from_addr', 'sender')
        signature = get_setting(settings, 'signature', 'sig', default="")
        use_tls = get_setting(settings, 'use_tls', 'tls', default=False)

        # Debug/log current resolved settings (avoid printing passwords in real logs)
        print("SMTP resolved:", {
            "smtp_server": smtp_server,
            "smtp_port": smtp_port,
            "smtp_username": smtp_username,
            "from_email": from_email,
            "use_tls": use_tls,
        })

        # Normalize values to avoid None.encode issues
        subject = subject or ""
        recipient = recipient or ""
        body = body or ""
        from_email = from_email or ""
        signature = signature or ""

        full_body = body
        if signature:
            full_body += f"<br><br>{signature}"

        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(full_body or "", 'html'))

        # Validate minimal SMTP info
        if not smtp_server or not smtp_port:
            print("SMTP server or port not configured properly.")
            return False

        try:
            server = smtplib.SMTP(smtp_server, int(smtp_port), timeout=10)
            if use_tls:
                server.starttls()
            if smtp_username:
                server.login(smtp_username, smtp_password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            print(f"Failed to send email to {recipient}: {e}")
            return False


def process_pending_emails(app):
    with app.app_context():
        try:
            now = datetime.now()
            pending_emails = Email.query.filter(
                Email.status == 'pending',
                Email.scheduled_time <= now
            ).all()

            for email in pending_emails:
                print(f"Sending email {email.id} to {email.recipient}...")
                success = send_email(email.subject, email.recipient, email.body)
                email.status = 'sent' if success else 'failed'
                db.session.commit()

        except Exception as e:
            print(f"Error in scheduler: {e}")
        finally:
            db.session.remove()


def start_scheduler(app):
    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(1)

    schedule.every(10).seconds.do(process_pending_emails, app=app)

    scheduler_thread = threading.Thread(target=run_schedule)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    print("Scheduler started...")
