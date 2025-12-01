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

# [NEW] Imports for Click Tracking
from bs4 import BeautifulSoup
from urllib.parse import quote

# ---------------------------
# Helper Functions
# ---------------------------

# [NEW] Function to rewrite links for tracking
def rewrite_links(html_body, tracking_id, domain):
    """
    Parses HTML, finds links marked with data-track="true",
    and replaces them with the tracking redirector.
    """
    if not html_body:
        return html_body

    try:
        soup = BeautifulSoup(html_body, 'html.parser')
        modified = False

        # Find only links explicitly marked by the user in the frontend
        for a_tag in soup.find_all('a', attrs={'data-track': 'true'}):
            original_url = a_tag.get('href')
            if original_url:
                # Construct the tracking URL
                # Format: domain/click/<tracking_id>?url=<encoded_original_url>
                safe_target = quote(original_url)
                tracking_url = f"{domain}/click/{tracking_id}?url={safe_target}"

                # Replace href with tracking URL
                a_tag['href'] = tracking_url

                # Clean up the marker attribute so it doesn't appear in the final email
                del a_tag['data-track']
                modified = True

        return str(soup) if modified else html_body
    except Exception as e:
        print(f"⚠ Error rewriting links: {e}")
        return html_body

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
    """
    try:
        server.send_message(msg)
        return True

    except Exception as e:
        error_str = str(e)

        # Check for rate limit error
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
    consecutive_rate_limits = 0 
    from_email = settings.default_sender
    signature = settings.signature or ""

    # Get domain for tracking links
    domain = os.getenv('DOMAIN', 'http://localhost:5000')

    REFRESH_RATE = 500
    counter = 0

    for email in emails:

        # Periodically refresh connection
        if counter >= REFRESH_RATE:
            print("🔄 Refresh SMTP connection (safety refresh)")
            try:
                server.quit()
            except:
                pass
            import time as time_module
            time_module.sleep(2.0)
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
            time_module.sleep(0.5)

        # Generate tracking ID if not exists
        if not email.tracking_id:
            email.tracking_id = str(uuid.uuid4())

        # [NEW] Process Body to Rewrite Links
        # We pass the raw body (which has data-track="true" tags) to the rewriter
        processed_body = rewrite_links(email.body, email.tracking_id, domain)

        # Build email with tracking pixel
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = email.recipient
        msg['Subject'] = email.subject

        tracking_pixel = f"<img src='{domain}/track/{email.tracking_id}' width='1' height='1' style='display:none;' />"

        # Use processed_body instead of email.body
        body_content = (processed_body or "") + tracking_pixel + (f"<br><br>{signature}" if signature else "")
        msg.attach(MIMEText(body_content, 'html'))

        # Send safely
        send_result = safe_send(server, msg, email.recipient, settings)

        if send_result is True:
            email.status = 'sent'
            sent_count += 1
            counter += 1
            consecutive_rate_limits = 0
            print(f"✅ {email.recipient} sent", flush=True)
        elif send_result == 'rate_limit_sent':
            email.status = 'sent'
            sent_count += 1
            counter += 1
            consecutive_rate_limits = 0
            rate_limited_count += 1
            print(f"✅ {email.recipient} sent (rate limited but queued)", flush=True)
        elif send_result == 'rate_limit':
            consecutive_rate_limits += 1
            rate_limited_count += 1
            retry_delay = timedelta(hours=1)
            email.rate_limit_retry_at = datetime.now() + retry_delay
            print(f"⏱️ {email.recipient} rate limited → retry in 1 hour", flush=True)
            failed_count += 1
        elif send_result not in [True, False, 'rate_limit', 'rate_limit_sent']:
            server = send_result
            email.status = 'sent'
            sent_count += 1
            counter += 1
            consecutive_rate_limits = 0
            print(f"✅ {email.recipient} sent (reconnected)", flush=True)
        else:
            email.status = 'failed'
            failed_count += 1
            consecutive_rate_limits = 0
            print(f"❌ {email.recipient} failed", flush=True)

        time.sleep(4.0)

    # Save results
    try:
        db.session.flush()

        sent_ids = [e.id for e in emails if e.status == 'sent']
        if sent_ids:
            from sqlalchemy import update
            db.session.execute(update(Email).where(Email.id.in_(sent_ids)).values(status='sent'))

        rate_limited_updates = {e.id: e.rate_limit_retry_at for e in emails if e.rate_limit_retry_at}
        if rate_limited_updates:
            for email_id, retry_at in rate_limited_updates.items():
                db.session.execute(update(Email).where(Email.id == email_id).values(rate_limit_retry_at=retry_at))

        failed_ids = [e.id for e in emails if e.status == 'failed']
        if failed_ids:
            db.session.execute(update(Email).where(Email.id.in_(failed_ids)).values(status='failed'))

        tracking_updates = {e.id: e.tracking_id for e in emails if e.tracking_id}
        if tracking_updates:
            for email_id, tracking_id in tracking_updates.items():
                db.session.execute(update(Email).where(Email.id == email_id).values(tracking_id=tracking_id))

        db.session.commit()
        print(f"💾 Database commit successful ({sent_count} sent, {failed_count} failed)", flush=True)
    except Exception as e:
        print(f"❌ DATABASE COMMIT ERROR: {e}", flush=True)
        db.session.rollback()
        sys.stdout.flush()
        raise

    try:
        server.quit()
    except:
        pass

    return f"{sent_count} sent | {failed_count} failed"


# ---------------------------
# Dispatcher (Unchanged)
# ---------------------------
@shared_task
def scheduler_dispatcher():
    # ... (Keep the rest of your dispatcher code exactly as it was) ...
    # It was correct in your snippet, no changes needed there.
    print("\n" + "="*80)
    print("🔍 Scheduler Running...")

    now = datetime.utcnow()

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

    pending = Email.query.filter(
        Email.status == 'pending',
        Email.scheduled_time <= now,
        Email.rate_limit_retry_at.is_(None),
        Email.batch_id.is_(None)
    ).limit(2000).all()

    if not pending:
        print("✓ No pending emails ready to send.")
        return "Idle"

    user_batches = defaultdict(list)

    for email in pending:
        if email.campaign and email.campaign.owner:
            user_batches[email.campaign.owner.id].append(email.id)

    total = 0
    batch_counter = 0
    for uid, ids in user_batches.items():
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            batch_id = f"batch_{uid}_{now.timestamp()}_{batch_counter}"
            batch_counter += 1

            Email.query.filter(Email.id.in_(chunk)).update({Email.batch_id: batch_id})
            db.session.commit()

            print(f"📦 Batch ({len(chunk)}) for UID {uid} → ID: {batch_id}")
            send_batch_task.delay(chunk)
            total += 1
            import time as time_module
            time_module.sleep(0.5)

    return f"Dispatched {total} batches."