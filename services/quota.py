class QuotaExhaustedError(Exception):
    """Raised when an OpenAI call fails due to exhausted account quota/balance.

    Distinct from ordinary rate limiting: quota exhaustion won't resolve itself
    within seconds, so callers should pause the whole processing queue rather
    than retrying this one call.
    """
