BROKER_VHOST = "/"
CELERY_RESULT_BACKEND = "amqp"
CELERY_IMPORTS = ("lp.services.job.celery", )
CELERYD_LOG_LEVEL = 'INFO'
CELERYD_CONCURRENCY = 1
