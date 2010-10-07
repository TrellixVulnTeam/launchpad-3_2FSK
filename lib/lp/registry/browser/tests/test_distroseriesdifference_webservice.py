# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import with_statement

__metaclass__ = type

import transaction

from lazr.restfulclient.errors import Unauthorized
from zope.component import getUtility

from canonical.testing import AppServerLayer
from canonical.launchpad.webapp.publisher import canonical_url
from lp.registry.enum import DistroSeriesDifferenceStatus
from lp.registry.interfaces.distroseriesdifference import (
    IDistroSeriesDifferenceSource,
    )
from lp.testing import (
    TestCaseWithFactory,
    ws_object,
    )


class DistroSeriesDifferenceWebServiceTestCase(TestCaseWithFactory):

    layer = AppServerLayer

    def test_get_difference(self):
        # DistroSeriesDifferences are available on the web service.
        ds_diff = self.factory.makeDistroSeriesDifference()
        ds_diff_path = canonical_url(ds_diff).replace(
            'http://launchpad.dev', '')

        ws_diff = ws_object(self.factory.makeLaunchpadService(), ds_diff)

        self.assertTrue(
            ws_diff.self_link.endswith(ds_diff_path))

    def test_blacklist_not_public(self):
        # The blacklist method is not publically available.
        ds_diff = self.factory.makeDistroSeriesDifference()
        ws_diff = ws_object(self.factory.makeLaunchpadService(), ds_diff)

        self.assertRaises(Unauthorized, ws_diff.blacklist)

    def test_blacklist(self):
        # The blacklist method can be called by people with edit access.
        ds_diff = self.factory.makeDistroSeriesDifference()
        ws_diff = ws_object(self.factory.makeLaunchpadService(
            ds_diff.derived_series.owner), ds_diff)

        result = ws_diff.blacklist()
        transaction.commit()

        utility = getUtility(IDistroSeriesDifferenceSource)
        ds_diff = utility.getByDistroSeriesAndName(
            ds_diff.derived_series, ds_diff.source_package_name.name)
        self.assertEqual(
            DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT,
            ds_diff.status)

    def test_unblacklist_not_public(self):
        # The unblacklist method is not publically available.
        ds_diff = self.factory.makeDistroSeriesDifference(
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)
        ws_diff = ws_object(self.factory.makeLaunchpadService(), ds_diff)

        self.assertRaises(Unauthorized, ws_diff.unblacklist)

    def test_unblacklist(self):
        # The unblacklist method can be called by people with edit access.
        ds_diff = self.factory.makeDistroSeriesDifference(
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)
        ws_diff = ws_object(self.factory.makeLaunchpadService(
            ds_diff.owner), ds_diff)

        result = ws_diff.unblacklist()
        transaction.commit()

        utility = getUtility(IDistroSeriesDifferenceSource)
        ds_diff = utility.getByDistroSeriesAndName(
            ds_diff.derived_series, ds_diff.source_package_name.name)
        self.assertEqual(
            DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
            ds_diff.status)

    def test_addComment(self):
        # Comments can be added via the API
        ds_diff = self.factory.makeDistroSeriesDifference()
        ws_diff = ws_object(self.factory.makeLaunchpadService(
            ds_diff.owner), ds_diff)

        result = ws_diff.addComment(comment='Hey there')

        self.assertEqual('Hey there', result['body_text'])
        self.assertTrue(
            result['resource_type_link'].endswith(
                '#distro_series_difference_comment'))

    def test_requestDiffs(self):
        # The generation of package diffs can be requested via the API.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str='foo', versions={
                'derived': '1.2',
                'parent': '1.3',
                'base': '1.0',
                })
        ws_diff = ws_object(self.factory.makeLaunchpadService(
            ds_diff.owner), ds_diff)

        result = ws_diff.requestPackageDiffs()
        transaction.commit()

        # Reload and check that the package diffs are there.
        utility = getUtility(IDistroSeriesDifferenceSource)
        ds_diff = utility.getByDistroSeriesAndName(
            ds_diff.derived_series, ds_diff.source_package_name.name)
        self.assertIsNot(None, ds_diff.package_diff)
        self.assertIsNot(None, ds_diff.parent_package_diff)

    def test_package_diffs(self):
        # The `IPackageDiff` attributes are exposed.
        ds_diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str='foo', versions={
                'derived': '1.2',
                'parent': '1.3',
                'base': '1.0',
                })
        from lp.testing import person_logged_in
        with person_logged_in(ds_diff.owner):
            ds_diff.requestPackageDiffs(ds_diff.owner)
        ws_diff = ws_object(self.factory.makeLaunchpadService(
            ds_diff.owner), ds_diff)

        self.assertEqual('In progress', ws_diff.package_diff.status)
        self.assertEqual('In progress', ws_diff.parent_package_diff.status)
