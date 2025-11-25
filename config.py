import os
from dotenv import load_dotenv
from celery.schedules import crontab

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Celery Configuration
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL') or 'redis://localhost:6379/0'
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND') or 'redis://localhost:6379/0'
    
    # Celery Beat Schedule
    CELERY_BEAT_SCHEDULE = {
        'check-every-10-seconds': {
            'task': 'app.tasks.scheduler_dispatcher',
            'schedule': 10.0,
        },
    }