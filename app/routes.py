from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, send_file, session
from flask_login import current_user, login_user, logout_user, login_required
from app import db, login
from app.models import Email, SMTPSettings, Campaign, User
# Note: ClickEvent is optional depending on if you created that model
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import unquote
import random
import string
import pytz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app, abort
from app.models import ClickEvent

user_tz = pytz.timezone("Asia/Kolkata")
utc = pytz.UTC

bp = Blueprint('main', __name__)

def send_system_email(to_email, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = current_app.config['SYSTEM_MAIL_SENDER']
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP(current_app.config['SYSTEM_MAIL_SERVER'], current_app.config['SYSTEM_MAIL_PORT'])
        server.starttls()
        server.login(current_app.config['SYSTEM_MAIL_USERNAME'], current_app.config['SYSTEM_MAIL_PASSWORD'])
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"System Email Error: {e}")
        return False

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

        # 1. Check if EMAIL exists specifically
        existing_email_user = User.query.filter_by(email=email).first()

        if existing_email_user:
            if not existing_email_user.is_verified:
                # Logic: User exists but not verified -> Resend OTP & Redirect
                otp = ''.join(random.choices(string.digits, k=6))
                existing_email_user.otp_code = otp
                # Optional: Update password if you want to allow password reset on re-signup
                # existing_email_user.set_password(password) 
                db.session.commit()

                send_system_email(email, "Verify Your Account", f"<h3>Your New OTP is: <b>{otp}</b></h3><p>Enter this on the verification page.</p>")

                session['verify_email'] = email
                flash('Account already exists but is not verified. We have sent a new OTP.', 'warning')
                return redirect(url_for('main.verify_otp'))
            else:
                # Logic: User exists and IS verified
                flash('Email already registered. Please login.', 'danger')
                return redirect(url_for('main.login'))

        # 2. Check if USERNAME exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists. Please choose another.', 'danger')
            return redirect(url_for('main.signup'))

        # 3. Create NEW User (if no conflicts)
        otp = ''.join(random.choices(string.digits, k=6))
        user = User(username=username, email=email, otp_code=otp, is_verified=False, is_active_user=False)
        user.set_password(password)

        # Make the first user an admin automatically
        if User.query.count() == 0:
            user.is_admin = True
            user.is_active_user = True
            user.is_verified = True

        db.session.add(user)
        db.session.commit()

        # Send OTP
        send_system_email(email, "Verify Your Account", f"<h3>Your OTP is: <b>{otp}</b></h3><p>Enter this on the verification page.</p>")

        session['verify_email'] = email

        flash('Registration successful! Please check your email for OTP.', 'info')
        return redirect(url_for('main.verify_otp'))

    return render_template('signup.html')

@bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    # CORRECTED LINE: Use 'session', not 'db.session'
    email = session.get('verify_email')

    if not email:
        flash('Session expired. Please login to verify.', 'warning')
        return redirect(url_for('main.login'))

    if request.method == 'POST':
        otp_input = request.form['otp']
        user = User.query.filter_by(email=email).first()

        if user and user.otp_code == otp_input:
            user.is_verified = True
            user.otp_code = None # Clear OTP
            db.session.commit()

            # Clear the session variable
            session.pop('verify_email', None)

            flash('Email verified! You can now login.', 'success')
            return redirect(url_for('main.login'))
        else:
            flash('Invalid OTP. Please try again.', 'danger')

    return render_template('verify_otp.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()

        if user is None or not user.check_password(request.form['password']):
            flash('Invalid username or password', 'danger')
            return redirect(url_for('main.login'))

        # CHECK 1: OTP Verification
        if not user.is_verified:
            # CORRECTED LINE: Use 'session'
            session['verify_email'] = user.email
            flash('Please verify your email first.', 'warning')
            return redirect(url_for('main.verify_otp'))

        # CHECK 2: Admin Approval (is_active_user)
        if not user.is_active_user:
            flash('Your account is pending Admin approval.', 'warning')
            return redirect(url_for('main.login'))

        # CHECK 3: Expiry Date
        if user.valid_until and datetime.utcnow() > user.valid_until:
            flash('Your subscription has expired. Contact Admin.', 'danger')
            return redirect(url_for('main.login'))

        login_user(user)
        return redirect(url_for('main.index'))

    return render_template('login.html')

@bp.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        abort(403) # Forbidden

    users = User.query.order_by(User.id).all()
    return render_template('admin_dashboard.html', users=users)

@bp.route('/admin/approve/<int:user_id>')
@login_required
def approve_user(user_id):
    if not current_user.is_admin: abort(403)

    user = User.query.get_or_404(user_id)
    user.is_active_user = True
    # Set default validity (e.g., 30 days)
    if not user.valid_until:
        user.valid_until = datetime.utcnow() + timedelta(days=30)

    db.session.commit()
    flash(f'User {user.username} approved!', 'success')
    return redirect(url_for('main.admin_dashboard'))

@bp.route('/admin/update_expiry/<int:user_id>', methods=['POST'])
@login_required
def update_expiry(user_id):
    if not current_user.is_admin: abort(403)

    user = User.query.get_or_404(user_id)
    date_str = request.form.get('expiry_date') # Format YYYY-MM-DD

    if date_str:
        try:
            user.valid_until = datetime.strptime(date_str, '%Y-%m-%d')
            db.session.commit()
            flash('Validity updated.', 'success')
        except:
            flash('Invalid date format.', 'danger')

    return redirect(url_for('main.admin_dashboard'))

@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.login'))

# --- API ROUTES ---

@bp.route('/api/stats')
@login_required
def get_stats_api():
    """API endpoint that returns live stats for AJAX refresh"""
    my_campaign_ids = [c.id for c in current_user.campaigns]

    if not my_campaign_ids:
        stats = {'sent': 0, 'pending': 0, 'failed': 0, 'processing': False}
    else:
        stats = {
            'sent': Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='sent').count(),
            'pending': Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='pending').count(),
            'failed': Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='failed').count()
        }
        # Processing status: show as processing if there are pending emails scheduled
        stats['processing'] = stats['pending'] > 0 or stats['sent'] > 0

    return jsonify(stats)

@bp.route('/api/activity-log')
@login_required
def get_activity_log():
    """Get recent activity data for dashboard infographics"""
    now = datetime.utcnow()

    # Recent campaigns (last 7 days)
    recent_campaigns = Campaign.query.filter(
        Campaign.user_id == current_user.id,
        Campaign.created_at >= now - timedelta(days=7)
    ).order_by(Campaign.created_at.desc()).limit(5).all()

    campaigns_data = []
    for campaign in recent_campaigns:
        sent = sum(1 for e in campaign.emails if e.status == 'sent')
        opened = sum(1 for e in campaign.emails if e.opened_at)
        campaigns_data.append({
            'name': campaign.name,
            'sent': sent,
            'opened': opened,
            'open_rate': round((opened / sent * 100), 1) if sent > 0 else 0,
            'created_at': campaign.created_at.strftime('%b %d')
        })

    # Activity breakdown (today) - count all sent/failed emails from all user's campaigns
    my_campaign_ids = [c.id for c in current_user.campaigns]
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if my_campaign_ids:
        today_sent = Email.query.filter(
            Email.campaign_id.in_(my_campaign_ids),
            Email.status == 'sent',
            Email.created_at >= today_start
        ).count()
        today_failed = Email.query.filter(
            Email.campaign_id.in_(my_campaign_ids),
            Email.status == 'failed',
            Email.created_at >= today_start
        ).count()
    else:
        today_sent = 0
        today_failed = 0

    # Top performing campaign (most emails)
    top_campaign = None
    if recent_campaigns:
        top_campaign = max(recent_campaigns, key=lambda c: len(c.emails))

    return jsonify({
        'recent_campaigns': campaigns_data,
        'today_activity': {
            'sent': today_sent,
            'failed': today_failed,
            'total': today_sent + today_failed
        },
        'top_campaign': {
            'name': top_campaign.name if top_campaign else 'N/A',
            'total_emails': len(top_campaign.emails) if top_campaign else 0
        }
    })

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

        # Deduplicate emails by recipient (prevent sending to same email twice)
        seen_recipients = set()
        unique_emails = []
        duplicates_removed = 0
        for email_data in emails_to_send:
            recipient_lower = email_data['recipient'].lower().strip()
            if recipient_lower not in seen_recipients:
                seen_recipients.add(recipient_lower)
                unique_emails.append(email_data)
            else:
                duplicates_removed += 1

        # Save to DB
        for email_data in unique_emails:
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
        if duplicates_removed > 0:
            flash(f'Campaign "{campaign_name}" created with {len(unique_emails)} emails. ({duplicates_removed} duplicates removed)', 'success')
        else:
            flash(f'Campaign "{campaign_name}" created with {len(unique_emails)} emails.', 'success')
        return redirect(url_for('main.campaigns'))

    return render_template('compose.html')

@bp.route('/campaigns')
@login_required
def campaigns():
    # Only show user's campaigns
    campaigns = Campaign.query.filter_by(user_id=current_user.id).order_by(Campaign.created_at.desc()).all()

    campaign_stats = []
    for c in campaigns:
        # Optimization: Use SQL count instead of Python len() for better performance
        total = Email.query.filter_by(campaign_id=c.id).count()
        sent = Email.query.filter_by(campaign_id=c.id, status='sent').count()
        failed = Email.query.filter_by(campaign_id=c.id, status='failed').count()
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
    """
    OPTIMIZED ROUTE: Handles server-side pagination and search.
    This prevents the page from crashing with large email lists.
    """
    # 1. Get the Campaign & Verify Ownership
    campaign = Campaign.query.filter_by(id=id, user_id=current_user.id).first_or_404()

    # 2. Get Page Number & Search Query from URL
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '', type=str)

    # 3. Build the Base Query
    query = Email.query.filter_by(campaign_id=id)

    # 4. Apply Search Filter (if user typed something)
    if search_query:
        search_pattern = f"%{search_query}%"
        query = query.filter(Email.recipient.ilike(search_pattern))

    # 5. Paginate (Show 100 per page)
    # error_out=False ensures empty page doesn't crash
    pagination = query.order_by(Email.id.desc()).paginate(
        page=page, per_page=100, error_out=False
    )

    # 6. Calculate Stats (Using SQL counts for speed)
    base_stats_query = Email.query.filter_by(campaign_id=id)

    total = base_stats_query.count()
    sent = base_stats_query.filter_by(status='sent').count()
    failed = base_stats_query.filter_by(status='failed').count()
    opened = base_stats_query.filter(Email.opened_at != None).count()
    clicked = base_stats_query.filter(Email.clicked_at != None).count()
    pending = total - (sent + failed)

    sent_pct = (sent / total * 100) if total > 0 else 0
    open_rate = (opened / sent * 100) if sent > 0 else 0

    stats = {
        'total': total,
        'sent': sent,
        'failed': failed,
        'opened': opened,
        'clicked': clicked,
        'pending': pending,
        'sent_pct': round(sent_pct, 1),
        'open_rate': round(open_rate, 1)
    }

    # 7. Render Template with pagination object
    return render_template(
        'campaign_details.html', 
        campaign=campaign, 
        stats=stats, 
        pagination=pagination
    )

@bp.route('/api/campaign/<int:id>/stats')
@login_required
def campaign_stats_api(id):
    """Detailed campaign stats API for real-time charts"""
    campaign = Campaign.query.filter_by(id=id, user_id=current_user.id).first_or_404()

    # Use SQL Counts for performance
    base_query = Email.query.filter_by(campaign_id=id)
    total = base_query.count()
    sent = base_query.filter_by(status='sent').count()
    failed = base_query.filter_by(status='failed').count()
    opened = base_query.filter(Email.opened_at != None).count()
    pending = total - sent - failed
    processing = pending > 0 or sent > 0

    # Batch info
    batches = db.session.query(Email.batch_id, db.func.count(Email.id)).filter(
        Email.campaign_id == id,
        Email.batch_id != None
    ).group_by(Email.batch_id).count()

    return jsonify({
        'total': total,
        'sent': sent,
        'failed': failed,
        'opened': opened,
        'pending': pending,
        'processing': processing,
        'sent_pct': round((sent / total * 100), 1) if total > 0 else 0,
        'failed_pct': round((failed / total * 100), 1) if total > 0 else 0,
        'pending_pct': round((pending / total * 100), 1) if total > 0 else 0,
        'open_rate': round((opened / sent * 100), 1) if sent > 0 else 0,
        'batches_processed': batches
    })

@bp.route('/track/<tracking_id>', methods=['GET'])
def track_email_open(tracking_id):
    """Handle email open tracking pixel requests"""
    email = Email.query.filter_by(tracking_id=tracking_id).first()
    if email and not email.opened_at:
        email.opened_at = datetime.utcnow()
        db.session.commit()
        import sys
        print(f"✅ TRACKED: Email {email.id} opened via {tracking_id}", file=sys.stderr)

    # Return 1x1 transparent GIF pixel
    pixel = BytesIO()
    pixel.write(b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b')
    pixel.seek(0)
    return send_file(pixel, mimetype='image/gif', cache_control='no-cache, no-store, must-revalidate')

# --- NEW CLICK TRACKING ROUTE ---
@bp.route('/click/<tracking_id>')
def track_click(tracking_id):
    target_url = request.args.get('url')
    if not target_url:
        return "Invalid URL", 400

    # 1. Decode the target URL
    target_url = unquote(target_url)

    # 2. Find the email
    email = Email.query.filter_by(tracking_id=tracking_id).first()

    if email:
        # 3. Mark as Clicked (First click only)
        if not email.clicked_at:
            email.clicked_at = datetime.utcnow()
            # If also not marked as opened, mark it (clicking implies opening)
            if not email.opened_at:
                email.opened_at = datetime.utcnow()
            db.session.commit()

        # 4. (Optional) Log detailed event
        # new_click = ClickEvent(email_id=email.id, url=target_url, ip_address=request.remote_addr)
        # db.session.add(new_click)
        # db.session.commit()

        print(f"✅ CLICKED: Email {email.id} clicked link {target_url}")

    # 5. Redirect to actual destination
    return redirect(target_url)

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
    # Note: If no emails exist, we default to campaign name or empty string
    base_subject = campaign.name
    base_body = ""

    # Optimize: Don't load all emails just to get the first one. Use .first()
    first_email = Email.query.filter_by(campaign_id=id).first()
    if first_email:
        base_subject = first_email.subject
        base_body = first_email.body

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

@bp.route('/resend-otp')
def resend_otp():
    # 1. Get email from session
    email = session.get('verify_email')

    if not email:
        flash('Session expired. Please try logging in again.', 'warning')
        return redirect(url_for('main.login'))

    # 2. Find User
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('main.signup'))

    # 3. Prevent Spam (Optional: Check if an OTP was sent < 1 min ago)
    # You can implement a timestamp check here if needed

    # 4. Generate New OTP
    new_otp = ''.join(random.choices(string.digits, k=6))
    user.otp_code = new_otp
    db.session.commit()

    # 5. Send Email
    subject = "Resend: Verify Your Account"
    body = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
        <h2>Verify Your Account</h2>
        <p>You requested a new verification code.</p>
        <div style="background: #f4f4f4; padding: 15px; border-radius: 5px; text-align: center; margin: 20px 0;">
            <span style="font-size: 24px; letter-spacing: 5px; font-weight: bold; color: #174143;">{new_otp}</span>
        </div>
        <p>If you did not request this, please ignore this email.</p>
    </div>
    """

    if send_system_email(email, subject, body):
        flash('A new OTP has been sent to your email.', 'success')
    else:
        # This will show if your SMTP settings are wrong
        flash('Failed to send email. Please contact support.', 'danger')

    return redirect(url_for('main.verify_otp'))

@bp.route('/admin/user/<int:user_id>/edit', methods=['POST'])
@login_required
def admin_edit_user(user_id):
    if not current_user.is_admin: abort(403)

    user = User.query.get_or_404(user_id)

    # Update Basic Info
    user.username = request.form.get('username')
    user.email = request.form.get('email')

    # Update Roles/Status
    # Checkboxes only send value if checked
    user.is_admin = bool(request.form.get('is_admin'))
    user.is_active_user = bool(request.form.get('is_active'))

    try:
        db.session.commit()
        flash(f'User {user.username} updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating user: {e}', 'danger')

    return redirect(url_for('main.admin_dashboard'))

@bp.route('/admin/user/<int:user_id>/password', methods=['POST'])
@login_required
def admin_reset_password(user_id):
    if not current_user.is_admin: abort(403)

    user = User.query.get_or_404(user_id)
    new_pass = request.form.get('new_password')

    if new_pass:
        user.set_password(new_pass)
        db.session.commit()
        flash(f'Password for {user.username} has been changed.', 'success')
    else:
        flash('Password cannot be empty.', 'warning')

    return redirect(url_for('main.admin_dashboard'))

@bp.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin: abort(403)

    if user_id == current_user.id:
        flash("You cannot delete yourself!", "danger")
        return redirect(url_for('main.admin_dashboard'))

    user = User.query.get_or_404(user_id)
    username = user.username

    try:
        # 1. Delete SMTP Settings
        if user.smtp_settings:
            db.session.delete(user.smtp_settings)

        # 2. Delete Campaigns and their Emails (Cascading manually for safety)
        for campaign in user.campaigns:
            # Delete Emails
            emails = Email.query.filter_by(campaign_id=campaign.id).all()
            for email in emails:
                # Delete ClickEvents first
                ClickEvent.query.filter_by(email_id=email.id).delete()
                db.session.delete(email)

            # Delete Campaign
            db.session.delete(campaign)

        # 3. Delete the User
        db.session.delete(user)
        db.session.commit()

        flash(f'User "{username}" and all their data have been deleted.', 'info')

    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {e}', 'danger')

    return redirect(url_for('main.admin_dashboard'))


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()

        if user:
            # Generate OTP
            otp = ''.join(random.choices(string.digits, k=6))
            user.otp_code = otp
            db.session.commit()

            # Send Email
            email_body = f"""
            <div style="font-family: Arial, sans-serif; padding: 20px; background-color: #f4f4f4;">
                <div style="background-color: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
                    <h2 style="color: #174143;">Password Reset Request</h2>
                    <p>You requested to reset your password. Your OTP code is:</p>
                    <h1 style="color: #F9B487; letter-spacing: 5px;">{otp}</h1>
                    <p>If you did not request this, please ignore this email.</p>
                </div>
            </div>
            """
            send_system_email(email, "Reset Your Password", email_body)

            # Store email in session for the next step
            session['reset_email'] = email
            flash('An OTP has been sent to your email address.', 'info')
            return redirect(url_for('main.verify_reset_otp'))
        else:
            # For security, we can genericize this message, or keep it specific for UX
            flash('No account found with that email address.', 'danger')

    return render_template('forgot_password.html')

@bp.route('/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp():
    email = session.get('reset_email')
    if not email:
        flash('Session expired. Please start over.', 'warning')
        return redirect(url_for('main.forgot_password'))

    if request.method == 'POST':
        otp_input = request.form.get('otp')
        user = User.query.filter_by(email=email).first()

        if user and user.otp_code and user.otp_code == otp_input:
            # Mark session as verified for reset
            session['allow_password_reset'] = True

            # Clear OTP immediately to prevent reuse
            user.otp_code = None
            db.session.commit()

            flash('OTP Verified! Please set your new password.', 'success')
            return redirect(url_for('main.reset_password'))
        else:
            flash('Invalid or expired OTP. Please try again.', 'danger')

    return render_template('verify_reset_otp.html')

@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    # Security Check: Ensure user passed the previous steps
    if not session.get('allow_password_reset') or not session.get('reset_email'):
        return redirect(url_for('main.login'))

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
        else:
            email = session.get('reset_email')
            user = User.query.filter_by(email=email).first()

            if user:
                user.set_password(password)
                db.session.commit()

                # Clear session security flags
                session.pop('allow_password_reset', None)
                session.pop('reset_email', None)

                flash('Your password has been reset successfully. Please login.', 'success')
                return redirect(url_for('main.login'))

    return render_template('reset_password.html')

@bp.route('/admin/user/<int:user_id>/toggle-status', methods=['POST'])
@login_required
def toggle_user_status(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    user = User.query.get_or_404(user_id)

    # Prevent admin from deactivating themselves
    if user.id == current_user.id:
         return jsonify({'error': 'You cannot deactivate your own account'}), 400

    # Flip the status
    user.is_active_user = not user.is_active_user
    db.session.commit()

    return jsonify({
        'success': True, 
        'new_status': user.is_active_user,
        'username': user.username
    })