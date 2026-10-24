import os

os.environ["APP_SECRET_KEY"] = "test-app-secret-key-not-for-production-000000"
os.environ["DATABASE_BACKEND"] = "sqlite"
os.environ["SQLITE_FILE_NAME"] = ":memory:"
