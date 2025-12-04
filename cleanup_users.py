from app import create_app, db
from app.models import User, Campaign, Email, SMTPSettings, ClickEvent

# --- CONFIGURATION ---
EMAIL_TO_KEEP = "info@qbaccountingpro.com"  # <--- REPLACE THIS
# ---------------------

app = create_app()

with app.app_context():
    print(f"🛡️  Preserving user: {EMAIL_TO_KEEP}")
    print("🧹 Starting cleanup...")

    # Find all users EXCEPT the one we want to keep
    users_to_delete = User.query.filter(User.email != EMAIL_TO_KEEP).all()

    if not users_to_delete:
        print("✓ No other users found to delete.")
        exit()

    for user in users_to_delete:
        print(f"   - Deleting user: {user.username} ({user.email})...")

        # 1. Delete SMTP Settings
        if user.smtp_settings:
            db.session.delete(user.smtp_settings)

        # 2. Delete Campaigns and their Emails
        for campaign in user.campaigns:
            # Delete Emails associated with this campaign
            # (We need to iterate to delete ClickEvents first if they exist)
            emails = Email.query.filter_by(campaign_id=campaign.id).all()
            for email in emails:
                # Delete any click tracking events for this email
                ClickEvent.query.filter_by(email_id=email.id).delete()
                # Delete the email itself
                db.session.delete(email)

            # Delete the campaign
            db.session.delete(campaign)

        # 3. Delete the User
        db.session.delete(user)

    # Commit all changes to the database
    try:
        db.session.commit()
        print(f"\n✅ Successfully deleted {len(users_to_delete)} users and their data.")
    except Exception as e:
        db.session.rollback()
        print(f"\n❌ Error during deletion: {e}")