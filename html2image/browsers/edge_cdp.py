from .chrome_cdp import ChromeCDP
from .edge import _find_edge


class EdgeCDP(ChromeCDP):
    """Edge browser backend using Chrome DevTools Protocol (CDP).

    Identical behavior to ChromeCDP — Edge is Chromium-based and exposes
    the same CDP interface. Only the executable discovery differs.
    """

    @property
    def executable(self):
        return self._executable

    @executable.setter
    def executable(self, value):
        self._executable = _find_edge(value)
