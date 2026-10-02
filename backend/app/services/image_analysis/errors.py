class ImageRejected(Exception):
    """The photo can't be analysed reliably. `issues` are user-facing reasons.

    The API turns this into HTTP 422 with {"quality": {"ok": false, "issues": [...]}}
    and no scores — a rejected photo never gets made-up numbers.
    """

    def __init__(self, issues: list[str]):
        super().__init__("; ".join(issues))
        self.issues = list(issues)


class ModelUnavailable(RuntimeError):
    """A required model file is missing or failed to load. The API returns HTTP 503."""
