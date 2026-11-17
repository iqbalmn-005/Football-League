"""
WSGI config for Football project.

It exposes the WSGI callable as a module-level variable named ``application``.
For Vercel deployment, ``app`` alias is also exposed.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')

application = get_wsgi_application()
app = application
