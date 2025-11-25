import smtplib
import time
from celery import shared_task
from app import db
from app.models import Email, SMTPSettings
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from collections import defaultdict

# --- Helper Functions ---
def get_setting(obj, *names, default=None):
    for n in names:
        if hasattr(obj, n): return getattr(obj, n)
    return default

def create_smtp_connection(settings):
    try:
        server = smtplib.SMTP(
            settings.server,
            settings.port,
            timeout=10
        )
        if settings.use_tls:
            server.starttls()

        if settings.username and settings.password:
            server.login(settings.username, settings.password)
        return server
    except Exception as e:
        print(f"SMTP Connection Error: {e}")
        return None

# --- WORKER TASK: Sends a specific batch (User Context Aware) ---
@shared_task(bind=True, max_retries=3)
def send_batch_task(self, email_ids):
    print(f"\n{'='*60}")
    print(f"📨 BATCH TASK STARTED - Processing {len(email_ids)} emails")

    # 1. Fetch Emails
    emails = Email.query.filter(Email.id.in_(email_ids)).all()
    if not emails:
        print("❌ ERROR: No emails found.")
        return "No Emails"

    # 2. Identify User Owner
    # We assume the dispatcher grouped these correctly by user
    first_email = emails[0]
    if not first_email.campaign or not first_email.campaign.owner:
        print("❌ ERROR: Email not linked to a user campaign.")
        return "Orphan Email"

    user = first_email.campaign.owner
    print(f"👤 Processing batch for User: {user.username} ({user.email})")

    # 3. Fetch User's SMTP Settings
    settings = SMTPSettings.query.filter_by(user_id=user.id).first()
    if not settings:
        print(f"❌ ERROR: User {user.username} has no SMTP settings.")
        # Mark these emails as failed so they don't loop forever
        for e in emails:
            e.status = 'failed'
        db.session.commit()
        return "No SMTP Settings"

    # 4. Open Connection
    print(f"🔌 Connecting to {settings.server}...")
    server = create_smtp_connection(settings)
    if not server:
        print("❌ SMTP Connection FAILED! Retrying...")
        try:
            self.retry(countdown=60)
        except Exception as e:
            # If max retries exceeded, mark emails as failed instead of crashing
            print(f"⚠ Max retries exceeded for batch. Marking {len(emails)} emails as failed.")
            for e in emails:
                e.status = 'failed'
            db.session.commit()
            return f"Failed after max retries - marked {len(emails)} emails as failed"

    sent_count = 0
    failed_count = 0

    try:
        from_email = settings.default_sender
        signature = settings.signature or ""

        for email in emails:
            try:
                msg = MIMEMultipart()
                msg['From'] = from_email
                msg['To'] = email.recipient
                msg['Subject'] = email.subject

                body = email.body
                if signature: body += f"<br><br>{signature}"
                msg.attach(MIMEText(body, 'html'))

                server.send_message(msg)
                email.status = 'sent'
                sent_count += 1
                time.sleep(0.5) # Politeness delay

            except Exception as e:
                failed_count += 1
                print(f"  ❌ Failed {email.recipient}: {e}")
                email.status = 'failed'

        db.session.commit()

    finally:
        try:
            server.quit()
        except:
            pass

    return f"User {user.username}: {sent_count} sent, {failed_count} failed."

# --- DISPATCHER TASK ---
@shared_task
def scheduler_dispatcher():
    print("=" * 80)
    print("🔍 SCHEDULER DISPATCHER RUNNING")

    now = datetime.now()

    # 1. Find all pending emails
    pending_emails = Email.query.filter(
        Email.status == 'pending',
        Email.scheduled_time <= now
    ).limit(2000).all() 

    if not pending_emails:
        print("✓ No pending emails.")
        return "Idle"

    # 2. Group by User ID
    # We must ensure we don't mix emails from User A and User B in one batch
    # because they need different SMTP connections.
    user_batches = defaultdict(list)

    for email in pending_emails:
        if email.campaign and email.campaign.owner:
            uid = email.campaign.owner.id
            user_batches[uid].append(email.id)
        else:
            # Handle orphan emails (no owner)
            print(f"⚠ Email {email.id} has no owner/campaign. Skipping.")

    # 3. Dispatch batches per user
    total_batches = 0

    for uid, ids in user_batches.items():
        batch_size = 50
        for i in range(0, len(ids), batch_size):
            chunk = ids[i:i + batch_size]
            print(f"📦 Dispatching batch of {len(chunk)} emails for User ID {uid}")
            send_batch_task.delay(chunk)
            total_batches += 1

    return f"Dispatched {total_batches} batches."