from app import db
from datetime import datetime

class SMTPSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    server = db.Column(db.String(120), default='smtp.gmail.com')
    port = db.Column(db.Integer, default=587)
    use_tls = db.Column(db.Boolean, default=True)
    username = db.Column(db.String(120))
    password = db.Column(db.String(120))
    default_sender = db.Column(db.String(120))
    signature = db.Column(db.Text, default='')

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    emails = db.relationship('Email', backref='campaign', lazy=True)

class Email(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending') # pending, sent, failed
    scheduled_time = db.Column(db.DateTime, default=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now)
    batch_id = db.Column(db.String(50), nullable=True) # For grouping bulk emails
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=True)

    def __repr__(self):
        return f'<Email {self.id} to {self.recipient}>'
