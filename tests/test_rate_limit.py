from app.whatsapp.rate_limit import Decision, RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(max_messages: int = 3, window: float = 60.0, **kw) -> tuple[RateLimiter, Clock]:
    clock = Clock()
    return RateLimiter(max_messages, window, clock=clock, **kw), clock


def test_allows_up_to_the_limit_then_notifies_once_then_drops():
    limiter, _ = make()
    assert [limiter.check("a") for _ in range(3)] == [Decision.ALLOW] * 3
    assert limiter.check("a") is Decision.NOTIFY
    assert [limiter.check("a") for _ in range(5)] == [Decision.DROP] * 5


def test_window_slides_and_allows_again():
    limiter, clock = make()
    for _ in range(3):
        limiter.check("a")
    assert limiter.check("a") is Decision.NOTIFY
    clock.now += 60
    assert limiter.check("a") is Decision.ALLOW


def test_customers_are_independent():
    limiter, _ = make(max_messages=1)
    assert limiter.check("a") is Decision.ALLOW
    assert limiter.check("a") is Decision.NOTIFY
    assert limiter.check("b") is Decision.ALLOW


def test_rejected_messages_do_not_extend_the_block():
    limiter, clock = make(max_messages=2, window=60)
    limiter.check("a"); limiter.check("a")          # t=1000, limit reached
    for _ in range(20):                              # spamming while blocked
        clock.now += 2
        limiter.check("a")
    clock.now = 1000 + 60                            # first two hits expire exactly one window after t=1000
    assert limiter.check("a") is Decision.ALLOW


def test_notify_is_sent_again_only_after_a_new_window_of_abuse():
    limiter, clock = make(max_messages=1, window=60)
    limiter.check("a")
    assert limiter.check("a") is Decision.NOTIFY
    clock.now += 30
    assert limiter.check("a") is Decision.DROP
    clock.now += 31  # window passed: hit expired -> allowed, notification state reset
    assert limiter.check("a") is Decision.ALLOW
    assert limiter.check("a") is Decision.NOTIFY


def test_memory_is_bounded():
    limiter, clock = make(max_messages=1, window=10, max_tracked_keys=5)
    for i in range(20):
        limiter.check(f"k{i}")
        clock.now += 11  # every earlier key is idle by the next call
    assert len(limiter._hits) <= 6
