class FetchError(Exception):
    pass


class UnsafeUrlError(FetchError):
    pass


class RobotsDisallowed(FetchError):
    pass


class ResponseTooLarge(FetchError):
    pass


class TooManyRedirects(FetchError):
    pass


class HttpStatusError(FetchError):
    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"HTTP {status_code} for {url}")
        self.status_code = status_code
        self.url = url
