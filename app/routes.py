from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, session, abort, make_response
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User, Campaign, Email, SMTPSettings, ClickEvent
from app.utils import send_system_email
from datetime import datetime, timedelta
import random
import string
import pandas as pd
from io import BytesIO
from urllib.parse import unquote, quote
import pytz

bp = Blueprint('main', __name__)

@bp.route('/')
@login_required
def index():
    # Only show user's campaigns
    campaigns = Campaign.query.filter_by(user_id=current_user.id).order_by(Campaign.created_at.desc()).limit(5).all()
    
    # Calculate stats for the user
    my_campaign_ids = [c.id for c in current_user.campaigns]
    
    if not my_campaign_ids:
        stats = {'total': 0, 'sent': 0, 'pending': 0, 'failed': 0, 'open_rate': 0}
    else:
        total = Email.query.filter(Email.campaign_id.in_(my_campaign_ids)).count()
        sent = Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='sent').count()
        failed = Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='failed').count()
        opened = Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.opened_at != None).count()
        pending = total - sent - failed
        
        open_rate = (opened / sent * 100) if sent > 0 else 0
        
        stats = {
            'total': total,
            'sent': sent,
            'pending': pending,
            'failed': failed,
            'open_rate': round(open_rate, 1)
        }

    return render_template('dashboard.html', campaigns=campaigns, stats=stats)

@bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('main.signup'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return redirect(url_for('main.signup'))
        
        # Check if first user - make admin
        is_first_user = User.query.count() == 0
        
        user = User(username=username, email=email)
        user.set_password(password)
        user.is_admin = is_first_user
        user.is_active_user = is_first_user # Auto-approve first user
        
        # Generate OTP
        otp = ''.join(random.choices(string.digits, k=6))
        user.otp_code = otp
        
        db.session.add(user)
        db.session.commit()
        
        # Send Verification Email
        subject = "Verify Your Nexus Email Account"
        body = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
            <h2 style="color: #174143;">Welcome to Nexus!</h2>
            <p>Thank you for signing up. Please use the following code to verify your account:</p>
            <div style="background: #f4f4f4; padding: 15px; border-radius: 5px; text-align: center; margin: 20px 0;">
                <span style="font-size: 24px; letter-spacing: 5px; font-weight: bold; color: #174143;">{otp}</span>
            </div>
            <p>If you did not create an account, please ignore this email.</p>
        </div>
        """
        
        if send_system_email(email, subject, body):
            session['verify_email'] = email
            flash('Account created! Please check your email for the verification code.', 'success')
            return redirect(url_for('main.verify_otp'))
        else:
            flash('Account created, but failed to send verification email. Please contact support.', 'warning')
            session['verify_email'] = email
            return redirect(url_for('main.verify_otp'))
            
    return render_template('signup.html')

@bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('verify_email')
    if not email:
        return redirect(url_for('main.signup'))
    
    if request.method == 'POST':
        otp_input = request.form['otp']
        user = User.query.filter_by(email=email).first()
        
        if user and user.otp_code == otp_input:
            user.is_verified = True
            user.otp_code = None
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
        
        if not user.is_verified:
            session['verify_email'] = user.email
            flash('Please verify your email first.', 'warning')
            return redirect(url_for('main.verify_otp'))
            
        if not user.is_active_user:
            flash('Your account is pending Admin approval.', 'warning')
            return redirect(url_for('main.login'))
            
        if user.valid_until and datetime.utcnow() > user.valid_until:
            flash('Your subscription has expired. Contact Admin.', 'danger')
            return redirect(url_for('main.login'))
            
        login_user(user)
        return redirect(url_for('main.index'))
        
    return render_template('login.html')

@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.login'))

@bp.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        abort(403)
    users = User.query.order_by(User.id).all()
    return render_template('admin_dashboard.html', users=users)

@bp.route('/admin/approve/<int:user_id>')
@login_required
def approve_user(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id)
    user.is_active_user = True
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
    date_str = request.form.get('expiry_date')
    if date_str:
        try:
            user.valid_until = datetime.strptime(date_str, '%Y-%m-%d')
            db.session.commit()
            flash('Validity updated.', 'success')
        except:
            flash('Invalid date format.', 'danger')
    return redirect(url_for('main.admin_dashboard'))

@bp.route('/api/stats')
@login_required
def get_stats_api():
    my_campaign_ids = [c.id for c in current_user.campaigns]
    if not my_campaign_ids:
        stats = {'sent': 0, 'pending': 0, 'failed': 0, 'processing': False}
    else:
        stats = {
            'sent': Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='sent').count(),
            'pending': Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='pending').count(),
            'failed': Email.query.filter(Email.campaign_id.in_(my_campaign_ids), Email.status=='failed').count()
        }
        stats['processing'] = stats['pending'] > 0
    return jsonify(stats)

@bp.route('/api/activity-log')
@login_required
def get_activity_log():
    my_campaign_ids = [c.id for c in current_user.campaigns]
    if not my_campaign_ids:
        return jsonify([])
    
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    daily_stats = db.session.query(
        db.func.date(Email.sent_at).label('date'),
        db.func.count(Email.id).label('count')
    ).filter(
        Email.campaign_id.in_(my_campaign_ids),
        Email.status == 'sent',
        Email.sent_at >= seven_days_ago
    ).group_by(db.func.date(Email.sent_at)).all()
    
    return jsonify([{'date': str(d.date), 'count': d.count} for d in daily_stats])

@bp.route('/compose', methods=['GET', 'POST'])
@login_required
def compose():
    duplicate_id = request.args.get('duplicate_from')
    prefill = {
        'recipients': request.args.get('recipients', ''),
        'subject': request.args.get('subject', ''),
        'body': request.args.get('body', ''),
        'campaign_name': request.args.get('campaign_name', '')
    }

    if duplicate_id:
        old_camp = Campaign.query.filter_by(id=duplicate_id, user_id=current_user.id).first()
        if old_camp:
            prefill['campaign_name'] = f"Copy of {old_camp.name}"
            # Load unique recipients from old campaign
            # Accessing .emails relationship directly
            recipients = [e.recipient for e in old_camp.emails]
            prefill['recipients'] = ", ".join(list(dict.fromkeys(recipients)))
            
            # Load subject and body from the first email found in this campaign
            first_email = Email.query.filter_by(campaign_id=old_camp.id).first()
            if first_email:
                prefill['subject'] = first_email.subject
                prefill['body'] = first_email.body
            
            # Debugging - ensure we are prefilling
            print(f"DEBUG: Duplicating campaign {duplicate_id}. Recipients: {len(recipients)}")
    
    if request.method == 'POST':
        campaign_name = request.form.get('campaign_name')
        subject_template = request.form.get('subject')
        body_template = request.form.get('body')
        recipients_str = request.form.get('recipients')
        file = request.files.get('file')
        scheduled_time_str = request.form.get('scheduled_time')
        
        if not campaign_name:
            flash('Campaign Name is required', 'danger')
            return redirect(url_for('main.compose'))

        campaign = Campaign(name=campaign_name, user_id=current_user.id)
        db.session.add(campaign)
        db.session.commit()

        user_tz = pytz.timezone('Asia/Kolkata')
        utc = pytz.utc
        scheduled_time = datetime.utcnow()
        if scheduled_time_str:
            try:
                naive_dt = datetime.strptime(scheduled_time_str, '%Y-%m-%dT%H:%M')
                ist_time = user_tz.localize(naive_dt)
                scheduled_time = ist_time.astimezone(utc).replace(tzinfo=None)
            except ValueError:
                flash('Invalid date format', 'warning')

        emails_to_send = []

        if file and file.filename:
            try:
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

        if recipients_str:
            recipients = [r.strip() for r in recipients_str.split(',') if r.strip()]
            for r in recipients:
                emails_to_send.append({
                    'recipient': r,
                    'subject': subject_template,
                    'body': body_template
                })

        if not emails_to_send:
            flash('Please provide recipients or upload a file', 'warning')
            return redirect(url_for('main.compose'))

        seen_recipients = set()
        unique_emails = []
        for email_data in emails_to_send:
            recipient_lower = email_data['recipient'].lower().strip()
            if recipient_lower not in seen_recipients:
                seen_recipients.add(recipient_lower)
                unique_emails.append(email_data)

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
        flash(f'Campaign "{campaign_name}" created with {len(unique_emails)} emails.', 'success')
        return redirect(url_for('main.campaigns'))

    return render_template('compose.html', prefill=prefill)

@bp.route('/campaigns')
@login_required
def campaigns():
    campaigns = Campaign.query.filter_by(user_id=current_user.id).order_by(Campaign.created_at.desc()).all()
    campaign_stats = []
    for c in campaigns:
        total = Email.query.filter_by(campaign_id=c.id).count()
        sent = Email.query.filter_by(campaign_id=c.id, status='sent').count()
        failed = Email.query.filter_by(campaign_id=c.id, status='failed').count()
        pending = total - sent - failed
        campaign_stats.append({
            'id': c.id, 'name': c.name, 'created_at': c.created_at,
            'total': total, 'sent': sent, 'failed': failed, 'pending': pending
        })
    return render_template('campaigns.html', campaigns=campaign_stats)

@bp.route('/campaign/<int:id>')
@login_required
def campaign_details(id):
    campaign = Campaign.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '', type=str)
    query = Email.query.filter_by(campaign_id=id)
    if search_query:
        query = query.filter(Email.recipient.ilike(f"%{search_query}%"))
    pagination = query.order_by(Email.id.desc()).paginate(page=page, per_page=100, error_out=False)
    
    total = Email.query.filter_by(campaign_id=id).count()
    sent = Email.query.filter_by(campaign_id=id, status='sent').count()
    failed = Email.query.filter_by(campaign_id=id, status='failed').count()
    opened = Email.query.filter_by(campaign_id=id).filter(Email.opened_at != None).count()
    clicked = Email.query.filter_by(campaign_id=id).filter(Email.clicked_at != None).count()
    pending = total - (sent + failed)
    
    stats = {
        'total': total, 'sent': sent, 'failed': failed, 'opened': opened,
        'clicked': clicked, 'pending': pending,
        'sent_pct': round((sent / total * 100), 1) if total > 0 else 0,
        'open_rate': round((opened / sent * 100), 1) if sent > 0 else 0
    }
    
    sample = Email.query.filter_by(campaign_id=id).first()
    return render_template('campaign_details.html', campaign=campaign, stats=stats, pagination=pagination,
                           campaign_content=sample.body if sample else "", campaign_subject=sample.subject if sample else "")

@bp.route('/campaign/<int:id>/update-content', methods=['POST'])
@login_required
def update_campaign_content(id):
    campaign = Campaign.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    new_subject = request.form.get('subject')
    new_body = request.form.get('body')
    if not new_subject or not new_body:
        flash("Subject and Body cannot be empty.", "danger")
    else:
        updated = Email.query.filter_by(campaign_id=id, status='pending').update({Email.subject: new_subject, Email.body: new_body})
        db.session.commit()
        flash(f"Updated {updated} pending emails.", "success")
    return redirect(url_for('main.campaign_details', id=id))

@bp.route('/api/campaign/<int:id>/stats')
@login_required
def campaign_stats_api(id):
    campaign = Campaign.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    base = Email.query.filter_by(campaign_id=id)
    total = base.count()
    sent = base.filter_by(status='sent').count()
    failed = base.filter_by(status='failed').count()
    opened = base.filter(Email.opened_at != None).count()
    bots = base.filter(Email.bot_detected_at != None).count()
    pending = total - sent - failed
    
    return jsonify({
        'total': total, 'sent': sent, 'failed': failed, 'opened': opened, 'bots': bots, 'pending': pending,
        'processing': pending > 0,
        'sent_pct': round((sent / total * 100), 1) if total > 0 else 0,
        'open_rate': round((opened / sent * 100), 1) if sent > 0 else 0
    })

@bp.route('/track/<tracking_id>', methods=['GET'])
def track_email_open(tracking_id):
    email = Email.query.filter_by(tracking_id=tracking_id).first()
    if not email:
        return _serve_pixel()

    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    user_agent = request.headers.get('User-Agent', '').lower()
    
    is_apple_mpp = "apple" in user_agent and "mail" in user_agent and "proxy" in user_agent
    google_ips = ("74.125.", "64.233.")
    is_proxy = ip_address.startswith(google_ips) or "proxy" in user_agent or "cloud" in user_agent
    is_ua_bot = any(bot in user_agent for bot in ["bot", "crawl", "spider", "slurp", "preview"])
    
    now = datetime.utcnow()
    is_too_fast = False
    if email.sent_at:
        diff = (now - email.sent_at).total_seconds()
        if diff < 3:
            is_too_fast = True

    is_bot = is_ua_bot or is_too_fast or (is_apple_mpp and is_proxy)

    try:
        if hasattr(email, 'open_user_agent'): email.open_user_agent = user_agent[:255]
        if hasattr(email, 'open_ip_address'): email.open_ip_address = ip_address

        if is_bot:
            if not email.bot_detected_at: email.bot_detected_at = now
        else:
            if not email.opened_at: email.opened_at = now
        db.session.commit()
    except Exception as e:
        db.session.rollback()

    return _serve_pixel()

def _serve_pixel():
    pixel = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
    response = make_response(send_file(BytesIO(pixel), mimetype='image/gif'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@bp.route('/click/<tracking_id>')
def track_click(tracking_id):
    target_url = request.args.get('url')
    if not target_url: return "Invalid URL", 400
    email = Email.query.filter_by(tracking_id=tracking_id).first()
    if email:
        if not email.clicked_at:
            email.clicked_at = datetime.utcnow()
            if not email.opened_at: email.opened_at = datetime.utcnow()
            db.session.commit()
    return redirect(unquote(target_url))

@bp.route('/tasks/<int:id>/retry', methods=['POST'])
@login_required
def retry_task(id):
    email = Email.query.join(Campaign).filter(Email.id == id, Campaign.user_id == current_user.id).first_or_404()
    email.status = 'pending'
    email.scheduled_time = datetime.utcnow()
    db.session.commit()
    flash(f'Retrying email to {email.recipient}', 'info')
    return redirect(url_for('main.campaign_details', id=email.campaign_id) if email.campaign_id else url_for('main.campaigns'))

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    smtp = SMTPSettings.query.filter_by(user_id=current_user.id).first()
    if request.method == 'POST':
        if not smtp:
            smtp = SMTPSettings(user_id=current_user.id)
            db.session.add(smtp)
        smtp.server = request.form.get('smtp_server')
        smtp.port = int(request.form.get('smtp_port')) if request.form.get('smtp_port') else None
        smtp.username = request.form.get('smtp_username')
        smtp.password = request.form.get('smtp_password')
        smtp.default_sender = request.form.get('from_email')
        smtp.signature = request.form.get('signature')
        smtp.use_tls = bool(request.form.get('use_tls'))
        db.session.commit()
        flash('Settings updated', 'success')
        return redirect(url_for('main.settings'))
    return render_template('settings.html', settings=smtp)

@bp.route('/campaign/<int:id>/delete', methods=['POST'])
@login_required
def delete_campaign(id):
    c = Campaign.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    Email.query.filter_by(campaign_id=id).delete()
    db.session.delete(c)
    db.session.commit()
    return ("", 204)

@bp.route('/resend-otp')
def resend_otp():
    email = session.get('verify_email')
    if not email: return redirect(url_for('main.login'))
    user = User.query.filter_by(email=email).first()
    if not user: return redirect(url_for('main.signup'))
    otp = ''.join(random.choices(string.digits, k=6))
    user.otp_code = otp
    db.session.commit()
    if send_system_email(email, "Resend: Verify Your Account", f"OTP: {otp}"):
        flash('OTP sent', 'success')
    return redirect(url_for('main.verify_otp'))

@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            otp = ''.join(random.choices(string.digits, k=6))
            user.otp_code = otp
            db.session.commit()
            send_system_email(email, "Reset Your Password", f"OTP: {otp}")
            session['reset_email'] = email
            flash('OTP sent', 'info')
            return redirect(url_for('main.verify_reset_otp'))
    return render_template('forgot_password.html')

@bp.route('/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp():
    email = session.get('reset_email')
    if not email: return redirect(url_for('main.forgot_password'))
    if request.method == 'POST':
        if User.query.filter_by(email=email, otp_code=request.form.get('otp')).first():
            session['allow_password_reset'] = True
            flash('OTP Verified', 'success')
            return redirect(url_for('main.reset_password'))
    return render_template('verify_reset_otp.html')

@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('allow_password_reset'): return redirect(url_for('main.login'))
    if request.method == 'POST':
        if request.form.get('password') == request.form.get('confirm_password'):
            user = User.query.filter_by(email=session.get('reset_email')).first()
            if user:
                user.set_password(request.form.get('password'))
                db.session.commit()
                session.pop('allow_password_reset', None)
                flash('Password reset', 'success')
                return redirect(url_for('main.login'))
    return render_template('reset_password.html')

@bp.route('/admin/user/<int:user_id>/edit', methods=['POST'])
@login_required
def admin_edit_user(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id)
    user.username = request.form.get('username')
    user.email = request.form.get('email')
    user.is_admin = bool(request.form.get('is_admin'))
    user.is_active_user = bool(request.form.get('is_active'))
    db.session.commit()
    flash('User updated', 'success')
    return redirect(url_for('main.admin_dashboard'))

@bp.route('/admin/user/<int:user_id>/password', methods=['POST'])
@login_required
def admin_reset_password(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id)
    if request.form.get('new_password'):
        user.set_password(request.form.get('new_password'))
        db.session.commit()
        flash('Password changed', 'success')
    return redirect(url_for('main.admin_dashboard'))

@bp.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin or user_id == current_user.id: abort(403)
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted', 'info')
    return redirect(url_for('main.admin_dashboard'))

@bp.route('/admin/user/<int:user_id>/toggle-status', methods=['POST'])
@login_required
def toggle_user_status(user_id):
    if not current_user.is_admin or user_id == current_user.id: return jsonify({'error': 'Unauthorized'}), 403
    user = User.query.get_or_404(user_id)
    user.is_active_user = not user.is_active_user
    db.session.commit()
    return jsonify({'success': True, 'new_status': user.is_active_user})
