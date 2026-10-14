"""Per-user rolling limits (10 a minute, 100 a day; templates 30 and 300) and the one
generation slot."""

from app.services.chat import chat_config as cfg
from app.services.chat.limits import ChatLimits, GenerationSlot, RateLimiter


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_the_configured_limits():
    assert cfg.RATE_LIMITS == ((60, 10), (86400, 100)) and cfg.MAX_CONCURRENT_GENERATIONS == 1
    assert cfg.TEMPLATE_RATE_LIMITS == ((60, 30), (86400, 300))


def test_templates_and_the_model_count_separately():
    limits = ChatLimits()
    assert limits.rate.limits == cfg.RATE_LIMITS and limits.template_rate.limits == cfg.TEMPLATE_RATE_LIMITS
    for _ in range(10):
        limits.rate.hit("u1")
    assert limits.rate.hit("u1") is not None
    assert all(limits.template_rate.hit("u1") is None for _ in range(30))
    assert limits.template_rate.hit("u1") is not None and limits.rate.hit("u2") is None


def test_ten_a_minute_then_the_wait_until_the_oldest_leaves_the_window():
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    for _ in range(10):
        assert limiter.hit("u1") is None
        clock.now += 2
    assert limiter.hit("u1") == 40  # the first was at 1000; it leaves the window at 1060; now 1020
    clock.now = 1059.5
    assert limiter.hit("u1") == 1  # never 0
    clock.now = 1060.0
    assert limiter.hit("u1") is None


def test_a_refused_request_is_not_counted():
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    for _ in range(10):
        limiter.hit("u1")
    for _ in range(50):
        assert limiter.hit("u1") is not None
    clock.now += 60
    assert all(limiter.hit("u1") is None for _ in range(10))


def test_a_hundred_a_day():
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    for _ in range(100):
        assert limiter.hit("u1") is None
        clock.now += 61  # never the per-minute limit
    assert clock.now == 7100
    assert limiter.hit("u1") == 1000 + 86400 - 7100  # until the first leaves the 24-hour window
    clock.now = 1000 + 86400
    assert limiter.hit("u1") is None


def test_users_are_limited_separately():
    limiter = RateLimiter(clock=Clock())
    for _ in range(10):
        limiter.hit("u1")
    assert limiter.hit("u1") is not None and limiter.hit("u2") is None


def test_one_generation_at_a_time():
    slot = GenerationSlot()
    assert slot.try_acquire() and not slot.try_acquire()
    slot.release()
    assert slot.try_acquire()
    slot.release()
    slot.release()  # a stray release never makes room for two
    assert slot.try_acquire() and not slot.try_acquire()
