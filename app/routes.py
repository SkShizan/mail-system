from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import current_user, login_user, logout_user, login_required
from app import db, login
from app.models import Email, SMTPSettings, Campaign, User
from datetime import datetime, timedelta
import pytz

user_tz = pytz.timezone("Asia/Kolkata")
utc = pytz.UTC

bp = Blueprint('main', __name__)

@login.user_loader
def load_user(id):
    return User.query.get(int(id))

# --- AUTH ROUTES ---

@bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('Username or Email already exists.', 'danger')
            return redirect(url_for('main.signup'))

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('main.login'))
    return render_template('signup.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user is None or not user.check_password(request.form['password']):
            flash('Invalid username or password', 'danger')
            return redirect(url_for('main.login'))
        login_user(user)
        return redirect(url_for('main.index'))
    return render_template('login.html')

@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.login'))

# --- APPLICATION ROUTES (Protected) ---

@bp.route('/')
@login_required
def index():
    # Filter stats by campaigns belonging to current_user
    my_campaign_ids = [c.id for c in current_user.campaigns]

    if not my_campaign_ids:
        stats = {'sent': 0, 'pending': 0, 'failed': 0}
    else:
        stats = {
            'sent': Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='sent').count(),
            'pending': Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='pending').count(),
            'failed': Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='failed').count()
        }
    return render_template('dashboard.html', stats=stats)

@bp.route('/compose', methods=['GET', 'POST'])
@login_required
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

        # Create campaign LINKED TO CURRENT USER
        campaign = Campaign(name=campaign_name, user_id=current_user.id)
        db.session.add(campaign)
        db.session.commit()

        # Scheduled time - convert from IST to UTC
        scheduled_time = datetime.utcnow()
        if scheduled_time_str:
            try:
                naive_dt = datetime.strptime(scheduled_time_str, '%Y-%m-%dT%H:%M')
                ist_time = user_tz.localize(naive_dt)
                scheduled_time = ist_time.astimezone(utc).replace(tzinfo=None)
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

        # Method 2: Manual recipients
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
@login_required
def campaigns():
    # Only show user's campaigns
    campaigns = Campaign.query.filter_by(user_id=current_user.id).order_by(Campaign.created_at.desc()).all()

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
@login_required
def campaign_details(id):
    # Ensure user owns this campaign
    campaign = Campaign.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    
    # Calculate campaign stats
    total = len(campaign.emails)
    sent = sum(1 for e in campaign.emails if e.status == 'sent')
    failed = sum(1 for e in campaign.emails if e.status == 'failed')
    pending = total - sent - failed
    
    stats = {
        'total': total,
        'sent': sent,
        'failed': failed,
        'pending': pending,
        'sent_pct': (sent / total * 100) if total > 0 else 0
    }
    
    return render_template('campaign_details.html', campaign=campaign, stats=stats)

@bp.route('/tasks/<int:id>/retry', methods=['POST'])
@login_required
def retry_task(id):
    # Ensure email belongs to a campaign owned by user
    email = Email.query.join(Campaign).filter(
        Email.id == id, 
        Campaign.user_id == current_user.id
    ).first_or_404()

    email.status = 'pending'
    email.scheduled_time = datetime.utcnow()
    db.session.commit()
    flash(f'Retrying email to {email.recipient}', 'info')

    if email.campaign_id:
        return redirect(url_for('main.campaign_details', id=email.campaign_id))
    return redirect(url_for('main.campaigns'))

@bp.route('/schedule-email', methods=['POST'])
@login_required
def schedule_email_api():
    data = request.get_json()
    recipient = data.get('recipient') or ""
    subject = data.get('subject') or ""
    body = data.get('body') or ""
    delay = data.get('delay', 0)

    if not recipient or not subject or not body:
        return jsonify({'error': 'Missing required fields'}), 400

    scheduled_time = datetime.utcnow() + timedelta(seconds=delay)

    # Create a default/hidden campaign for direct API calls if needed, 
    # or just create email without campaign (but careful with ownership).
    # Ideally, API should specify campaign. For now, we link to a "Direct" campaign or None.
    # Note: If campaign_id is None, it won't show in any user dashboard. 
    # Let's create a temporary campaign holder for API calls or require it.

    # For simplicity in this snippets, we will just create it.
    # WARNING: Without campaign_id, it might be orphaned in UI. 
    # Let's create a "API Campaign" for the user if it doesn't exist.

    api_campaign = Campaign.query.filter_by(user_id=current_user.id, name="API Emails").first()
    if not api_campaign:
        api_campaign = Campaign(name="API Emails", user_id=current_user.id)
        db.session.add(api_campaign)
        db.session.commit()

    new_email = Email(
        recipient=recipient.strip(),
        subject=subject,
        body=body,
        scheduled_time=scheduled_time,
        status="pending",
        campaign_id=api_campaign.id
    )
    db.session.add(new_email)
    db.session.commit()

    return jsonify({'message': 'Email scheduled successfully', 'id': new_email.id}), 201

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    # Fetch settings specifically for this user
    smtp_settings = SMTPSettings.query.filter_by(user_id=current_user.id).first()

    if request.method == 'POST':
        if not smtp_settings:
            smtp_settings = SMTPSettings(user_id=current_user.id)
            db.session.add(smtp_settings)

        # Read form inputs
        form_server = request.form.get('smtp_server')
        form_port = request.form.get('smtp_port')
        form_username = request.form.get('smtp_username')
        form_password = request.form.get('smtp_password')
        form_from_email = request.form.get('from_email')
        form_signature = request.form.get('signature')
        form_use_tls = bool(request.form.get('use_tls'))

        # Safe setter helper
        def safe_set(obj, name, value):
            try:
                if hasattr(obj, name):
                    setattr(obj, name, value)
            except Exception:
                pass

        safe_set(smtp_settings, 'server', form_server)

        try:
            port_val = int(form_port) if form_port else None
        except:
            port_val = None
        safe_set(smtp_settings, 'port', port_val)

        safe_set(smtp_settings, 'username', form_username)
        safe_set(smtp_settings, 'password', form_password)
        safe_set(smtp_settings, 'default_sender', form_from_email)
        safe_set(smtp_settings, 'signature', form_signature)
        safe_set(smtp_settings, 'use_tls', form_use_tls)

        db.session.commit()
        flash('Settings updated successfully', 'success')
        return redirect(url_for('main.settings'))

    return render_template('settings.html', settings=smtp_settings)

@bp.route('/campaign/<int:id>/delete', methods=['POST'])
@login_required
def delete_campaign(id):
    campaign = Campaign.query.filter_by(id=id, user_id=current_user.id).first_or_404()

    # Emails will be deleted by cascade, but good to be explicit or safe
    Email.query.filter_by(campaign_id=id).delete()

    db.session.delete(campaign)
    db.session.commit()
    return ("", 204)

@bp.route('/email/<int:id>/delete', methods=['POST'])
@login_required
def delete_email(id):
    # Ensure email belongs to user
    email = Email.query.join(Campaign).filter(
        Email.id == id, 
        Campaign.user_id == current_user.id
    ).first_or_404()

    db.session.delete(email)
    db.session.commit()
    return ("", 204)

@bp.route("/campaign/<int:id>/add-emails", methods=["POST"])
@login_required
def add_emails_to_campaign(id):
    from app.models import Email
    import pandas as pd

    campaign = Campaign.query.filter_by(id=id, user_id=current_user.id).first_or_404()

    recipients_str = request.form.get("recipients")
    file = request.files.get("file")
    emails_added = 0

    # Use first existing email to get template body/subject if available, else default
    base_subject = campaign.name
    base_body = ""
    if campaign.emails:
        base_subject = campaign.emails[0].subject
        base_body = campaign.emails[0].body

    # Method 1: File Upload
    if file and file.filename:
        try:
            if file.filename.endswith(".csv"):
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)

            df.columns = [c.strip() for c in df.columns]
            email_col = next((c for c in df.columns if c.lower() == "email"), None)

            if email_col:
                for _, row in df.iterrows():
                    recipient = row[email_col]
                    if pd.isna(recipient): continue

                    new_email = Email(
                        recipient=str(recipient).strip(),
                        subject=base_subject,
                        body=base_body,
                        scheduled_time=datetime.now(),
                        status="pending",
                        campaign_id=id,
                    )
                    db.session.add(new_email)
                    emails_added += 1
        except Exception as e:
            flash(f"Error reading file: {e}", "danger")

    # Method 2: Manual
    if recipients_str:
        recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
        for r in recipients:
            new_email = Email(
                recipient=r,
                subject=base_subject,
                body=base_body,
                scheduled_time=datetime.now(),
                status="pending",
                campaign_id=id,
            )
            db.session.add(new_email)
            emails_added += 1

    db.session.commit()
    flash(f"Added {emails_added} new emails to campaign.", "success")
    return redirect(url_for('main.campaign_details', id=id))