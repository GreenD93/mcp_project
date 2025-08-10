export PYTHONDONTWRITEBYTECODE=1
uvicorn mail_sender:app --port 8003 --reload