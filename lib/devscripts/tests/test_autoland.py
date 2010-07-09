# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for automatic landing thing."""

__metaclass__ = type

import unittest

from launchpadlib.launchpad import EDGE_SERVICE_ROOT, STAGING_SERVICE_ROOT

from lp.testing.fakemethod import FakeMethod

from devscripts.autoland import (
    get_bazaar_host, get_bugs_clause, get_reviewer_clause,
    get_reviewer_handle, get_qa_clause, get_testfix_clause,
    MissingReviewError, MissingBugsError, MissingBugsIncrError,
    MergeProposal)


class FakeBug:
    """Fake launchpadlib Bug object.

    Only used for the purposes of testing.
    """

    def __init__(self, id):
        self.id = id


class FakePerson:
    """Fake launchpadlib Person object.

    Only used for the purposes of testing.
    """

    def __init__(self, name, irc_handles):
        self.name = name
        self.irc_nicknames = list(irc_handles)


class FakeIRC:
    """Fake IRC handle.

    Only used for the purposes of testing.
    """

    def __init__(self, nickname, network):
        self.nickname = nickname
        self.network = network


class FakeLPMergeProposal:
    """Fake launchpadlib MergeProposal object.

    Only used for the purposes of testing.
    """

    def __init__(self, root=None):
        self._root = root


class TestBugsClaused(unittest.TestCase):
    """Tests for `get_bugs_clause`."""

    def test_no_bugs(self):
        # If there are no bugs, then there is no bugs clause.
        bugs_clause = get_bugs_clause([])
        self.assertEqual('', bugs_clause)

    def test_one_bug(self):
        # If there's a bug, then the bugs clause is [bug=$ID].
        bug = FakeBug(45)
        bugs_clause = get_bugs_clause([bug])
        self.assertEqual('[bug=45]', bugs_clause)

    def test_two_bugs(self):
        # If there are two bugs, then the bugs clause is [bug=$ID,$ID].
        bug1 = FakeBug(20)
        bug2 = FakeBug(45)
        bugs_clause = get_bugs_clause([bug1, bug2])
        self.assertEqual('[bug=20,45]', bugs_clause)


class TestGetCommitMessage(unittest.TestCase):

    def makePerson(self, name):
        return FakePerson(name, [])

    def test_commit_with_bugs(self):
        incr = False
        no_qa = False
        testfix = False

        bug1 = FakeBug(20)
        mp = MergeProposal(FakeLPMergeProposal())
        mp.get_bugs = FakeMethod([bug1])
        mp.get_reviews = FakeMethod({None : [self.makePerson('foo')]})

        self.assertEqual("[r=foo][ui=none][bug=20] Foobaring the sbrubble.",
            mp.get_commit_message("Foobaring the sbrubble.", testfix, no_qa,
                incr))

    def test_commit_no_bugs_no_noqa(self):
        incr = False
        no_qa = False
        testfix = False

        mp = MergeProposal(FakeLPMergeProposal())
        mp.get_bugs = FakeMethod([])
        mp.get_reviews = FakeMethod({None : [self.makePerson('foo')]})

        self.assertRaises(MissingBugsError, mp.get_commit_message,
            testfix, no_qa, incr)

    def test_commit_no_bugs_with_noqa(self):
        incr = False
        no_qa = True
        testfix = False

        mp = MergeProposal(FakeLPMergeProposal())
        mp.get_bugs = FakeMethod([])
        mp.get_reviews = FakeMethod({None : [self.makePerson('foo')]})

        self.assertEqual("[r=foo][ui=none][no-qa] Foobaring the sbrubble.",
            mp.get_commit_message("Foobaring the sbrubble.", testfix, no_qa,
                incr))

    def test_commit_bugs_with_noqa(self):
        incr = False
        no_qa = True
        testfix = False

        bug1 = FakeBug(20)
        mp = MergeProposal(FakeLPMergeProposal())
        mp.get_bugs = FakeMethod([bug1])
        mp.get_reviews = FakeMethod({None : [self.makePerson('foo')]})

        self.assertEqual(
            "[r=foo][ui=none][bug=20][no-qa] Foobaring the sbrubble.",
            mp.get_commit_message("Foobaring the sbrubble.", testfix, no_qa,
                incr))

    def test_commit_bugs_with_incr(self):
        incr = True
        no_qa = False
        testfix = False

        bug1 = FakeBug(20)
        mp = MergeProposal(FakeLPMergeProposal())
        mp.get_bugs = FakeMethod([bug1])
        mp.get_reviews = FakeMethod({None : [self.makePerson('foo')]})

        self.assertEqual(
            "[r=foo][ui=none][bug=20][incr] Foobaring the sbrubble.",
            mp.get_commit_message("Foobaring the sbrubble.", testfix, no_qa,
                incr))

    def test_commit_no_bugs_with_incr(self):
        incr = True
        no_qa = False
        testfix = False

        bug1 = FakeBug(20)
        mp = MergeProposal(FakeLPMergeProposal())
        mp.get_bugs = FakeMethod([bug1])
        mp.get_reviews = FakeMethod({None : [self.makePerson('foo')]})

        self.assertEqual(
            "[r=foo][ui=none][bug=20][incr] Foobaring the sbrubble.",
            mp.get_commit_message("Foobaring the sbrubble.", testfix, no_qa,
                incr))



class TestGetTestfixClause(unittest.TestCase):
    """Tests for `get_testfix_clause`"""

    def test_no_testfix(self):
        testfix = False
        self.assertEqual('', get_testfix_clause(testfix))

    def test_is_testfix(self):
        testfix = True
        self.assertEqual('[testfix]', get_testfix_clause(testfix))


class TestGetQaClause(unittest.TestCase):
    """Tests for `get_qa_clause`"""

    def test_no_bugs_no_option_given(self):
        bugs = None
        no_qa = False
        incr = False
        self.assertRaises(MissingBugsError, get_qa_clause, bugs, no_qa,
            incr)

    def test_bugs_noqa_option_given(self):
        bug1 = FakeBug(20)
        no_qa = True
        incr = False
        self.assertEqual('[no-qa]',
            get_qa_clause([bug1], no_qa, incr))

    def test_no_bugs_noqa_option_given(self):
        bugs = None
        no_qa = True
        incr = False
        self.assertEqual('[no-qa]',
            get_qa_clause(bugs, no_qa, incr))

    def test_bugs_no_option_given(self):
        bug1 = FakeBug(20)
        no_qa = False
        incr = False
        self.assertEqual('',
            get_qa_clause([bug1], no_qa, incr))

    def test_bugs_incr_option_given(self):
        bug1 = FakeBug(20)
        no_qa = False
        incr = True
        self.assertEqual('[incr]',
            get_qa_clause([bug1], no_qa, incr))

    def test_no_bugs_incr_option_given(self):
        bugs = None
        no_qa = False
        incr = True
        self.assertRaises(MissingBugsIncrError,
            get_qa_clause, bugs, no_qa, incr)


class TestGetReviewerHandle(unittest.TestCase):
    """Tests for `get_reviewer_handle`."""

    def makePerson(self, name, irc_handles):
        return FakePerson(name, irc_handles)

    def test_no_irc_nicknames(self):
        # If the person has no IRC nicknames, their reviewer handle is their
        # Launchpad user name.
        person = self.makePerson(name='foo', irc_handles=[])
        self.assertEqual('foo', get_reviewer_handle(person))

    def test_freenode_irc_nick_preferred(self):
        # If the person has a Freenode IRC nickname, then that is preferred as
        # their user handle.
        person = self.makePerson(
            name='foo', irc_handles=[FakeIRC('bar', 'irc.freenode.net')])
        self.assertEqual('bar', get_reviewer_handle(person))

    def test_non_freenode_nicks_ignored(self):
        # If the person has IRC nicks that aren't freenode, we ignore them.
        person = self.makePerson(
            name='foo', irc_handles=[FakeIRC('bar', 'irc.efnet.net')])
        self.assertEqual('foo', get_reviewer_handle(person))


class TestGetReviewerClause(unittest.TestCase):
    """Tests for `get_reviewer_clause`."""

    def makePerson(self, name):
        return FakePerson(name, [])

    def get_reviewer_clause(self, reviewers):
        return get_reviewer_clause(reviewers)

    def test_one_reviewer_no_type(self):
        # It's very common for a merge proposal to be reviewed by one person
        # with no specified type of review. It such cases the review clause is
        # '[r=<person>][ui=none]'.
        clause = self.get_reviewer_clause({None: [self.makePerson('foo')]})
        self.assertEqual('[r=foo][ui=none]', clause)

    def test_two_reviewers_no_type(self):
        # Branches can have more than one reviewer.
        clause = self.get_reviewer_clause(
            {None: [self.makePerson('foo'), self.makePerson('bar')]})
        self.assertEqual('[r=bar,foo][ui=none]', clause)

    def test_mentat_reviewers(self):
        # A mentat review sometimes is marked like 'ui*'.  Due to the
        # unordered nature of dictionaries, the reviewers are sorted before
        # being put into the clause for predictability.
        clause = self.get_reviewer_clause(
            {None: [self.makePerson('foo')],
             'code*': [self.makePerson('newguy')],
             'ui': [self.makePerson('beuno')],
             'ui*': [self.makePerson('bac')]})
        self.assertEqual('[r=foo,newguy][ui=bac,beuno]', clause)

    def test_code_reviewer_counts(self):
        # Some people explicitly specify the 'code' type when they do code
        # reviews, these are treated in the same way as reviewers without any
        # given type.
        clause = self.get_reviewer_clause({'code': [self.makePerson('foo')]})
        self.assertEqual('[r=foo][ui=none]', clause)

    def test_release_critical(self):
        # Reviews that are marked as release-critical are included in a
        # separate clause.
        clause = self.get_reviewer_clause(
            {'code': [self.makePerson('foo')],
             'release-critical': [self.makePerson('bar')]})
        self.assertEqual('[release-critical=bar][r=foo][ui=none]', clause)

    def test_db_reviewer_counts(self):
        # There's no special way of annotating database reviews in Launchpad
        # commit messages, so they are included with the code reviews.
        clause = self.get_reviewer_clause({'db': [self.makePerson('foo')]})
        self.assertEqual('[r=foo][ui=none]', clause)

    def test_ui_reviewers(self):
        # If someone has done a UI review, then that appears in the clause
        # separately from the code reviews.
        clause = self.get_reviewer_clause(
            {'code': [self.makePerson('foo')],
             'ui': [self.makePerson('bar')],
             })
        self.assertEqual('[r=foo][ui=bar]', clause)

    def test_no_reviewers(self):
        # If the merge proposal hasn't been approved by anyone, we cannot
        # generate a valid clause.
        self.assertRaises(MissingReviewError, self.get_reviewer_clause, {})


class TestGetBazaarHost(unittest.TestCase):
    """Tests for `get_bazaar_host`."""

    def test_dev_service(self):
        # The Bazaar host for the dev service is bazaar.launchpad.dev.
        self.assertEqual(
            'bazaar.launchpad.dev',
            get_bazaar_host('https://api.launchpad.dev/beta/'))

    def test_edge_service(self):
        # The Bazaar host for the edge service is bazaar.launchpad.net, since
        # there's no edge codehosting service.
        self.assertEqual(
            'bazaar.launchpad.net', get_bazaar_host(EDGE_SERVICE_ROOT))

    def test_production_service(self):
        # The Bazaar host for the production service is bazaar.launchpad.net.
        self.assertEqual(
            'bazaar.launchpad.net',
            get_bazaar_host('https://api.launchpad.net/beta/'))

    def test_staging_service(self):
        # The Bazaar host for the staging service is
        # bazaar.staging.launchpad.net.
        self.assertEqual(
            'bazaar.staging.launchpad.net',
            get_bazaar_host(STAGING_SERVICE_ROOT))

    def test_unrecognized_service(self):
        # Any unrecognized URL will raise a ValueError.
        self.assertRaises(
            ValueError, get_bazaar_host, 'https://api.lunchpad.net')


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
