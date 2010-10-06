# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import unittest

from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.testing.layers import LaunchpadZopelessLayer
from lp.registry.interfaces.series import SeriesStatus
from lp.testing import TestCaseWithFactory
from lp.translations.browser.product import ProductView


class TestProduct(TestCaseWithFactory):
    """Test Product view in translations facet."""

    layer = LaunchpadZopelessLayer

    def test_primary_translatable_with_package_link(self):
        # Create a product that uses translations.
        product = self.factory.makeProduct()
        series = product.development_focus
        product.official_rosetta = True
        view = ProductView(product, LaunchpadTestRequest())

        # If development focus series is linked to
        # a distribution package with translations,
        # we do not try to show translation statistics
        # for the package.
        sourcepackage = self.factory.makeSourcePackage()
        sourcepackage.setPackaging(series, None)
        sourcepackage.distroseries.distribution.official_rosetta = True
        pot = self.factory.makePOTemplate(
            distroseries=sourcepackage.distroseries,
            sourcepackagename=sourcepackage.sourcepackagename)
        self.assertEquals(None, view.primary_translatable)

    def test_untranslatable_series(self):
        # Create a product that uses translations.
        product = self.factory.makeProduct()
        series_trunk = product.development_focus
        product.official_rosetta = True
        view = ProductView(product, LaunchpadTestRequest())

        # New series are added, one for each type of status
        series_experimental = self.factory.makeProductSeries(
            product=product, name='evo-experimental')
        series_experimental.status = SeriesStatus.EXPERIMENTAL

        series_development = self.factory.makeProductSeries(
            product=product, name='evo-development')
        series_development.status = SeriesStatus.DEVELOPMENT

        series_frozen = self.factory.makeProductSeries(
            product=product, name='evo-frozen')
        series_frozen.status = SeriesStatus.FROZEN

        series_current = self.factory.makeProductSeries(
            product=product, name='evo-current')
        series_current.status = SeriesStatus.CURRENT

        series_supported = self.factory.makeProductSeries(
            product=product, name='evo-supported')
        series_supported.status = SeriesStatus.SUPPORTED

        series_obsolete = self.factory.makeProductSeries(
            product=product, name='evo-obsolete')
        series_obsolete.status = SeriesStatus.OBSOLETE

        series_future = self.factory.makeProductSeries(
            product=product, name='evo-future')
        series_future.status = SeriesStatus.FUTURE

        # The series are returned in alphabetical order and do not
        # include obsolete series.
        series_names = [series.name for series in view.untranslatable_series]
        self.assertEqual([
            u'evo-current',
            u'evo-development',
            u'evo-experimental',
            u'evo-frozen',
            u'evo-future',
            u'evo-supported',
            u'trunk'], series_names)


class TestSearchQuestionsViewCanConfigureAnswers(TestSearchQuestionsView):

    def test_cannot_configure_translations_product_no_edit_permission(self):
        product = self.factory.makeProduct()
        view = create_initialized_view(product, '+translations')
        self.assertEqual(False, view.can_configure_answers)

    def test_can_configure_translations_product_with_edit_permission(self):
        product = self.factory.makeProduct()
        login_person(product.owner)
        view = create_initialized_view(product, '+translations')
        self.assertEqual(True, view.can_configure_answers)

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
