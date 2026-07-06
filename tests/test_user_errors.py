"""User-facing error text must not mention GitHub."""

import os
import sys
import unittest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, 'src'))

from tools.user_errors import scrub_user_error_text
from tools.updater_core import format_updater_error_message


class UserErrorsTest(unittest.TestCase):
    def test_scrub_github_url_and_brand(self) -> None:
        raw = (
            'See https://github.com/zubcats/foo/releases and api.github.com/repos/x '
            'or GitHub Releases for GitHub'
        )
        out = scrub_user_error_text(raw)
        self.assertNotIn('github', out.lower())
        self.assertNotIn('GitHub', out)

    def test_updater_ssl_error_has_no_github(self) -> None:
        err = Exception(
            '<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>'
        )
        msg = format_updater_error_message(err)
        self.assertNotIn('github', msg.lower())

    def test_updater_unreachable_has_no_github(self) -> None:
        err = OSError(None, 'host unreachable', None, 10065)
        msg = format_updater_error_message(err)
        self.assertNotIn('github', msg.lower())


if __name__ == '__main__':
    unittest.main()
