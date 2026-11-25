"""
WSGI config for Football project.

It exposes the WSGI callable as a module-level variable named ``application``.
For Vercel deployment, ``app`` alias is also exposed.
"""

import os
import sys

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')

application = get_wsgi_application()
app = application

# Automatically apply pending migrations on Vercel/cloud cold start
if os.environ.get('VERCEL') or os.environ.get('DATABASE_URL'):
    try:
        from django.core.management import call_command
        call_command('migrate', interactive=False, verbosity=0)
    except Exception as exc:
        print(f"Auto-migration warning: {exc}", file=sys.stderr)
