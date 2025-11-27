import smtplib
import time
from celery import shared_task
from app import db
from app.models import Email, SMTPSettings
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from collections import defaultdict

# ---------------------------
# Helper Functions
# ---------------------------
def create_smtp_connection(settings):
    """Create and return a fresh SMTP connection."""
    try:
        server = smtplib.SMTP(settings.server, settings.port, timeout=30)
        server.ehlo()

        if settings.use_tls:
            server.starttls()
            server.ehlo()

        if settings.username and settings.password:
            server.login(settings.username, settings.password)

        print(f"✅ SMTP CONNECTED: {settings.server}:{settings.port}")
        return server

    except Exception as e:
        print(f"❌ SMTP Connection Error: {e}")
        return None


def safe_send(server, msg, recipient, settings, retry=1):
    """
    Try sending an email. If connection dies, reconnect and retry once.
    Returns True if sent, False otherwise.
    """
    try:
        server.send_message(msg)
        return True

    except Exception as e:
        print(f"⚠ {recipient} send failed: {e} — retrying...")

        # Close broken connection
        try:
            server.quit()
        except:
            pass

        # Reconnect
        new_server = create_smtp_connection(settings)
        if not new_server:
            return False

        try:
            new_server.send_message(msg)
            return new_server  # return the new live connection
        except Exception as e:
            print(f"❌ Second attempt failed ({recipient}): {e}")
            return False


# ---------------------------
# Batch Worker Task
# ---------------------------
@shared_task(bind=True, max_retries=3)
def send_batch_task(self, email_ids):
    print("\n" + "="*60)
    print(f"📨 SEND BATCH: {len(email_ids)} emails")

    emails = Email.query.filter(Email.id.in_(email_ids)).all()
    if not emails:
        return "No emails found"

    # Identify owner
    user = emails[0].campaign.owner if emails[0].campaign else None
    if not user:
        print("❌ Missing user context")
        return "Invalid batch"

    print(f"👤 User: {user.username} ({user.email})")

    # Fetch SMTP settings
    settings = SMTPSettings.query.filter_by(user_id=user.id).first()
    if not settings:
        print("❌ No SMTP settings found")
        for e in emails:
            e.status = "failed"
        db.session.commit()
        return "Missing SMTP settings"

    # Open initial connection
    server = create_smtp_connection(settings)
    if not server:
        print("❌ SMTP failed — retrying whole task")
        return self.retry(countdown=60)

    sent_count = 0
    failed_count = 0
    from_email = settings.default_sender
    signature = settings.signature or ""

    # Keep SMTP alive limit
    REFRESH_RATE = 10  
    counter = 0

    for email in emails:

        # Periodically refresh connection
        if counter >= REFRESH_RATE:
            print("🔄 Refresh SMTP connection (safety refresh)")
            try:
                server.quit()
            except:
                pass
            server = create_smtp_connection(settings)
            counter = 0

        # Ensure connection exists
        if not server:
            print("⚠️ Reconnecting due to lost session...")
            server = create_smtp_connection(settings)
            if not server:
                email.status = 'failed'
                failed_count += 1
                continue

        # Build email
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = email.recipient
        msg['Subject'] = email.subject

        body_content = (email.body or "") + (f"<br><br>{signature}" if signature else "")
        msg.attach(MIMEText(body_content, 'html'))

        # Send safely
        send_result = safe_send(server, msg, email.recipient, settings)

        if send_result is True or send_result:
            email.status = 'sent'
            sent_count += 1
            counter += 1

            # Replace server if safe_send returned a new one (means reconnection happened)
            if send_result not in [True, False]:
                server = send_result  

        else:
            email.status = 'failed'
            failed_count += 1

        # Delay per provider rules
        time.sleep(0.5)

    # Save results
    db.session.commit()

    # Close connection
    try:
        server.quit()
    except:
        pass

    print(f"🧾 RESULT: {sent_count} sent | {failed_count} failed")
    return f"{sent_count} sent | {failed_count} failed"


# ---------------------------
# Dispatcher
# ---------------------------
@shared_task
def scheduler_dispatcher():
    print("\n" + "="*80)
    print("🔍 Scheduler Running...")

    now = datetime.now()

    pending = Email.query.filter(
        Email.status == 'pending',
        Email.scheduled_time <= now
    ).limit(2000).all()

    if not pending:
        print("✓ No pending emails.")
        return "Idle"

    user_batches = defaultdict(list)

    for email in pending:
        if email.campaign and email.campaign.owner:
            user_batches[email.campaign.owner.id].append(email.id)

    total = 0
    for uid, ids in user_batches.items():
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            print(f"📦 Batch ({len(chunk)}) for UID {uid}")
            send_batch_task.delay(chunk)
            total += 1

    return f"Dispatched {total} batches."
