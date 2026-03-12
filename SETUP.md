# Book Club App — Setup

## Prerequisites
- Python 3.12+
- Docker & Docker Compose (for Postgres)
- A Google Cloud project with OAuth 2.0 credentials

## 1. Google OAuth Setup
1. Go to https://console.cloud.google.com/apis/credentials
2. Create an **OAuth 2.0 Client ID** (Web application)
3. Add `http://localhost:8000/auth/callback` as an authorized redirect URI
4. Copy the Client ID and Client Secret

## 2. Environment
```bash
cp .env.example .env
# Edit .env and fill in GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY
```

Generate a SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## 3. Install dependencies
```bash
pip install -r requirements.txt
```

## 4. Start Postgres
```bash
docker-compose up db -d
```

## 5. Run database migrations
```bash
alembic upgrade head
```

## 6. Start the app
```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000 — the first user to sign in becomes admin.

## Or: run everything with Docker Compose
```bash
docker-compose up --build
```
Then run migrations once the app container is up:
```bash
docker-compose exec app alembic upgrade head
```

## Admin workflow
1. Sign in as admin → go to `/admin`
2. Create a new season (give it a name and page limit)
3. Share the URL with your book club members
4. The app auto-advances through states as everyone submits/votes
