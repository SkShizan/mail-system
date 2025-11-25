import smtplib
import time
from celery import shared_task
from app import db
from app.models import Email, SMTPSettings
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# --- Helper Functions ---
def get_setting(obj, *names, default=None):
    for n in names:
        if hasattr(obj, n): return getattr(obj, n)
    return default

def create_smtp_connection(settings):
    try:
        server = smtplib.SMTP(
            get_setting(settings, 'smtp_server', 'server', 'host'),
            int(get_setting(settings, 'smtp_port', 'port')),
            timeout=10
        )
        if get_setting(settings, 'use_tls', 'tls', default=False):
            server.starttls()

        user = get_setting(settings, 'smtp_username', 'username')
        pw = get_setting(settings, 'smtp_password', 'password')
        if user and pw:
            server.login(user, pw)
        return server
    except Exception as e:
        print(f"SMTP Connection Error: {e}")
        return None

# --- WORKER TASK: Sends a specific batch of emails ---
@shared_task(bind=True, max_retries=3)
def send_batch_task(self, email_ids):
    # 1. Fetch settings & emails
    settings = SMTPSettings.query.first()
    if not settings: return "No Settings"

    emails = Email.query.filter(Email.id.in_(email_ids)).all()
    if not emails: return "No Emails Found"

    # 2. Open Connection (ONCE per batch)
    server = create_smtp_connection(settings)
    if not server:
        # Retry the whole batch later if connection fails
        self.retry(countdown=60)

    sent_count = 0
    try:
        from_email = get_setting(settings, 'from_email', 'default_sender')
        signature = get_setting(settings, 'signature', 'sig', default="")

        for email in emails:
            try:
                # Construct email
                msg = MIMEMultipart()
                msg['From'] = from_email
                msg['To'] = email.recipient
                msg['Subject'] = email.subject

                body = email.body
                if signature: body += f"<br><br>{signature}"
                msg.attach(MIMEText(body, 'html'))

                # Send
                server.send_message(msg)

                email.status = 'sent'
                sent_count += 1

                # Tiny throttle to be nice to the server inside the open connection
                time.sleep(0.5) 

            except Exception as e:
                print(f"Failed single email {email.recipient}: {e}")
                email.status = 'failed'

        db.session.commit()

    finally:
        try: server.quit()
        except: pass

    return f"Batch complete. Sent {sent_count}/{len(emails)}"

# --- MANAGER TASK: Finds work to do ---
@shared_task
def scheduler_dispatcher():
    # Find pending emails due for sending
    now = datetime.now()
    pending_emails = Email.query.filter(
        Email.status == 'pending',
        Email.scheduled_time <= now
    ).limit(1000).all() # Grab up to 1000 at a time

    if not pending_emails:
        return "No pending emails."

    # Group into batches of 50 to distribute load
    batch_size = 50
    email_ids = [e.id for e in pending_emails]

    # Chunk the list
    for i in range(0, len(email_ids), batch_size):
        batch_ids = email_ids[i:i + batch_size]
        # Dispatch to workers
        send_batch_task.delay(batch_ids)

    return f"Dispatched {len(email_ids)} emails."