from app import create_app

app = create_app()
celery = app.extensions["celery"]

# Import tasks to register them with Celery
from app import tasks