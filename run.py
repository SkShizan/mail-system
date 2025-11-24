from app import create_app, db
from app.email_sender import start_scheduler

app = create_app()

# Create DB tables if they don't exist
with app.app_context():
    db.create_all()

# Start the scheduler
start_scheduler(app)

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False) # use_reloader=False to prevent scheduler running twice
