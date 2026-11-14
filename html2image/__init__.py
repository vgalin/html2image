"""Top-level package for html2image
"""

from .html2image import Html2Image
from .cli import main
from .exceptions import (
    Html2ImageError,
    BrowserNotFoundError,
    BrowserError,
    BrowserTimeoutError,
    PageLoadError,
    PageLoadTimeoutError,
)

__all__ = [
    'Html2Image', 'main',
    'Html2ImageError',
    'BrowserNotFoundError',
    'BrowserError',
    'BrowserTimeoutError',
    'PageLoadError',
    'PageLoadTimeoutError',
]
