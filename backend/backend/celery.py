import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

app = Celery('backend')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@app.task(name='backend.celery_healthcheck')
def celery_healthcheck() -> str:
    """Verify the broker, worker, and result backend are connected."""
    return 'ok'
