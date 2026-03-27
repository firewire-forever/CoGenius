from celery import Celery, Task
from flask import Flask

def create_celery(app: Flask) -> Celery:
    """
    Factory function to create and configure a Celery object.
    It ensures that tasks run within the Flask application context.
    """
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app 