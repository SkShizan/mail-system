from app import create_app, db
from app.models import User

app = create_app()

with app.app_context():
    # REPLACE 'your-email@example.com' WITH THE USER'S EMAIL
    target_email = "shizankhan011@gmail.com"

    user = User.query.filter_by(email=target_email).first()

    if user:
        user.is_admin = True
        user.is_active_user = True  # Ensure they are also active
        user.is_verified = True     # Ensure they are verified
        db.session.commit()
        print(f"✅ Success! User '{user.username}' ({target_email}) is now a Super Admin.")
    else:
        print(f"❌ Error: User with email '{target_email}' not found.")