#!/bin/sh
set -e
alembic upgrade head
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
