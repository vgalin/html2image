from .browser import Browser


class FirefoxHeadless(Browser):

    def __init__(self):
        raise NotImplementedError(
            "Could not make screenshot work on Firefox headless yet ...\n"
            "See https://bugzilla.mozilla.org/show_bug.cgi?id=1715450"
        )

    @property
    def executable(self):
        pass

    @executable.setter
    def executable(self, value):
        pass

    def render(self, **kwargs):
        pass

    def __enter__(self):
        pass

    def __exit__(self, *exc):
        pass
