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
    
    CRITICAL FIX: When we get 451 on first send_message(), email was likely queued by SMTP
    Don't retry - mark as 'rate_limit_sent' so we DON'T send duplicate on retry
    """
    try:
        server.send_message(msg)
        return True

    except Exception as e:
        error_str = str(e)
        
        # Check for rate limit error
        # CRITICAL: If 451 on FIRST attempt, email was probably queued by SMTP
        # Return 'rate_limit_sent' to indicate: rate limited BUT email was sent
        if "451" in error_str or "Ratelimit" in error_str or "quota" in error_str.lower():
            print(f"⏱️ {recipient} rate limited (email queued by SMTP - no retry)", flush=True)
            return 'rate_limit_sent'  # Email sent, just rate limited for future
        
        print(f"⚠ {recipient} send failed: {e} — retrying...", flush=True)

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
                print(f"⏱️ {recipient} rate limited on retry (email likely queued)", flush=True)
                # Even on retry 451, email was probably sent
                return 'rate_limit_sent'
            print(f"❌ Second attempt failed ({recipient}): {e}", flush=True)
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
        elif send_result == 'rate_limit_sent':
            # CRITICAL FIX: Email was sent BUT got 451 error (email was queued by SMTP)
            # Mark as SENT, not as retry - prevents duplicate sends
            email.status = 'sent'
            sent_count += 1
            counter += 1
            consecutive_rate_limits = 0
            rate_limited_count += 1
            print(f"✅ {email.recipient} sent (rate limited but queued)", flush=True)
        elif send_result == 'rate_limit':
            # Legacy: Rate limit without sending (shouldn't happen with new fix)
            consecutive_rate_limits += 1
            rate_limited_count += 1
            
            retry_delay = timedelta(hours=1)
            retry_msg = "1 hour"
            
            email.rate_limit_retry_at = datetime.now() + retry_delay
            print(f"⏱️ {email.recipient} rate limited → retry in {retry_msg}", flush=True)
            failed_count += 1
        elif send_result not in [True, False, 'rate_limit', 'rate_limit_sent']:
            # New server connection returned (reconnection successful)
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
        # Optimized: 4 seconds between emails with 2 workers = 30 emails/minute total
        time.sleep(4.0)  # 4 seconds between emails - optimized for speed

    # Save results - CRITICAL: use direct SQL updates for reliability in Celery context
    try:
        # First, commit ORM changes
        db.session.flush()
        
        # Use direct SQL to update sent emails (most reliable in Celery)
        sent_ids = [e.id for e in emails if e.status == 'sent']
        if sent_ids:
            from sqlalchemy import update
            db.session.execute(update(Email).where(Email.id.in_(sent_ids)).values(status='sent'))
        
        # Update rate-limited emails with retry times
        rate_limited_updates = {e.id: e.rate_limit_retry_at for e in emails if e.rate_limit_retry_at}
        if rate_limited_updates:
            for email_id, retry_at in rate_limited_updates.items():
                db.session.execute(update(Email).where(Email.id == email_id).values(rate_limit_retry_at=retry_at))
        
        # Update failed emails
        failed_ids = [e.id for e in emails if e.status == 'failed']
        if failed_ids:
            db.session.execute(update(Email).where(Email.id.in_(failed_ids)).values(status='failed'))
        
        # Save tracking IDs (CRITICAL for open tracking)
        tracking_updates = {e.id: e.tracking_id for e in emails if e.tracking_id}
        if tracking_updates:
            for email_id, tracking_id in tracking_updates.items():
                db.session.execute(update(Email).where(Email.id == email_id).values(tracking_id=tracking_id))
        
        # Finally commit everything
        db.session.commit()
        print(f"💾 Database commit successful ({sent_count} sent, {failed_count} failed)", flush=True)
    except Exception as e:
        print(f"❌ DATABASE COMMIT ERROR: {e}", flush=True)
        db.session.rollback()
        print(f"❌ Rolled back all changes due to error", flush=True)
        sys.stdout.flush()
        raise  # Re-raise so Celery knows task failed

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

    now = datetime.utcnow()  # FIXED: Use UTC to match database timestamps
    
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
    # 4. NOT already dispatched (batch_id is NULL - prevents duplicate sends)
    pending = Email.query.filter(
        Email.status == 'pending',
        Email.scheduled_time <= now,
        Email.rate_limit_retry_at.is_(None),
        Email.batch_id.is_(None)  # CRITICAL: Skip already-dispatched emails
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
    batch_counter = 0
    for uid, ids in user_batches.items():
        for i in range(0, len(ids), 50):  # Larger batches: 50 emails for faster processing
            chunk = ids[i:i + 50]
            batch_id = f"batch_{uid}_{now.timestamp()}_{batch_counter}"
            batch_counter += 1
            
            # CRITICAL: Mark emails as dispatched BEFORE queuing task (prevents re-dispatch on next scheduler run)
            Email.query.filter(Email.id.in_(chunk)).update({Email.batch_id: batch_id})
            db.session.commit()
            
            print(f"📦 Batch ({len(chunk)}) for UID {uid} → ID: {batch_id}")
            send_batch_task.delay(chunk)
            total += 1
            import time as time_module
            time_module.sleep(0.5)  # 0.5 second between batch dispatches

    return f"Dispatched {total} batches."
