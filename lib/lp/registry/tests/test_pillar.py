# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Unit tests for methods of PillarName and PillarNameSet."""

import unittest

from zope.component import getUtility

from canonical.launchpad.ftests import login
from lp.registry.interfaces.pillar import IPillarNameSet
from canonical.launchpad.testing import TestCaseWithFactory
from canonical.testing import LaunchpadFunctionalLayer


class TestPillarNameSet(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def test_search_correctly_ranks_by_aliases(self):
        """When we use a pillar's alias to search, that pillar will be the
        first one on the list.
        """
        login('mark@hbd.com')
        lz_foo = self.factory.makeProduct(name='lz-foo')
        lz_bar = self.factory.makeProduct(name='lz-bar')
        launchzap = self.factory.makeProduct(name='launchzap')
        launchzap.setAliases(['lz'])
        pillar_set = getUtility(IPillarNameSet)
        result_names = [
            pillar.name for pillar in pillar_set.search('lz', limit=5)]
        self.assertEquals(result_names, [u'launchzap', u'lz-bar', u'lz-foo'])


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
