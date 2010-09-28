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


class DSDCommentWebServiceTestCase(TestCaseWithFactory):

    layer = AppServerLayer

    def test_get_difference_comment(self):
        # DistroSeriesDifferencesComments are available on the web service.
        ds_diff = self.factory.makeDistroSeriesDifference()
        from lp.testing import person_logged_in
        from storm.store import Store
        with person_logged_in(ds_diff.owner):
            comment = ds_diff.addComment(ds_diff.owner, "Hey there")
        Store.of(comment).flush()
        transaction.commit()
        dsd_comment_path = canonical_url(comment).replace(
            'http://launchpad.dev', '')

        ws_diff = ws_object(self.factory.makeLaunchpadService(), comment)

        self.assertTrue(
            ws_diff.self_link.endswith(dsd_comment_path))
