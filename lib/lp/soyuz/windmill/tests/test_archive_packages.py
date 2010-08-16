# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from canonical.launchpad.windmill.testing import constants
from lp.soyuz.windmill.testing import SoyuzWindmillLayer
from lp.testing import WindmillTestCase


class TestArchivePackagesSourcesExtra(WindmillTestCase):
    """Each listed source package can be expanded for extra information."""

    layer = SoyuzWindmillLayer

    def test_sources_extra_available(self):
        """A successful request for the extra info updates the display."""

        self.client.open(
            url='http://launchpad.dev:8085/~cprov/+archive/ppa/+packages')
        self.client.waits.forPageLoad(timeout=constants.PAGE_LOAD)

        self.client.click(id="pub29-expander")

        self.client.waits.forElement(
            xpath=u'//div[@id="pub29-container"]//a[text()="i386"]',
            timeout=constants.FOR_ELEMENT)
