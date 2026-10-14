# Capacity Connect (SIH26075)
Flask + SQLite + Bootstrap + Chart.js learning platform.

## Run
    pip install -r requirements.txt
    python app.py        # open http://127.0.0.1:5000

The database and 5 demo courses are created automatically on first run.

Demo logins: trainer@demo.com / trainer123, trainee@demo.com / trainee123, admin@demo.com / admin123

## Deploy on Render
Build: `pip install -r requirements.txt`  Start: `gunicorn app:app`  Env var: `SECRET_KEY`
(Note: SQLite on Render's free tier is not persistent across deploys.)
