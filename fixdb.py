from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    try:
        with db.engine.connect() as conn:
            # Add the missing column
            conn.execute(
                text("ALTER TABLE email ADD COLUMN clicked_at TIMESTAMP"))
            conn.commit()
        print("✅ Successfully added 'clicked_at' column to 'email' table.")
    except Exception as e:
        print(f"❌ Error: {e}")
        # It might fail if the column already exists or if there's a connection issue
