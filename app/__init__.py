from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from celery import Celery, Task
from config import Config
import pytz

db = SQLAlchemy()
login = LoginManager()
login.login_view = 'main.login'

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login.init_app(app)

    # Initialize Celery
    app.config.from_mapping(
        CELERY=dict(
            broker_url=app.config['CELERY_BROKER_URL'],
            result_backend=app.config['CELERY_RESULT_BACKEND'],
            task_ignore_result=True,
        ),
    )
    celery_init_app(app)
    app.jinja_env.globals['pytz'] = pytz

    from app import routes
    app.register_blueprint(routes.bp)

    return app

def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    
    # Configure Beat schedule from config
    celery_app.conf.beat_schedule = app.config.get('CELERY_BEAT_SCHEDULE', {})
    celery_app.conf.timezone = 'UTC'
    
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app