from abc import ABC, abstractmethod


class Browser(ABC):
    """Abstract class representing a web browser."""

    def __init__(self, flags, disable_logging):
        pass

    @property
    @abstractmethod
    def executable(self):
        pass

    @executable.setter
    @abstractmethod
    def executable(self, value):
        pass

    @abstractmethod
    def screenshot(self, *args, **kwargs):
        pass

    @abstractmethod
    def __enter__(self):
        pass

    @abstractmethod
    def __exit__(self, *exc):
        pass

    @property
    @abstractmethod
    def disable_logging(self):
        pass


class CDPBrowser(Browser):
    """A web browser that can be interacted with via Chrome DevTools Protocol.
    """

    def __init__(self, flags, cdp_port, disable_logging):
        pass
