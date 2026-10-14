from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# hide_parameters: a database error's message names the SQL but not the values bound to it
# (an email, a password hash, a profile's tags). PostgreSQL's own DETAIL line can still hold
# a row's values; main.py's database error handler keeps that message out of the log.
ENGINE_OPTIONS = {"pool_pre_ping": True, "hide_parameters": True}

engine = create_engine(settings.DATABASE_URL, **ENGINE_OPTIONS)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
