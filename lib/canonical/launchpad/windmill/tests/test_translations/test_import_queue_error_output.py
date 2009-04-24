# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Test interactive error output display in the import queue UI."""

__metaclass__ = type
__all__ = []

# Generated by the windmill services transformer
from windmill.authoring import WindmillTestClient

from canonical.launchpad.windmill.testing import lpuser

class ImportQueueErrorOutputTest:
    """Test interactive error output display in the import queue UI."""

    def __init__(self, name=None,
                 url='http://translations.launchpad.net:8085/+imports',
                 suite='translations', user=lpuser.TRANSLATIONS_ADMIN):
        """Create a new ImportQueueErrorOutputTest.

        :param name: Name of the test.
        :param url: Start at, default
            http://translation.launchpad.net:8085/+imports.
        :param suite: The test suite that this test is part of.
        :param user: The user who should be logged in.
        """
        self.url = url
        if name is None:
            self.__name__ = 'test_%s_documentation_links' % suite
        else:
            self.__name__ = name
        self.suite = suite
        self.user = user

    def _checkOutputPanel(self, client, panel_xpath):
        client.waits.forElement(xpath=panel_xpath, timeout=u'5000')
        # XXX JeroenVermeulen 2009-04-21 bug=365176: Check panel
        # contents here!

    def __call__(self):
        """Run test.

        The test:
        * produces an environment with failed translation imports;
        * loads the translation import queue page;
        * tests that the error output can be revealed interactively;
        * tests that the error output can be hidden again.
        """
        client = WindmillTestClient(self.suite)

        self.user.ensure_login(client)
        client.open(url=self.url)
        client.waits.forPageLoad(timeout=u'20000')

        placeholder = u"//div[@id='1']//div[@class='original show-output']"
        client.waits.forElement(xpath=placeholder, timeout=u'8000')
        client.click(xpath=placeholder)

        show_button = u"//div[@id='1']//div[@class='new show-output']"
        client.waits.forElement(xpath=show_button, timeout=u'8000')

        output_panel = (
            u"//div[@id='1']//tr[@class='discreet secondary output-panel]'")
        self._checkOutputPanel(client, output_panel)

        # Hide output panel.
        client.click(xpath=show_button)
        # XXX JeroenVermeulen 2009-04-21 bug=365176: waits.forElement() to
        # wait for the output panel to disappear.
        client.asserts.assertNotElement(xpath=output_panel)

        # Reveal output panel again.  This brings us back to the same
        # state as when it was first revealed.
        client.click(xpath=show_button)
        self._checkOutputPanel(client, output_panel)


test_import_queue_error_output = ImportQueueErrorOutputTest(
    name='test_import_queue_error_output')

