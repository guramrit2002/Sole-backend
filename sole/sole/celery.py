import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sole.settings')

app = Celery('sole')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
