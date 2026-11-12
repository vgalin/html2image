"""Top-level package for html2image
"""

from .html2image import Html2Image
from .browsers._page_fit_common import FullPageCaptureLimitError
from .cli import main

__all__ = ['Html2Image', 'FullPageCaptureLimitError', 'main', ]
