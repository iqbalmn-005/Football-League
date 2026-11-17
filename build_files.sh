#!/usr/bin/env bash
# Build script for Vercel deployment
set -e

echo "=== FUTBOLIX VERCEL BUILD PIPELINE ==="

# 1. Install production dependencies
echo "Installing dependencies from requirements.txt..."
python3 -m pip install -r requirements.txt

# 2. Run migrations against PostgreSQL if DATABASE_URL is configured
if [ -n "$DATABASE_URL" ] || [ -n "$POSTGRES_URL" ]; then
    echo "Running Django migrations against production PostgreSQL..."
    python3 manage.py migrate --noinput
else
    echo "DATABASE_URL not set in build environment. Skipping build-time migrations."
fi

# 3. Collect static files
echo "Collecting static assets..."
python3 manage.py collectstatic --noinput --clear

echo "=== BUILD PIPELINE COMPLETED SUCCESSFULLY ==="
