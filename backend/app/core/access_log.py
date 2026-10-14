"""The web server's access log, without query strings (step 8).

uvicorn prints one line per request on the "uvicorn.access" logger: the client address, the
method, the path WITH its query string, the HTTP version and the status. A query string can
hold the user's own words (the catalog's /api/catalog?search=...), so this filter drops
everything after "?" before the line is printed.

Fail closed: a record that isn't uvicorn's access line (its format string and its five
arguments, as in uvicorn 0.53's protocols/http/*_impl.py) is dropped, never printed.
"""

import logging

ACCESS_LOGGER = "uvicorn.access"
ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'


class DropQueryString(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if record.msg != ACCESS_FORMAT or not (isinstance(args, tuple) and len(args) == 5):
            return False
        client, method, path, http_version, status = args
        if not isinstance(path, str):
            return False
        record.args = (client, method, path.split("?", 1)[0], http_version, status)
        return True


def install() -> None:
    """Add the filter to uvicorn's access logger, once. uvicorn configures its loggers before
    it imports the app, and dictConfig keeps a logger's filters, so this stays in place."""
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, DropQueryString) for f in logger.filters):
        logger.addFilter(DropQueryString())
