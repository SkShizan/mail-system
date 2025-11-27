import smtplib
import time
import sys
from celery import shared_task
from app import db
from app.models import Email, SMTPSettings
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from collections import defaultdict
import uuid
import os

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
    rate_limited_count = 0
    consecutive_rate_limits = 0  # Track consecutive rate limit hits
    from_email = settings.default_sender
    signature = settings.signature or ""

    # Keep SMTP alive limit - refresh less frequently to avoid auth storms
    REFRESH_RATE = 500  # Only refresh after 500 emails to minimize reconnections
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

        # Generate tracking ID if not exists
        if not email.tracking_id:
            email.tracking_id = str(uuid.uuid4())
        
        # Build email with tracking pixel
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = email.recipient
        msg['Subject'] = email.subject

        tracking_pixel = f"<img src='{os.getenv('DOMAIN', 'http://localhost:5000')}/track/{email.tracking_id}' width='1' height='1' style='display:none;' />"
        body_content = (email.body or "") + tracking_pixel + (f"<br><br>{signature}" if signature else "")
        msg.attach(MIMEText(body_content, 'html'))

        # Send safely
        send_result = safe_send(server, msg, email.recipient, settings)

        if send_result is True:
            email.status = 'sent'
            sent_count += 1
            counter += 1
            consecutive_rate_limits = 0  # Reset counter on successful send
            print(f"✅ {email.recipient} sent", flush=True)
        elif send_result == 'rate_limit':
            # Rate limit hit - detect type and set intelligent retry
            consecutive_rate_limits += 1
            rate_limited_count += 1
            
            # Smart retry logic based on consecutive failures
            if consecutive_rate_limits <= 2:
                # 1-2 failures = likely per-second limit
                retry_delay = timedelta(seconds=30)
                retry_msg = "30 seconds"
            elif consecutive_rate_limits <= 5:
                # 3-5 failures = likely per-minute limit
                retry_delay = timedelta(minutes=1)
                retry_msg = "1 minute"
            else:
                # 6+ failures = likely per-hour limit
                retry_delay = timedelta(hours=1)
                retry_msg = "1 hour"
            
            email.rate_limit_retry_at = datetime.now() + retry_delay
            print(f"⏱️ {email.recipient} rate limited → retry in {retry_msg}", flush=True)
            failed_count += 1
        elif send_result not in [True, False, 'rate_limit']:
            # New server connection returned
            server = send_result
            email.status = 'sent'
            sent_count += 1
            counter += 1
            consecutive_rate_limits = 0  # Reset counter on successful send
            print(f"✅ {email.recipient} sent (reconnected)", flush=True)
        else:
            # Other errors - mark as failed (not rate limit related)
            email.status = 'failed'
            failed_count += 1
            consecutive_rate_limits = 0  # Reset counter on other errors
            print(f"❌ {email.recipient} failed", flush=True)

        # Delay per provider rules (respect SMTP rate limits)
        # Hostinger: Per-minute throttling + per-second limits
        # Conservative: 10 seconds between emails with 2 workers = 12 emails/minute total
        time.sleep(10.0)  # 10 seconds between emails - safe for all providers

    # Save results
    db.session.commit()

    # Close connection
    try:
        server.quit()
    except:
        pass

    rate_limit_pct = (rate_limited_count / len(emails) * 100) if emails else 0
    print(f"🧾 RESULT: {sent_count} sent | {failed_count} failed ({rate_limited_count} rate limited)", flush=True)
    print(f"📊 Rate limit: {rate_limit_pct:.0f}% of batch", flush=True)
    sys.stdout.flush()
    return f"{sent_count} sent | {failed_count} failed"


# ---------------------------
# Dispatcher
# ---------------------------
@shared_task
def scheduler_dispatcher():
    print("\n" + "="*80)
    print("🔍 Scheduler Running...")

    now = datetime.now()
    
    # Clean up expired rate limit retries (reset them so they can be retried)
    expired_retries = Email.query.filter(
        Email.status == 'pending',
        Email.rate_limit_retry_at.isnot(None),
        Email.rate_limit_retry_at <= now
    ).count()
    if expired_retries > 0:
        Email.query.filter(
            Email.status == 'pending',
            Email.rate_limit_retry_at.isnot(None),
            Email.rate_limit_retry_at <= now
        ).update({Email.rate_limit_retry_at: None})
        db.session.commit()
        print(f"🔧 Cleared {expired_retries} expired rate limit retries - retrying now!")

    # Find emails that are:
    # 1. Pending (status='pending')
    # 2. Scheduled time passed
    # 3. NOT in rate limit retry wait (rate_limit_retry_at is NULL or has passed)
    pending = Email.query.filter(
        Email.status == 'pending',
        Email.scheduled_time <= now,
        Email.rate_limit_retry_at.is_(None)
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
        for i in range(0, len(ids), 50):  # Larger batches: 50 emails for faster processing
            chunk = ids[i:i + 50]
            print(f"📦 Batch ({len(chunk)}) for UID {uid}")
            send_batch_task.delay(chunk)
            total += 1
            import time as time_module
            time_module.sleep(0.5)  # 0.5 second between batch dispatches

    return f"Dispatched {total} batches."
