# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test registered vocabularies."""

__metaclass__ = type
__all__ = []

import unittest

from zope.component import getUtilitiesFor
from zope.schema.interfaces import IVocabularyFactory
from zope.security._proxy import _Proxy

from canonical.testing.layers import FunctionalLayer
from lp.testing import TestCase


class TestVocabularies(TestCase):
    layer = FunctionalLayer

    def test_security_proxy(self):
        """Our vocabularies should be registered with <securedutility>."""
        vocabularies = getUtilitiesFor(IVocabularyFactory)
        for name, vocab in vocabularies:
            if type(vocab) != _Proxy and vocab.__module__[:5] != 'zope.':
                raise AssertionError(
                    '%s.%s vocabulary is not wrapped in a security proxy.' % (
                    vocab.__module__, name))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
