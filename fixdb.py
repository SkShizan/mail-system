from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("🔄 Updating database schema...")

    with db.engine.connect() as conn:
        # 1. Add 'is_verified' column
        try:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN is_verified BOOLEAN DEFAULT FALSE'))
            print("✅ Added column: is_verified")
        except Exception as e:
            print(f"ℹ️  Column 'is_verified' might already exist or error: {e}")

        # 2. Add 'otp_code' column
        try:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN otp_code VARCHAR(6)'))
            print("✅ Added column: otp_code")
        except Exception as e:
            print(f"ℹ️  Column 'otp_code' might already exist or error: {e}")

        # 3. Add 'is_admin' column
        try:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN is_admin BOOLEAN DEFAULT FALSE'))
            print("✅ Added column: is_admin")
        except Exception as e:
            print(f"ℹ️  Column 'is_admin' might already exist or error: {e}")

        # 4. Add 'is_active_user' column
        try:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN is_active_user BOOLEAN DEFAULT FALSE'))
            print("✅ Added column: is_active_user")
        except Exception as e:
            print(f"ℹ️  Column 'is_active_user' might already exist or error: {e}")

        # 5. Add 'valid_until' column
        try:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN valid_until TIMESTAMP'))
            print("✅ Added column: valid_until")
        except Exception as e:
            print(f"ℹ️  Column 'valid_until' might already exist or error: {e}")

        conn.commit()

    print("\n🎉 Database update complete! You can now restart your server.")