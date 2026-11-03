import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Football.settings')
django.setup()

from django.template.loader import get_template

def check():
    templates_to_test = [
        'organizer_index.html',
        'user_dashboard.html',
        'team.html',
        'fixture_generator.html'
    ]
    for t_name in templates_to_test:
        try:
            tmpl = get_template(t_name)
            print(f"[OK] {t_name} parsed successfully")
        except Exception as e:
            print(f"[ERROR] {t_name} failed: {e}")
            raise e

if __name__ == '__main__':
    check()
