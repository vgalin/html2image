from .browser import Browser


class FirefoxHeadless(Browser):

    def __init__(self):
        raise NotImplementedError(
            "Could not make screenshot work on Firefox headless yet ...\n"
            "See https://bugzilla.mozilla.org/show_bug.cgi?id=1715450"
        )

    @property
    def executable_path(self):
        pass

    @executable_path.setter
    def executable_path(self, value):
        pass

    def render(self, **kwargs):
        pass
