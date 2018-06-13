"""
Django settings for ozp project.

Generated by 'django-admin startproject' using Django 1.8.2.

For more information on this file, see
https://docs.djangoproject.com/en/1.8/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.8/ref/settings/
"""

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
import os
import datetime

from ozpcenter.utils import str_to_bool


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.8/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'v%ue42rl)b*^6494!&1kd)dzfa--cs(#9#qwoe1p()hrjh#j9t'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# TODO: make this ['{{ api_fqdn}}', '{{ frontend_fqdn }}']
ALLOWED_HOSTS = ['*']

# Use nose to run all tests
TEST_RUNNER = 'django_nose.NoseTestSuiteRunner'

# OZP_LOG_LEVEL=CRITICAL
# Tell nose to measure coverage on the ozp, ozpcenter, ozpiwc  apps
NOSE_ARGS = [
    '--with-coverage',
    '--cover-html',
    '--cover-package=ozp,ozpcenter,ozpiwc,plugins',
    '--verbosity=2',
]

# Application definition

INSTALLED_APPS = (
    'django.contrib.admin',
    # put contenttypes above auth so that python manage.py flush works
    # correctly: https://code.djangoproject.com/ticket/9207
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'django_filters',
    'django_extensions',
    'rest_framework_swagger',
    'ozpcenter',
    'ozpiwc',
    'corsheaders',
)

# Note that CorsMiddleware needs to come before Django's CommonMiddleware if
# you are using Django's USE_ETAGS = True setting, otherwise the CORS headers
# will be lost from the 304 not-modified responses, causing errors in some
# browsers.
MIDDLEWARE_CLASSES = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.security.SecurityMiddleware',
)

ROOT_URLCONF = 'ozp.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ozp.wsgi.application'


# Database
# https://docs.djangoproject.com/en/1.8/ref/settings/#databases
MAIN_DATABASE = os.getenv('MAIN_DATABASE', 'sqlite')

if MAIN_DATABASE == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        }
    }
elif MAIN_DATABASE == 'psql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql_psycopg2',  # Add 'postgresql_psycopg2', 'mysql', 'sqlite3' or 'oracle'.
            'NAME': 'ozp',  # Or path to database file if using sqlite3.
            'USER': 'ozp_user',
            'PASSWORD': 'password',
            'HOST': '127.0.0.1',  # Empty for localhost through domain sockets or '127.0.0.1' for localhost through TCP.
            'PORT': '',  # Set to empty string for default.
        }
    }


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple'
        },
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': 'ozp.log',
            'formatter': 'json',
        }
    },
    'formatters': {
        'json': {
           '()': 'ozp.logging_formatter.CustomisedJSONFormatter', },
        'simple': {
            'format': '%(asctime)s - %(levelname)s - %(module)s - %(message)s'
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'WARNING'),
        },
        'PIL': {
            'handlers': ['console', 'file'],
            'level': os.getenv('PILLOW_LOG_LEVEL', 'WARNING'),
        },
        'ozp-center': {
            'handlers': ['console', 'file'],
            'level': os.getenv('OZP_LOG_LEVEL', 'INFO'),
        },
        'ozp-iwc': {
            'handlers': ['console', 'file'],
            'level': os.getenv('OZP_LOG_LEVEL', 'INFO'),
        }
    },
}

# http://docs.celeryproject.org/en/latest/userguide/configuration.html#configuration

# print('Currently using in-memory celery, please switch to different broker')
# CELERY_BROKER_URL = 'memory://localhost/'
# CELERY_RESULT_BACKEND = 'cache'
# CELERY_CACHE_BACKEND = 'memory'
# CELERY_ALWAYS_EAGER = True
# CELERY_EAGER_PROPAGATES_EXCEPTIONS = True
# CELERY_BROKER_BACKEND = 'memory'

CELERY_BROKER_URL = 'redis://localhost:6379/11'
# CELERY_BROKER_URL = 'amqp://guest:password@localhost:5672/'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/12'
# CELERY_RESULT_BACKEND = 'rpc://'
# CELERY_RESULT_BACKEND= 'elasticsearch://example.com:9200/index_name/doc_type'  # encoding issue

# http://docs.celeryproject.org/en/latest/userguide/calling.html#calling-serializers
CELERY_TASK_SERIALIZER = 'json'  # 'msgpack'
CELERY_RESULT_SERIALIZER = 'json'  # 'msgpack'
CELERY_ACCEPT_CONTENT = ['json', 'msgpack']
# CELERY_timezone = 'Europe/Oslo'
# CELERY_enable_utc = True

# Internationalization
# https://docs.djangoproject.com/en/1.8/topics/i18n/

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

REST_FRAMEWORK = {
    'EXCEPTION_HANDLER': 'ozpcenter.errors.exception_handler',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        # 'ozpcenter.auth.pkiauth.PkiAuthentication'
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework_jwt.authentication.JSONWebTokenAuthentication',
        # 'rest_framework.authentication.SessionAuthentication',
        ),
    # Use Django's standard `django.contrib.auth` permissions,
    # or allow read-only access for unauthenticated users.
    'DEFAULT_PERMISSION_CLASSES': (
        # 'rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly',
        'ozpcenter.permissions.IsUser',
    ),
    'DEFAULT_FILTER_BACKENDS': ('rest_framework.filters.DjangoFilterBackend',),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'DEFAULT_PARSER_CLASSES': (
        'ozpiwc.parsers.DataResourceParser',
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
        'rest_framework.renderers.StaticHTMLRenderer',
        'ozpiwc.renderers.RootResourceRenderer',
        'ozpiwc.renderers.UserResourceRenderer',
        'ozpiwc.renderers.SystemResourceRenderer',
        'ozpiwc.renderers.DataObjectResourceRenderer',
        'ozpiwc.renderers.DataObjectListResourceRenderer',
        'ozpiwc.renderers.ApplicationResourceRenderer',
        'ozpiwc.renderers.ApplicationListResourceRenderer',
        'ozpiwc.renderers.IntentResourceRenderer',
        'ozpiwc.renderers.IntentListResourceRenderer'
    )
}

# NOTE: In production or when developing with redis server, comment REDIS_CLIENT_CLASS line
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'localhost:6379',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'REDIS_CLIENT_CLASS': 'mockredis.mock_strict_redis_client',
            'COMPRESSOR': 'django_redis.compressors.lzma.LzmaCompressor',
            'SERIALIZER': 'django_redis.serializers.msgpack.MSGPackSerializer',
            # 'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
            # 'SERIALIZER': 'django_redis.serializers.json.JSONSerializer',
        }
    },
}

JWT_AUTH = {
    'JWT_EXPIRATION_DELTA': datetime.timedelta(days=7),
    'JWT_AUTH_COOKIE': 'jwt-token',
    'JWT_ISSUER': 'ozp-backend',
    'JWT_ALLOW_REFRESH': True,
}
# django-cors-headers
# TODO: lock this down in production
CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True

OZP = {
    'DEMO_APP_ROOT': 'https://localhost:8443',
    # if set to False, never try and update authorization-related info from
    # an external source
    'USE_AUTH_SERVER': False,
    # convert DNs read as /CN=My Name/OU=Something... to CN=My Name, OU=Something
    'PREPROCESS_DN': True,
    'OZP_AUTHORIZATION': {
        'SERVER_CRT': '/ozp/server.crt',
        'SERVER_KEY': '/ozp/server.key',
        # assumes the real URL is <root>/users/<DN>/
        'USER_INFO_URL': r'http://localhost:8003/demo-auth/users/%s/info.json?issuerDN=%s',
        # assumes the real URL is <root>/users/<DN>/groups/<PROJECT_NAME>/
        'USER_GROUPS_URL': r'http://localhost:8003/demo-auth/users/%s/groups/%s/',
        # name of the group in the auth service for apps mall stewards
        'APPS_MALL_STEWARD_GROUP_NAME': 'OZP_APPS_MALL_STEWARD',
        # name of the group in the auth service for org stewards
        'ORG_STEWARD_GROUP_NAME': 'OZP_ORG_STEWARD',
        # name of the group in the auth service for metrics users
        'METRICS_GROUP_NAME': 'OZP_METRICS_USER',
        # name of the group in the auth service for beta users
        'BETA_USER_GROUP_NAME': 'OZP_BETA_USER',
        # name of the project in the auth serice
        'PROJECT_NAME': 'OZP',
        # seconds to treat cached authorization data as valid before trying to
        # update it
        # max value: 60*60*24 (1 day)
        'SECONDS_TO_CACHE_DATA': 5
    }
}

# Plugin Info
ACCESS_CONTROL_PLUGIN = 'default_access_control'
AUTHORIZATION_PLUGIN = 'default_authorization'

# Set to empty string if no default agency exists
# If a default agency exists, set it to the agency's short name
DEFAULT_AGENCY = ''

# Number of seconds to cache data
GLOBAL_SECONDS_TO_CACHE_DATA = 60 * 60 * 24  # 24 Hours

# Boolean to enable/disable the use Elasticsearch use
ES_ENABLED = str_to_bool(os.getenv('ES_ENABLED', False))  # This needs to be false for unit test to pass
ES_INDEX_NAME = 'appsmall'
ES_TYPE_NAME = 'listings'
ES_ID_FIELD = 'id'
ES_RECOMMEND_USER = 'es_recommend_user'
ES_RECOMMEND_CONTENT = 'es_recommend_content'
ES_RECOMMEND_TYPE = 'recommend'

ES_NUMBER_OF_SHARDS = 1
ES_NUMBER_OF_REPLICAS = 0

ES_HOST = [{
    "host": "localhost",
    "port": 9200
}]

ES_BASIC_AUTH = str_to_bool(os.getenv('ES_BASIC_AUTH', False))
ES_AUTH_USERNAME = os.getenv('ES_AUTH_USERNAME', 'user')
ES_AUTH_PASSWORD = os.getenv('ES_AUTH_PASSWORD', 'password')

# Email Settings
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
# 'django.core.mail.backends.console.EmailBackend'
# 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_FILE_PATH = 'test_email_msg' # change this to a proper location

EMAIL_PORT = 1025
# EMAIL_HOST localhost
# EMAIL_HOST_PASSWORD
# EMAIL_HOST_USER
# EMAIL_SSL_CERTFILE None
# EMAIL_SSL_KEYFILE None
# EMAIL_SUBJECT_PREFIX [Django]
# EMAIL_TIMEOUT None
# EMAIL_USE_SSL False
# EMAIL_USE_TLS False

# https://docs.djangoproject.com/en/1.8/ref/templates/language/#templates
# Template Vars
# non_emailed_count = Number of Notifications
EMAIL_FROM_FIELD = 'admin@app.com'
EMAIL_SUBJECT_FIELD_TEMPLATE = '{{ non_emailed_count }} New Notifications'
EMAIL_BODY_FIELD_TEMPLATE = '''Welcome to App Site

You have {{ non_emailed_count }} new notifications

You have received this email because you have subscribed to Notifications
You can disabling these Notifications by logging into Center and disable Email Notifications in profile page
'''


# AWS settings
AWS_STORAGE_BUCKET_NAME = 'ozp-static'
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID', 'MISSING AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', 'MISSING AWS_SECRET_ACCESS_KEY')

# Tell django-storages that when coming up with the URL for an item in S3 storage, keep
# it simple - just use this domain plus the path. (If this isn't set, things get complicated).
# This controls how the `static` template tag from `staticfiles` gets expanded, if you're using it.
# We also use it in the next setting.
# AWS_S3_HOST =
AWS_S3_SECURE_URLS = False
AWS_S3_CUSTOM_DOMAIN = '{}.s3-website-us-east-1.amazonaws.com'.format(AWS_STORAGE_BUCKET_NAME)

# This is used by the `static` template tag from `static`, if you're using that. Or if anything else
# refers directly to STATIC_URL. So it's safest to always set it.
# STATIC_URL = "http://%s/" % AWS_S3_CUSTOM_DOMAIN
# STATIC_ROOT is the absolute path to the folder within which static files will
#   be collected by the staticfiles application
STATIC_ROOT = os.path.join(BASE_DIR, 'static/')

# STATIC_URL is the relative browser URL to be used when accessing static files
#   from the browser

STATIC_URL = '/static/'
#
# if not DEBUG:
# Tell the staticfiles app to use S3Boto storage when writing the collected static files (when
# you run `collectstatic`).
# STATICFILES_STORAGE = 'storages.backends.s3boto.S3BotoStorage'


# for details regarding media vs static files:
#   http://timmyomahony.com/blog/static-vs-media-and-root-vs-path-in-django/

# For S3 - ozp.storage.MediaS3Storage
# For File System - ozp.storage.MediaFileStorage
DEFAULT_MEDIA_FILE_STORAGE = os.getenv('DEFAULT_MEDIA_FILE_STORAGE', 'ozp.storage.MediaFileStorage')

# MEDIA_ROOT is the absolute path to the folder that will hold user uploads
AWS_MEDIA_STORAGE_BUCKET_NAME = 'ozp-media'
AWS_MEDIA_S3_CUSTOM_DOMAIN = '{}.s3-website-us-east-1.amazonaws.com'.format(AWS_MEDIA_STORAGE_BUCKET_NAME)
AWS_MEDIA_DEFAULT_ACL = 'private'  # http://docs.aws.amazon.com/AmazonS3/latest/dev/acl-overview.html
# AWS_MEDIA_S3_CUSTOM_DOMAIN = None  # Make AWS_MEDIA_S3_CUSTOM_DOMAIN to None to get Presigned URLS
MEDIA_ROOT = os.path.join(BASE_DIR, 'media/')
# AWS_QUERYSTRING_AUTH = False
# AWS_S3_SIGNATURE_VERSION = 's3v4'  # Presigned URLs

# MEDIA_URL is the relative browser URL to be used when accessing media files
#   from the browser
MEDIA_URL = 'media/'

#  Web Socket Service URL (aml-ws-service)
WS_ENABLE = str_to_bool(os.getenv('WS_ENABLE', False))
WS_URL = os.getenv('WS_URL', 'http://127.0.0.1:4200')
