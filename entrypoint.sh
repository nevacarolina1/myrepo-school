#!/bin/sh
# entrypoint.sh
gunicorn --bind :3000 --workers 2 main:monitor &
watchmedo auto-restart --patterns="*.py" --recursive -- python main.py
