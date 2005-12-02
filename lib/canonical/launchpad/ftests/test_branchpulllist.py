# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Tests for BranchPullListing and related."""

__metaclass__ = type

import unittest
from zope.testing.doctest import DocFileSuite, DocTestSuite

from canonical.database.constants import UTC_NOW
from canonical.launchpad import browser as browser
from canonical.launchpad.ftests.harness import LaunchpadFunctionalTestCase


def test_suite():
    loader = unittest.TestLoader()
    result = loader.loadTestsFromName(__name__)
    return result


class MockRequest:
    """A mock request.
    
    We are not using the standard zope one because SteveA said it was
    'crackful'.
    """


class MockResponse:
    """A mock response.
    
    We are not using the standard zope one because SteveA said it was
    'crackful'.
    """

    def __init__(self):
        self._calls = []

    def setHeader(self, header, value):
        self._calls.append(('setHeader', header, value))


class MockPerson:
    """A fake person."""

    def __init__(self, name):
        self.name = name


class MockProduct:
    """A fake product."""

    def __init__(self, name):
        self.name = name


class MockBranch:
    """A fake branch with the usual fields."""

    def __init__(self, name, url, product_name, person_name):
        self.name = name
        self.owner = MockPerson(person_name)
        if product_name is not None:
            self.product = MockProduct(product_name)
        else:
            self.product = None
        self.url = url


class TestBranchPullListing(unittest.TestCase):

    def test_branch_pull_class_exists(self):
        from canonical.launchpad.browser import BranchPullListing


class TestBranchPullWithBranches(unittest.TestCase):

    def setUp(self):
        unittest.TestCase.setUp(self)
        self.view = browser.BranchPullListing(None, None)
        self.branch_with_product = MockBranch("foo", "http://foo/bar",
                                              "product", "john")
        self.branch_with_another_product = MockBranch("bar", "http://foo/gam",
                                                      "a_product", "mary")
        self.branch_with_no_product = MockBranch("quux", "sftp://example.com",
                                                 None, "james")


    def test_get_line_for_branch(self):
        self.assertEqual(
            "http://foo/bar john product foo",
            self.view.get_line_for_branch(self.branch_with_product))
        self.assertEqual(
            "http://foo/gam mary a_product bar",
            self.view.get_line_for_branch(self.branch_with_another_product))
        self.assertEqual(
            "sftp://example.com james +junk quux",
            self.view.get_line_for_branch(self.branch_with_no_product))

    def test_branches_page(self):
        self.assertEqual("http://foo/bar john product foo\n"
                         "http://foo/gam mary a_product bar\n",
                         self.view.branches_page(
                            [self.branch_with_product,
                             self.branch_with_another_product]))
        self.assertEqual("sftp://example.com james +junk quux\n"
                         "http://foo/gam mary a_product bar\n",
                         self.view.branches_page(
                            [self.branch_with_no_product,
                             self.branch_with_another_product]))
        self.assertEqual("http://foo/bar john product foo\n"
                         "http://foo/gam mary a_product bar\n"
                         "sftp://example.com james +junk quux\n",
                         self.view.branches_page(
                            [self.branch_with_product,
                             self.branch_with_another_product,
                             self.branch_with_no_product]))


class TestBranchesToPullSample(LaunchpadFunctionalTestCase):

    def test_get_branches_to_pull(self):
        from canonical.launchpad.database import Branch
        self.login()
        mock_request = MockRequest()
        mock_request.response = MockResponse()
        view = browser.BranchPullListing(None, mock_request)
        # sample data gives 2 branches:
        expected_ids = set([15, 16, 17, 18, 19, 20, 21, 22, 23])
        got_ids = set([branch.id for branch in view.get_branches_to_pull()])
        self.assertEqual(expected_ids, got_ids)
        # now check refresh logic:
        # current logic - any branch with either no last mirrored time, or
        # now - lastmirrored < 24 hours and not a supermirror branch.
        # 
        branch = Branch.get(23)
        branch.last_mirror_attempt = UTC_NOW
        branch.sync()

        expected_ids = set([15, 16, 17, 18, 19, 20, 21, 22])
        got_ids = set([branch.id for branch in view.get_branches_to_pull()])
        self.assertEqual(expected_ids, got_ids)
        # As we've finished this test we dont care about what we have created
        # in the database, if we could rollback that might be nice for clarity.

    def test_branch_pull_render(self):
        self.login()
        mock_request = MockRequest()
        mock_request.response = MockResponse()
        view = browser.BranchPullListing(None, mock_request)
        self.assertEqual(set([
            u'http://trekkies.example.com/gnome-terminal/klingon name12 gnome-terminal klingon',
            u'http://example.com/gnome-terminal/2.4 name12 gnome-terminal 2.4',
            u'http://localhost:8000/b name12 +junk junk.contrib',
            u'http://not.launchpad.server.com/ spiv +junk feature',
            u'http://example.com/gnome-terminal/2.6 name12 gnome-terminal 2.6',
            u'http://users.example.com/gnome-terminal/slowness name12 gnome-terminal slowness',
            u'http://whynot.launchpad.server.com/ spiv +junk feature2',
            u'http://example.com/gnome-terminal/main name12 gnome-terminal main',
            u'http://localhost:8000/a name12 +junk junk.dev',
            u'']),
            set(view.render().split('\n')))
        
    def test_branch_pull_mime_type(self):
        self.login()
        mock_request = MockRequest()
        mock_request.response = MockResponse()
        view = browser.BranchPullListing(None, mock_request)
        view.render()
        self.assertEqual([('setHeader', 'Content-type', 'text/plain')],
                         mock_request.response._calls)
