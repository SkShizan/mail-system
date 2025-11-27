from app import db
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))

    # Relationships
    campaigns = db.relationship('Campaign', backref='owner', lazy=True)
    smtp_settings = db.relationship('SMTPSettings', backref='owner', uselist=False, lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class SMTPSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # Linked to User
    server = db.Column(db.String(120), default='smtp.gmail.com')
    port = db.Column(db.Integer, default=587)
    use_tls = db.Column(db.Boolean, default=True)
    username = db.Column(db.String(120))
    password = db.Column(db.String(120))
    default_sender = db.Column(db.String(120))
    signature = db.Column(db.Text, default='')

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # Linked to User
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    emails = db.relationship('Email', backref='campaign', lazy=True)

class Email(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')
    scheduled_time = db.Column(db.DateTime, default=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now)
    batch_id = db.Column(db.String(50), nullable=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=True)
    rate_limit_retry_at = db.Column(db.DateTime, nullable=True)
    tracking_id = db.Column(db.String(50), unique=True, nullable=True)
    opened_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<Email {self.id} to {self.recipient}>'