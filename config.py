import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'

    # DIRECTLY set the URL here to force Supabase
    # Ensure you replace 'postgres://' with 'postgresql://' if needed (SQLAlchemy sometimes requires the 'ql')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'postgresql://localhost/nexus'

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Celery Configuration
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL') or 'redis://localhost:6379/0'
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND') or 'redis://localhost:6379/0'
    CELERYD_CONCURRENCY = 4  # Reduced from 8 to respect SMTP rate limits

    CELERY_BEAT_SCHEDULE = {
        'check-every-10-seconds': {
            'task': 'app.tasks.scheduler_dispatcher',
            'schedule': 10.0,
        },
    }