"""Step 8: what the server's logs can't contain.

- uvicorn's access log loses every query string (catalog searches put the user's words
  there), and a line it doesn't recognise is dropped, not printed.
- The engine hides bound parameters, and a database error is logged as its class and
  constraint name only: PostgreSQL's own message (DETAIL: "Key (email)=(...)", "Failing row
  contains (...)") holds the row's values, which hide_parameters doesn't cover.
"""

import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import main
from app.core import access_log, database

ACCESS_ARGS = ("127.0.0.1:50123", "GET", "/api/catalog?search=my+secret+words&page=2", "1.1", 200)


def access_record(msg=access_log.ACCESS_FORMAT, args=ACCESS_ARGS) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, msg, args, None)


# --------------------------------------------------------------------------------------
# The access log
# --------------------------------------------------------------------------------------


def test_the_query_string_is_dropped():
    record = access_record()
    assert access_log.DropQueryString().filter(record) is True
    assert record.getMessage() == '127.0.0.1:50123 - "GET /api/catalog HTTP/1.1" 200'


def test_a_path_without_a_query_string_is_unchanged():
    record = access_record(args=("127.0.0.1:50123", "POST", "/api/chat", "1.1", 429))
    assert access_log.DropQueryString().filter(record) is True
    assert record.getMessage() == '127.0.0.1:50123 - "POST /api/chat HTTP/1.1" 429'


@pytest.mark.parametrize(("msg", "args"), [
    ('%s "%s %s"', ACCESS_ARGS[:3]),  # another format
    (access_log.ACCESS_FORMAT, ACCESS_ARGS[:4]),  # missing an argument
    (access_log.ACCESS_FORMAT, ACCESS_ARGS + ("extra",)),
    (access_log.ACCESS_FORMAT, ("127.0.0.1", "GET", b"/api/catalog?search=x", "1.1", 200)),  # path not text
    ("request %s", ("/api/catalog?search=x",)),
])
def test_a_line_that_isnt_uvicorns_access_line_is_dropped(msg, args):
    assert access_log.DropQueryString().filter(access_record(msg, args)) is False


def test_the_app_installs_the_filter_once_and_it_works_through_uvicorns_formatter(caplog):
    from uvicorn.logging import AccessFormatter

    access_log.install()  # main.py already did, at import
    logger = logging.getLogger(access_log.ACCESS_LOGGER)
    assert sum(isinstance(f, access_log.DropQueryString) for f in logger.filters) == 1
    caplog.set_level(logging.INFO, logger=access_log.ACCESS_LOGGER)
    logger.info(access_log.ACCESS_FORMAT, *ACCESS_ARGS)
    logger.info("not an access line %s", "/api/catalog?search=my+secret+words")
    assert len(caplog.records) == 1 and "secret" not in caplog.text
    line = AccessFormatter(fmt="%(client_addr)s %(request_line)s %(status_code)s", use_colors=False).format(caplog.records[0])
    assert line == "127.0.0.1:50123 GET /api/catalog HTTP/1.1 200 OK"


# --------------------------------------------------------------------------------------
# Database errors
# --------------------------------------------------------------------------------------


def test_the_engine_hides_bound_parameters():
    assert database.ENGINE_OPTIONS["hide_parameters"] is True
    assert database.engine.hide_parameters is True


@pytest.fixture
def private_engine(migrated_db):
    """The throwaway database, through an engine with the app's own options."""
    engine = create_engine(migrated_db.url, **database.ENGINE_OPTIONS)
    yield engine
    engine.dispose()


def duplicate_email(engine, email):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email, hashed_password) VALUES (:e, 'x')"), {"e": email})
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email, hashed_password) VALUES (:e, 'x')"), {"e": email})


def out_of_range_score(engine, tag):
    with engine.begin() as conn:
        user = conn.execute(text("INSERT INTO users (email, hashed_password) VALUES (:e, 'x') RETURNING id"),
                            {"e": f"{tag}@example.com"}).scalar_one()
        conn.execute(text("INSERT INTO skin_profiles (user_id, acne_score, redness_score, wrinkle_score, "
                          "pigmentation_score, pore_score, questionnaire_tags) "
                          "VALUES (:u, 150, 30, 30, 30, 30, CAST(:t AS jsonb))"),
                     {"u": user, "t": f'{{"probe": "{tag}"}}'})


def test_hidden_parameters_are_not_enough_on_their_own(private_engine):
    """Why main.py has a database error handler: the parameters are hidden, but PostgreSQL's
    own DETAIL line still names the value."""
    email = f"dup-{uuid.uuid4().hex[:10]}@example.com"
    with pytest.raises(IntegrityError) as caught:
        duplicate_email(private_engine, email)
    assert "SQL parameters hidden" in str(caught.value)
    assert email in str(caught.value)  # in the DETAIL line


@pytest.mark.parametrize("trigger", [duplicate_email, out_of_range_score], ids=["unique", "check"])
def test_a_database_error_is_logged_without_its_values(private_engine, caplog, trigger):
    tag = f"probe-{uuid.uuid4().hex[:10]}"
    app = FastAPI()
    app.add_exception_handler(SQLAlchemyError, main.database_error_handler)

    @app.post("/boom")
    def boom():
        trigger(private_engine, f"{tag}@example.com" if trigger is duplicate_email else tag)

    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.WARNING, logger="sqlalchemy")
    response = TestClient(app).post("/boom")
    assert response.status_code == 500 and response.json() == {"detail": "Internal Server Error"}
    assert tag not in response.text and tag not in caplog.text
    assert "Failing row" not in caplog.text and "Key (" not in caplog.text
    assert "Database error on POST /boom: IntegrityError (constraint " in caplog.text


def test_the_app_registers_the_database_error_handler():
    assert main.app.exception_handlers[SQLAlchemyError] is main.database_error_handler
