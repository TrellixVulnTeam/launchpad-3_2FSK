# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import re

import transaction
from zope.component import (
    getMultiAdapter,
    getUtility,
    )
from zope.publisher.interfaces import NotFound
from zope.security.interfaces import Unauthorized

from canonical.launchpad.browser.librarian import (
    StreamOrRedirectLibraryFileAliasView,
    SafeStreamOrRedirectLibraryFileAliasView,
    )
from canonical.launchpad.interfaces import ILaunchBag
from canonical.launchpad.interfaces.librarian import (
    ILibraryFileAliasWithParent,
    )
from canonical.launchpad.webapp.publisher import RedirectionView
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.testing import LaunchpadFunctionalLayer
from lp.bugs.browser.bugattachment import (
    BugAttachmentFileNavigation,
    )
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    )


class TestAccessToBugAttachmentFiles(TestCaseWithFactory):
    """Tests of traversal to and access of files of bug attachments."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestAccessToBugAttachmentFiles, self).setUp()
        self.bug_owner = self.factory.makePerson()
        getUtility(ILaunchBag).clear()
        login_person(self.bug_owner)
        self.bug = self.factory.makeBug(owner=self.bug_owner)
        self.bugattachment = self.factory.makeBugAttachment(
            bug=self.bug, filename='foo.txt', data='file content')

    def test_traversal_to_lfa_of_bug_attachment(self):
        # Traversing to the URL provided by a ProxiedLibraryFileAlias of a
        # bug attachament returns a StreamOrRedirectLibraryFileAliasView.
        request = LaunchpadTestRequest()
        request.setTraversalStack(['foo.txt'])
        navigation = BugAttachmentFileNavigation(
            self.bugattachment, request)
        view = navigation.publishTraverse(request, '+files')
        self.assertIsInstance(view, StreamOrRedirectLibraryFileAliasView)

    def test_traversal_to_lfa_of_bug_attachment_wrong_filename(self):
        # If the filename provided in the URL does not match the
        # filename of the LibraryFileAlias, a NotFound error is raised.
        request = LaunchpadTestRequest()
        request.setTraversalStack(['nonsense'])
        navigation = BugAttachmentFileNavigation(self.bugattachment, request)
        self.assertRaises(
            NotFound, navigation.publishTraverse, request, '+files')

    def test_access_to_unrestricted_file(self):
        # Requests of unrestricted files are redirected to Librarian URLs.
        request = LaunchpadTestRequest()
        request.setTraversalStack(['foo.txt'])
        navigation = BugAttachmentFileNavigation(
            self.bugattachment, request)
        view = navigation.publishTraverse(request, '+files')
        next_view, traversal_path = view.browserDefault(request)
        self.assertIsInstance(next_view, RedirectionView)
        mo = re.match(
            '^http://localhost:58000/\d+/foo.txt$', next_view.target)
        self.assertIsNot(None, mo)

    def test_access_to_restricted_file(self):
        # Requests of restricted files are handled by ProxiedLibraryFileAlias.
        lfa_with_parent = getMultiAdapter(
            (self.bugattachment.libraryfile, self.bugattachment),
            ILibraryFileAliasWithParent)
        lfa_with_parent.restricted = True
        self.bug.setPrivate(True, self.bug_owner)
        transaction.commit()
        request = LaunchpadTestRequest()
        request.setTraversalStack(['foo.txt'])
        navigation = BugAttachmentFileNavigation(self.bugattachment, request)
        view = navigation.publishTraverse(request, '+files')
        next_view, traversal_path = view.browserDefault(request)
        self.assertEqual(view, next_view)
        file_ = next_view()
        file_.seek(0)
        self.assertEqual('file content', file_.read())

    def test_access_to_restricted_file_unauthorized(self):
        # If a user cannot access the bug attachment itself, he can neither
        # access the restricted Librarian file.
        lfa_with_parent = getMultiAdapter(
            (self.bugattachment.libraryfile, self.bugattachment),
            ILibraryFileAliasWithParent)
        lfa_with_parent.restricted = True
        self.bug.setPrivate(True, self.bug_owner)
        transaction.commit()
        user = self.factory.makePerson()
        login_person(user)
        self.assertRaises(Unauthorized, getattr, self.bugattachment, 'title')
        request = LaunchpadTestRequest()
        request.setTraversalStack(['foo.txt'])
        navigation = BugAttachmentFileNavigation(self.bugattachment, request)
        self.assertRaises(
            Unauthorized, navigation.publishTraverse, request, '+files')

    def test_content_disposition_of_restricted_file(self):
        # The content of restricted Librarian files for bug attachments
        # is served by instances of SafeStreamOrRedirectLibraryFileAliasView
        # which set the content disposition header of the HTTP response for
        # to "attachment".
        lfa_with_parent = getMultiAdapter(
            (self.bugattachment.libraryfile, self.bugattachment),
            ILibraryFileAliasWithParent)
        lfa_with_parent.restricted = True
        self.bug.setPrivate(True, self.bug_owner)
        transaction.commit()
        request = LaunchpadTestRequest()
        request.setTraversalStack(['foo.txt'])
        navigation = BugAttachmentFileNavigation(self.bugattachment, request)
        view = navigation.publishTraverse(request, '+files')
        next_view, traversal_path = view.browserDefault(request)
        self.assertIsInstance(
            next_view, SafeStreamOrRedirectLibraryFileAliasView)
        next_view()
        self.assertEqual(
            'attachment', request.response.getHeader('Content-Disposition'))
