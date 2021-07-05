from abc import ABC, abstractmethod


class Browser(ABC):
    """Abstract class representing a web browser."""

    def __init__(self, flags):
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
