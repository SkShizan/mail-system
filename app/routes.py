from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from app import db
from app.models import Email, SMTPSettings, Campaign
from datetime import datetime, timedelta
import uuid
import pytz

user_tz = pytz.timezone("Asia/Kolkata")   # or detect automatically
utc = pytz.UTC

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    stats = {
        'sent': Email.query.filter_by(status='sent').count(),
        'pending': Email.query.filter_by(status='pending').count(),
        'failed': Email.query.filter_by(status='failed').count()
    }
    return render_template('dashboard.html', stats=stats)



@bp.route('/compose', methods=['GET', 'POST'])
def compose():
    if request.method == 'POST':
        campaign_name = request.form.get('campaign_name')
        recipients_str = request.form.get('recipients')
        subject_template = request.form.get('subject') or ""
        body_template = request.form.get('body') or ""
        scheduled_time_str = request.form.get('scheduled_time')
        file = request.files.get('file')

        if not campaign_name or not subject_template or not body_template:
            flash('Campaign Name, Subject, and Body are required', 'danger')
            return redirect(url_for('main.compose'))

        # Create campaign
        campaign = Campaign(name=campaign_name)
        db.session.add(campaign)
        db.session.commit()

        # Scheduled time - convert from IST to UTC
        scheduled_time = datetime.utcnow()
        if scheduled_time_str:
            try:
                # Parse the datetime string (e.g., "2025-11-25T09:27")
                naive_dt = datetime.strptime(scheduled_time_str, '%Y-%m-%dT%H:%M')
                # Assume user entered IST time, convert to UTC
                ist_time = user_tz.localize(naive_dt)
                scheduled_time = ist_time.astimezone(utc).replace(tzinfo=None)
                print(f"📅 DEBUG - IST time from form: {naive_dt} IST")
                print(f"⏰ DEBUG - Converted to UTC: {scheduled_time} UTC")
                print(f"🕐 DEBUG - Current UTC time: {datetime.utcnow()}")
            except ValueError:
                flash('Invalid date format', 'warning')

        emails_to_send = []

        # Method 1: Excel / CSV upload
        if file and file.filename:
            try:
                import pandas as pd

                if file.filename.endswith('.csv'):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)

                df.columns = [c.strip() for c in df.columns]
                email_col = next((c for c in df.columns if c.lower() == 'email'), None)

                if not email_col:
                    flash('Excel file must have an "Email" column', 'danger')
                    return redirect(url_for('main.compose'))

                for _, row in df.iterrows():
                    recipient = row[email_col]
                    if pd.isna(recipient) or not str(recipient).strip():
                        continue

                    subject = subject_template
                    body = body_template

                    # Replace {{column}}
                    for col in df.columns:
                        val = "" if pd.isna(row[col]) else str(row[col])
                        subject = subject.replace(f"{{{{{col}}}}}", val)
                        body = body.replace(f"{{{{{col}}}}}", val)

                    emails_to_send.append({
                        'recipient': str(recipient).strip(),
                        'subject': subject,
                        'body': body
                    })

            except Exception as e:
                flash(f"Error processing file: {e}", 'danger')
                return redirect(url_for('main.compose'))

        # Method 2: Manual recipients input
        elif recipients_str:
            recipients = [r.strip() for r in recipients_str.split(',') if r.strip()]
            for r in recipients:
                emails_to_send.append({
                    'recipient': r,
                    'subject': subject_template,
                    'body': body_template
                })
        else:
            flash('Please provide recipients or upload a file', 'warning')
            return redirect(url_for('main.compose'))

        # Save to DB
        for email_data in emails_to_send:
            new_email = Email(
                recipient=email_data['recipient'],
                subject=email_data['subject'],
                body=email_data['body'],
                scheduled_time=scheduled_time,
                campaign_id=campaign.id,
                status="pending"
            )
            db.session.add(new_email)

        db.session.commit()

        flash(f'Campaign "{campaign_name}" created with {len(emails_to_send)} emails.', 'success')
        return redirect(url_for('main.campaigns'))

    return render_template('compose.html')



@bp.route('/campaigns')
def campaigns():
    campaigns = Campaign.query.order_by(Campaign.created_at.desc()).all()

    campaign_stats = []
    for c in campaigns:
        total = len(c.emails)
        sent = sum(1 for e in c.emails if e.status == 'sent')
        failed = sum(1 for e in c.emails if e.status == 'failed')
        pending = total - sent - failed

        campaign_stats.append({
            'id': c.id,
            'name': c.name,
            'created_at': c.created_at,
            'total': total,
            'sent': sent,
            'failed': failed,
            'pending': pending
        })

    return render_template('campaigns.html', campaigns=campaign_stats)



@bp.route('/campaign/<int:id>')
def campaign_details(id):
    campaign = Campaign.query.get_or_404(id)
    return render_template('campaign_details.html', campaign=campaign)



@bp.route('/tasks/<int:id>/retry', methods=['POST'])
def retry_task(id):
    email = Email.query.get_or_404(id)
    email.status = 'pending'
    email.scheduled_time = datetime.utcnow()
    db.session.commit()
    flash(f'Retrying email to {email.recipient}', 'info')
    
    if email.campaign_id:
        return redirect(url_for('main.campaign_details', id=email.campaign_id))
    return redirect(url_for('main.campaigns'))



@bp.route('/schedule-email', methods=['POST'])
def schedule_email_api():
    data = request.get_json()
    recipient = data.get('recipient') or ""
    subject = data.get('subject') or ""
    body = data.get('body') or ""
    delay = data.get('delay', 0)

    if not recipient or not subject or not body:
        return jsonify({'error': 'Missing required fields'}), 400

    scheduled_time = datetime.utcnow() + timedelta(seconds=delay)

    new_email = Email(
        recipient=recipient.strip(),
        subject=subject,
        body=body,
        scheduled_time=scheduled_time,
        status="pending"
    )
    db.session.add(new_email)
    db.session.commit()

    return jsonify({'message': 'Email scheduled successfully', 'id': new_email.id}), 201



@bp.route('/settings', methods=['GET', 'POST'])
def settings():
    smtp_settings = SMTPSettings.query.first()

    if request.method == 'POST':
        if not smtp_settings:
            smtp_settings = SMTPSettings()
            db.session.add(smtp_settings)

        # Read form inputs
        form_server = request.form.get('smtp_server')
        form_port = request.form.get('smtp_port')
        form_username = request.form.get('smtp_username')
        form_password = request.form.get('smtp_password')
        form_from_email = request.form.get('from_email')
        form_signature = request.form.get('signature')
        form_use_tls = bool(request.form.get('use_tls'))

        # Safe setter helper: set attribute only if model has it, else create attribute
        def safe_set(obj, name, value):
            try:
                if hasattr(obj, name):
                    setattr(obj, name, value)
                else:
                    # create attribute on object instance (won't persist to DB unless column exists)
                    setattr(obj, name, value)
            except Exception:
                pass

        # Try to set several common names to avoid mismatches across versions
        safe_set(smtp_settings, 'smtp_server', form_server)
        safe_set(smtp_settings, 'server', form_server)
        safe_set(smtp_settings, 'host', form_server)

        if form_port:
            try:
                port_val = int(form_port)
            except Exception:
                port_val = None
        else:
            port_val = None

        safe_set(smtp_settings, 'smtp_port', port_val)
        safe_set(smtp_settings, 'port', port_val)

        safe_set(smtp_settings, 'smtp_username', form_username)
        safe_set(smtp_settings, 'username', form_username)

        safe_set(smtp_settings, 'smtp_password', form_password)
        safe_set(smtp_settings, 'password', form_password)

        safe_set(smtp_settings, 'from_email', form_from_email)
        safe_set(smtp_settings, 'default_sender', form_from_email)
        safe_set(smtp_settings, 'from_addr', form_from_email)
        safe_set(smtp_settings, 'sender', form_from_email)

        safe_set(smtp_settings, 'signature', form_signature)
        safe_set(smtp_settings, 'sig', form_signature)

        safe_set(smtp_settings, 'use_tls', form_use_tls)
        safe_set(smtp_settings, 'tls', form_use_tls)

        db.session.commit()
        flash('Settings updated successfully', 'success')
        return redirect(url_for('main.settings'))

    return render_template('settings.html', settings=smtp_settings)

@bp.route('/campaign/<int:id>/delete', methods=['POST'])
def delete_campaign(id):
    campaign = Campaign.query.get_or_404(id)

    # delete all emails under this campaign
    Email.query.filter_by(campaign_id=id).delete()

    # delete campaign
    db.session.delete(campaign)
    db.session.commit()

    return ("", 204)

@bp.route('/email/<int:id>/delete', methods=['POST'])
def delete_email(id):
    email = Email.query.get_or_404(id)
    db.session.delete(email)
    db.session.commit()
    return ("", 204)
@bp.route("/campaign/<int:id>/add-emails", methods=["POST"])
def add_emails_to_campaign(id):
    from app.models import Email
    from datetime import datetime
    import pandas as pd

    campaign = Campaign.query.get_or_404(id)
    recipients_str = request.form.get("recipients")
    file = request.files.get("file")
    emails_added = 0

    # Method 1: File Upload
    if file and file.filename:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        df.columns = [c.strip() for c in df.columns]
        email_col = next((c for c in df.columns if c.lower() == "email"), None)

        for _, row in df.iterrows():
            recipient = row[email_col]
            if pd.isna(recipient): continue

            new_email = Email(
                recipient=str(recipient).strip(),
                subject=campaign.emails[0].subject,   # reuse campaign subject
                body=campaign.emails[0].body,         # reuse body template
                scheduled_time=datetime.now(),
                status="pending",
                campaign_id=id,
            )
            db.session.add(new_email)
            emails_added += 1

    # Method 2: Manual
    if recipients_str:
        recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
        for r in recipients:
            new_email = Email(
                recipient=r,
                subject=campaign.emails[0].subject,
                body=campaign.emails[0].body,
                scheduled_time=datetime.now(),
                status="pending",
                campaign_id=id,
            )
            db.session.add(new_email)
            emails_added += 1

    db.session.commit()
    flash(f"Added {emails_added} new emails to campaign.", "success")
    return redirect(url_for('main.campaign_details', id=id))