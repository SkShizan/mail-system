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
    print(f"\n{'='*60}")
    print(f"📨 BATCH TASK STARTED - Processing {len(email_ids)} emails")
    print(f"{'='*60}")
    
    # 1. Fetch settings & emails
    settings = SMTPSettings.query.first()
    if not settings:
        print("❌ ERROR: No SMTP settings configured!")
        return "No Settings"
    
    print(f"✓ SMTP Settings loaded:")
    print(f"  Server: {get_setting(settings, 'smtp_server', 'server', 'host')}")
    print(f"  Port: {get_setting(settings, 'smtp_port', 'port')}")
    print(f"  Username: {get_setting(settings, 'smtp_username', 'username')}")
    print(f"  From: {get_setting(settings, 'from_email', 'default_sender')}")

    emails = Email.query.filter(Email.id.in_(email_ids)).all()
    if not emails:
        print("❌ ERROR: No emails found with provided IDs!")
        return "No Emails Found"
    
    print(f"✓ Loaded {len(emails)} emails from database")

    # 2. Open Connection (ONCE per batch)
    print("🔌 Attempting SMTP connection...")
    server = create_smtp_connection(settings)
    if not server:
        print("❌ SMTP Connection FAILED! Will retry in 60 seconds...")
        # Retry the whole batch later if connection fails
        self.retry(countdown=60)

    print("✓ SMTP Connection established successfully!")
    
    sent_count = 0
    failed_count = 0
    try:
        from_email = get_setting(settings, 'from_email', 'default_sender')
        signature = get_setting(settings, 'signature', 'sig', default="")

        for email in emails:
            try:
                print(f"\n  📧 Sending email #{email.id} to {email.recipient}...")
                
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
                print(f"  ✓ Email #{email.id} sent successfully!")

                # Tiny throttle to be nice to the server inside the open connection
                time.sleep(0.5) 

            except Exception as e:
                failed_count += 1
                print(f"  ❌ Failed to send email #{email.id} to {email.recipient}: {e}")
                email.status = 'failed'

        db.session.commit()
        print(f"\n✓ Database updated with results")

    finally:
        try:
            server.quit()
            print("✓ SMTP connection closed")
        except Exception as e:
            print(f"⚠ Error closing SMTP connection: {e}")

    result = f"Batch complete: {sent_count} sent, {failed_count} failed out of {len(emails)}"
    print(f"\n{'='*60}")
    print(f"📊 BATCH TASK COMPLETE: {result}")
    print(f"{'='*60}\n")
    return result

# --- MANAGER TASK: Finds work to do ---
@shared_task
def scheduler_dispatcher():
    print("=" * 80)
    print("🔍 SCHEDULER DISPATCHER RUNNING")
    print("=" * 80)
    
    # Find pending emails due for sending
    now = datetime.now()
    print(f"⏰ Current time (UTC): {now}")
    
    pending_emails = Email.query.filter(
        Email.status == 'pending',
        Email.scheduled_time <= now
    ).limit(1000).all() # Grab up to 1000 at a time

    print(f"📧 Found {len(pending_emails)} pending emails to send")
    
    if not pending_emails:
        print("✓ No pending emails to send at this time")
        return "No pending emails."
    
    # Show first few emails for debugging
    for email in pending_emails[:5]:
        print(f"  - ID {email.id}: {email.recipient}, scheduled for {email.scheduled_time}")

    # Group into batches of 50 to distribute load
    batch_size = 50
    email_ids = [e.id for e in pending_emails]

    # Chunk the list
    batch_count = 0
    for i in range(0, len(email_ids), batch_size):
        batch_ids = email_ids[i:i + batch_size]
        batch_count += 1
        print(f"📦 Dispatching batch {batch_count} with {len(batch_ids)} emails")
        # Dispatch to workers
        send_batch_task.delay(batch_ids)

    result = f"✓ Dispatched {len(email_ids)} emails in {batch_count} batches"
    print(result)
    print("=" * 80)
    return result