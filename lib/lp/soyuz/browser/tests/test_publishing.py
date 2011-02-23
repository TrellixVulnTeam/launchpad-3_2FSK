# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for source package publication listing."""

__metaclass__ = type

import soupmatchers
from zope.component import getUtility

from canonical.testing.layers import LaunchpadFunctionalLayer
from canonical.launchpad.webapp.publisher import canonical_url

from lp.registry.interfaces.person import IPersonSet
from lp.soyuz.enums import PackagePublishingStatus
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import (
    BrowserTestCase,
    person_logged_in,
    )
from lp.testing.sampledata import ADMIN_EMAIL


class TestSourcePublicationListingExtra(BrowserTestCase):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestSourcePublicationListingExtra, self).setUp()
        self.admin = getUtility(IPersonSet).getByEmail(ADMIN_EMAIL)
        # Create everything we need to create builds, such as a
        # DistroArchSeries and a builder.
        self.pf = self.factory.makeProcessorFamily()
        pf_proc = self.pf.addProcessor(self.factory.getUniqueString(), '', '')
        self.distroseries = self.factory.makeDistroSeries()
        self.das = self.factory.makeDistroArchSeries(
            distroseries=self.distroseries, processorfamily=self.pf,
            supports_virtualized=True)
        self.archive = self.factory.makeArchive(
            distribution=self.distroseries.distribution)
        with person_logged_in(self.admin):
            self.publisher = SoyuzTestPublisher()
            self.publisher.prepareBreezyAutotest()
            self.distroseries.nominatedarchindep = self.das
            self.publisher.addFakeChroots(distroseries=self.distroseries)
            self.builder = self.factory.makeBuilder(processor=pf_proc)

    def test_view_with_source_package_recipe(self):
        # When a SourcePackageRelease is linked to a
        # SourcePackageRecipeBuild, the view shows which recipe was
        # responsible for creating the SPR.
        sprb = self.factory.makeSourcePackageRecipeBuild(
            archive=self.archive)
        recipe = sprb.recipe
        spph = self.publisher.getPubSource(
            archive=self.archive, status=PackagePublishingStatus.PUBLISHED)
        spph.sourcepackagerelease.source_package_recipe_build = sprb
        recipe_link_matcher = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'link to build', 'a', attrs={'href': canonical_url(sprb,
                    force_local_path=True)},
                text='Built'),
            soupmatchers.Tag(
                'recipe name', 'a', attrs={'href': canonical_url(recipe)},
                text=recipe.name),
            soupmatchers.Tag(
                'requester', 'a',
                attrs={'href': canonical_url(sprb.requester,
                    force_local_path=True)},
                text=sprb.requester.displayname))
        browser = self.getViewBrowser(spph, '+listing-archive-extra')
        self.assertThat(browser.contents, recipe_link_matcher)

    def test_view_without_source_package_recipe(self):
        # And if a SourcePackageRelease is not linked, there is no sign of it
        # in the view.
        spph = self.publisher.getPubSource(
            archive=self.archive, status=PackagePublishingStatus.PUBLISHED)
        browser = self.getViewBrowser(spph, '+listing-archive-extra')
        self.assertNotIn('Built by recipe', browser.contents)
