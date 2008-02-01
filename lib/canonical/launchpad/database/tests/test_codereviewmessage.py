# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Unit tests for CodeReviewMessage"""

import unittest
from canonical.launchpad.interfaces import CodeReviewVote
from canonical.testing import LaunchpadFunctionalLayer
from canonical.launchpad.ftests import login
from canonical.launchpad.testing import LaunchpadObjectFactory

class TestCodeReviewMessage(unittest.TestCase):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        unittest.TestCase.setUp(self)
        login('test@canonical.com')
        self.factory = LaunchpadObjectFactory()
        self.bmp = self.factory.makeProposalToMerge()
        self.submitter = self.factory.makePerson()
        self.reviewer = self.factory.makePerson()
        self.bmp2 = self.factory.makeProposalToMerge()

    def test_create_root_message(self):
        message = self.bmp.createMessage(self.submitter, 'Message subject',
            'Message content')
        self.assertEqual(None, message.vote)
        self.assertEqual(self.submitter, message.message.owner)
        self.assertEqual(message, self.bmp.conversation)
        self.assertEqual('Message subject', message.message.subject)
        self.assertEqual('Message content', message.message.chunks[0].content)

    def test_create_reply_message(self):
        message = self.bmp.createMessage(self.submitter, 'Message subject',
            'Message content')
        reply = self.bmp.createMessage(self.reviewer, 'Reply subject',
            'Reply content', CodeReviewVote.TWEAK, message)
        self.assertEqual(message, self.bmp.conversation)
        self.assertEqual(message.message.id, reply.message.parent.id)
        self.assertEqual(message.message, reply.message.parent)
        self.assertEqual('Reply subject', reply.message.subject)
        self.assertEqual('Reply content', reply.message.chunks[0].content)
        self.assertEqual(CodeReviewVote.TWEAK, reply.vote)

    def test_create_no_parent_message(self):
        message = self.bmp.createMessage(self.submitter, 'Message subject',
            'Message content')
        new_message = self.bmp.createMessage( self.reviewer, 'New subject',
            'New content', CodeReviewVote.TWEAK)
        self.assertEqual(
            self.bmp.conversation.message, new_message.message.parent)

    def test_reply_with_wrong_merge_proposal(self):
        message = self.bmp.createMessage(self.submitter, 'Message subject',
            'Message content')
        self.assertRaises(AssertionError, self.bmp2.createMessage,
                          self.reviewer, 'Reply subject', 'Reply content',
                          CodeReviewVote.TWEAK, message)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
