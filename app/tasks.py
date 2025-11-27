import smtplib
import time
from celery import shared_task
from app import db
from app.models import Email, SMTPSettings
from datetime import datetime, timedelta
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
    Returns: True if sent, False if other error, 'rate_limit' if 451 error
    Rate limit errors need smart retry (wait 1 hour), not immediate retry.
    """
    try:
        server.send_message(msg)
        return True

    except Exception as e:
        error_str = str(e)
        
        # Check for rate limit error - return special indicator for hourly retry
        if "451" in error_str or "Ratelimit" in error_str or "quota" in error_str.lower():
            print(f"⏱️ {recipient} rate limited — will retry after 1 hour")
            return 'rate_limit'
        
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
            error_str2 = str(e)
            if "451" in error_str2 or "Ratelimit" in error_str2 or "quota" in error_str2.lower():
                print(f"⏱️ {recipient} rate limited on retry — will retry after 1 hour")
                return 'rate_limit'
            print(f"❌ Second attempt failed ({recipient}): {e}")
            return False


# ---------------------------
# Batch Worker Task
# ---------------------------
@shared_task(bind=True, max_retries=0)
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
    
    # Small wait after connection to let server stabilize
    import time as time_module
    time_module.sleep(0.5)

    sent_count = 0
    failed_count = 0
    from_email = settings.default_sender
    signature = settings.signature or ""

    # Keep SMTP alive limit - refresh less frequently to avoid auth storms
    REFRESH_RATE = 200  # Only refresh after 200 emails to minimize reconnections
    counter = 0

    for email in emails:

        # Periodically refresh connection (very rarely to avoid rate limiting)
        if counter >= REFRESH_RATE:
            print("🔄 Refresh SMTP connection (safety refresh)")
            try:
                server.quit()
            except:
                pass
            import time as time_module
            time_module.sleep(2.0)  # Wait before reconnecting
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
            import time as time_module
            time_module.sleep(0.5)  # Wait after reconnection

        # Build email
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = email.recipient
        msg['Subject'] = email.subject

        body_content = (email.body or "") + (f"<br><br>{signature}" if signature else "")
        msg.attach(MIMEText(body_content, 'html'))

        # Send safely
        send_result = safe_send(server, msg, email.recipient, settings)

        if send_result is True:
            email.status = 'sent'
            sent_count += 1
            counter += 1
        elif send_result == 'rate_limit':
            # Rate limit hit - set retry time to 1 hour from now, keep status as pending
            email.rate_limit_retry_at = datetime.now() + timedelta(hours=1)
            print(f"⏱️ {email.recipient} will retry at {email.rate_limit_retry_at}")
            failed_count += 1
        elif send_result not in [True, False, 'rate_limit']:
            # New server connection returned
            server = send_result
            email.status = 'sent'
            sent_count += 1
            counter += 1
        else:
            # Other errors - mark as failed
            email.status = 'failed'
            failed_count += 1

        # Delay per provider rules (respect SMTP rate limits)
        time.sleep(15.0)  # 15 seconds between emails - very conservative for low rate limit accounts

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

    # Find emails that are:
    # 1. Pending (status='pending')
    # 2. Scheduled time passed
    # 3. NOT in rate limit retry wait (rate_limit_retry_at is NULL or has passed)
    pending = Email.query.filter(
        Email.status == 'pending',
        Email.scheduled_time <= now,
        (Email.rate_limit_retry_at.is_(None) | (Email.rate_limit_retry_at <= now))
    ).limit(2000).all()

    if not pending:
        print("✓ No pending emails ready to send.")
        
        # Show how many are waiting for rate limit reset
        rate_limited = Email.query.filter(
            Email.status == 'pending',
            Email.rate_limit_retry_at.isnot(None),
            Email.rate_limit_retry_at > now
        ).count()
        if rate_limited > 0:
            print(f"⏱️ {rate_limited} emails waiting for rate limit reset...")
        
        return "Idle"

    user_batches = defaultdict(list)

    for email in pending:
        if email.campaign and email.campaign.owner:
            user_batches[email.campaign.owner.id].append(email.id)

    total = 0
    for uid, ids in user_batches.items():
        for i in range(0, len(ids), 20):  # Smaller batches: 20 emails instead of 50
            chunk = ids[i:i + 20]
            print(f"📦 Batch ({len(chunk)}) for UID {uid}")
            send_batch_task.delay(chunk)
            total += 1
            import time as time_module
            time_module.sleep(1)  # 1 second between batch dispatches

    return f"Dispatched {total} batches."
