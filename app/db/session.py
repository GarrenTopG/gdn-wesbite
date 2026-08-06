from sqlmodel import SQLModel, Session, create_engine

# SQLite database file path
sqlite_file_name = "aurorah.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# connect_args={"check_same_thread": False} is required for SQLite with FastAPI
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})


def create_db_and_tables():
    """Initializes and creates all database tables."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency injector for database sessions in FastAPI endpoints."""
    with Session(engine) as session:
        yield session