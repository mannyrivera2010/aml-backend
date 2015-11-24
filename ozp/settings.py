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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.8/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'v%ue42rl)b*^6494!&1kd)dzfa--cs(#9#qwoe1p()hrjh#j9t'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = (
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'django_extensions',
    'rest_framework_swagger',
    'ozpcenter',
    'ozpiwc',
    'corsheaders'
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

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        }
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
        },
        'ozp-center': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
        'ozp-iwc': {
            'handlers': ['console'],
            'level': 'DEBUG',
        }
    },
}

# Internationalization
# https://docs.djangoproject.com/en/1.8/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

# for details regarding media vs static files:
#   http://timmyomahony.com/blog/static-vs-media-and-root-vs-path-in-django/

# STATIC_ROOT is the absolute path to the folder within which static files will
#   be collected by the staticfiles application
STATIC_ROOT = os.path.join(BASE_DIR, 'static/')

# STATIC_URL is the relative browser URL to be used when accessing static files
#   from the browser
STATIC_URL = '/static/'

# MEDIA_ROOT is the absolute path to the folder that will hold user uploads
MEDIA_ROOT = os.path.join(BASE_DIR, 'media/')

# MEDIA_URL is the relative browser URL to be used when accessing media files
#   from the browser
MEDIA_URL='media/'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        #'ozpcenter.auth.pkiauth.PkiAuthentication'
        'rest_framework.authentication.BasicAuthentication'
        # 'rest_framework.authentication.SessionAuthentication',
    , ),
    # Use Django's standard `django.contrib.auth` permissions,
    # or allow read-only access for unauthenticated users.
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly',
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

# NOTE: In production, change this to memcached
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        'TIMEOUT': 300, # 5 minutes
        'OPTIONS': {
            'MAX_ENTRIES': 10000
        }
    }
}

# django-cors-headers
# TODO: lock this down in production
CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True

OZP = {
    # if set to False, never try and update authorization-related info from
    # an external source
    'USE_AUTH_SERVER': False,
    'DN_SEPARATOR': r'/',
    'OZP_AUTHORIZATION': {
        # assumes the real URL is <root>/users/<DN>/
        'USER_INFO_URL': r'http://localhost:8000/demo-auth/users/%s/info.json?issuerDN=%s',
        # assumes the real URL is <root>/users/<DN>/groups/<PROJECT_NAME>/
        'USER_GROUPS_URL': r'http://localhost:8000/demo-auth/users/%s/groups/%s/',
        # name of the group in the auth service for apps mall stewards
        'APPS_MALL_STEWARD_GROUP_NAME': 'OZP_APPS_MALL_STEWARD',
        # name of the group in the auth service for org stewards
        'ORG_STEWARD_GROUP_NAME': 'OZP_ORG_STEWARD',
        # name of the group in the auth service for metrics users
        'METRICS_GROUP_NAME': 'OZP_METRICS_USER',
        # name of the project in the auth serice
        'PROJECT_NAME': 'OZP',
        # seconds to treat cached authorization data as valid before trying to
        # update it
        # max value: 60*60*24 (1 day)
        'SECONDS_TO_CACHE_DATA': 5
    }
}
