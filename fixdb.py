from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    try:
        with db.engine.connect() as conn:
            # Add new columns safely
            conn.execute(text("ALTER TABLE email ADD COLUMN open_user_agent TEXT"))
            conn.execute(text("ALTER TABLE email ADD COLUMN open_ip_address VARCHAR(50)"))
            conn.execute(text("ALTER TABLE email ADD COLUMN bot_detected_at TIMESTAMP"))
            conn.commit()
        print("✅ Database successfully updated with protection columns.")
    except Exception as e:
        print(f"ℹ️ Info (might already exist): {e}")