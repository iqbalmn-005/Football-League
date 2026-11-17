"""
Django settings for Football project.
FUTBOLIX - Football Tournament and League Management Platform.
"""

from pathlib import Path
import os

try:
    import dj_database_url
except ImportError:
    dj_database_url = None

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Detect Vercel environment
IS_VERCEL = 'VERCEL' in os.environ

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-m3^r7y-^e+4*h(l^ip!zm6%bgb&c@awzt&931h(*2+t#ix2ghg')

# SECURITY WARNING: don't run with debug turned on in production!
DEFAULT_DEBUG = 'False' if IS_VERCEL else 'True'
DEBUG = os.environ.get('DJANGO_DEBUG', DEFAULT_DEBUG).lower() in ('true', '1', 'yes')

# ALLOWED_HOSTS
allowed_hosts_env = os.environ.get('DJANGO_ALLOWED_HOSTS')
if allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_env.split(',') if h.strip()]
else:
    ALLOWED_HOSTS = ['192.168.29.3', 'localhost', '127.0.0.1', 'testserver', '.vercel.app', '.now.sh', 'futbolix.vercel.app']

vercel_url = os.environ.get('VERCEL_URL')
if vercel_url:
    clean_vercel_host = vercel_url.replace('https://', '').replace('http://', '').strip('/')
    if clean_vercel_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(clean_vercel_host)

if DEBUG and '*' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('*')

# CSRF_TRUSTED_ORIGINS
csrf_origins_env = os.environ.get('CSRF_TRUSTED_ORIGINS')
if csrf_origins_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_origins_env.split(',') if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = [
        'https://*.vercel.app',
        'https://futbolix.vercel.app',
        'http://localhost:8000',
        'http://127.0.0.1:8000',
    ]

if vercel_url:
    clean_host = vercel_url.replace('https://', '').replace('http://', '').strip('/')
    https_origin = f"https://{clean_host}"
    if https_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(https_origin)

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'leagues',
    'teams',
    'matches',
    'standings',
    'fixtures',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'Football.middleware.CustomErrorPageMiddleware',
]

ROOT_URLCONF = 'Football.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'front', BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'Football.wsgi.application'

# Database
# Production (Neon / Supabase / Heroku / Render) via DATABASE_URL or POSTGRES_URL
# Local development seamlessly defaults to SQLite when DATABASE_URL is not provided
DEFAULT_NEON_URL = 'postgresql://neondb_owner:npg_Dvl0kOqrfXt6@ep-dry-sea-bd7aiz6i-pooler.c-8.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
DATABASE_URL = os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL') or os.environ.get('POSTGRESQL_URL')

# Safe fallback for Vercel if environment variable hasn't been added yet
if not DATABASE_URL and IS_VERCEL:
    DATABASE_URL = DEFAULT_NEON_URL

if DATABASE_URL and dj_database_url:
    conn_max_age = int(os.environ.get('DJANGO_CONN_MAX_AGE', '0' if IS_VERCEL else '600'))
    db_config = dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=conn_max_age,
        conn_health_checks=True,
    )
    # Ensure sslmode=require for cloud providers (Neon, Supabase)
    if any(provider in DATABASE_URL.lower() for provider in ['neon.tech', 'supabase.co', 'sslmode=require']):
        db_config.setdefault('OPTIONS', {})
        db_config['OPTIONS']['sslmode'] = 'require'
    DATABASES = {
        'default': db_config
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Authentication Backends
AUTHENTICATION_BACKENDS = [
    'accounts.backends.PhoneOrUsernameBackend',
    'django.contrib.auth.backends.ModelBackend',
]

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Production Security & SSL Forwarding
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
