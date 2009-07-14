# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Tests for the `IProviderOpenIDStore` utility."""

__metaclass__ = type

import unittest

from zope.component import getUtility

from canonical.launchpad.database.tests.test_baseopenidstore import (
    BaseStormOpenIDStoreTestsMixin)
from canonical.launchpad.webapp.interfaces import IStoreSelector
from canonical.signon.dbpolicy import SSODatabasePolicy
from canonical.signon.interfaces.openidstore import IProviderOpenIDStore
from canonical.testing import DatabaseFunctionalLayer
from lp.testing import TestCase


class ProviderOpenIDStoreTests(BaseStormOpenIDStoreTestsMixin, TestCase):
    """Tests for the `IProviderOpenIDStore` utility."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(ProviderOpenIDStoreTests, self).setUp()
        getUtility(IStoreSelector).push(SSODatabasePolicy())
        self.store = getUtility(IProviderOpenIDStore)

    def tearDown(self):
        getUtility(IStoreSelector).pop()
        super(ProviderOpenIDStoreTests, self).tearDown()


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
