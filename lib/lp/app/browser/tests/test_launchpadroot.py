# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests related to ILaunchpadRoot."""

__metaclass__ = type


from BeautifulSoup import BeautifulSoup, SoupStrainer

from zope.component import getUtility
from zope.security.checker import selectChecker

from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.webapp.interfaces import ILaunchpadRoot
from canonical.launchpad.webapp.authorization import check_permission
from canonical.testing.layers import DatabaseFunctionalLayer

from lp.registry.interfaces.person import IPersonSet
from lp.testing import login_person, TestCaseWithFactory
from lp.testing.views import create_initialized_view, create_view


class LaunchpadRootPermissionTest(TestCaseWithFactory):
    """Test for the ILaunchpadRoot permission"""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.root = getUtility(ILaunchpadRoot)
        self.admin = getUtility(IPersonSet).getByEmail(
            'foo.bar@canonical.com')

    def setUpRegistryExpert(self):
        """Create a registry expert and logs in as them."""
        login_person(self.admin)
        self.expert = self.factory.makePerson()
        getUtility(ILaunchpadCelebrities).registry_experts.addMember(
            self.expert, self.admin)
        login_person(self.expert)

    def test_anonymous_cannot_edit(self):
        self.failIf(check_permission('launchpad.Edit', self.root),
            "Anonymous user shouldn't have launchpad.Edit on ILaunchpadRoot")

    def test_regular_user_cannot_edit(self):
        login_person(self.factory.makePerson())
        self.failIf(check_permission('launchpad.Edit', self.root),
            "Regular users shouldn't have launchpad.Edit on ILaunchpadRoot")

    def test_registry_expert_can_edit(self):
        self.setUpRegistryExpert()
        self.failUnless(check_permission('launchpad.Edit', self.root),
            "Registry experts should have launchpad.Edit on ILaunchpadRoot")

    def test_admins_can_edit(self):
        login_person(self.admin)
        self.failUnless(check_permission('launchpad.Edit', self.root),
            "Admins should have launchpad.Edit on ILaunchpadRoot")

    def test_featured_projects_view_requires_edit(self):
        view = create_view(self.root, '+featuredprojects')
        checker = selectChecker(view)
        self.assertEquals('launchpad.Edit', checker.permission_id('__call__'))

    def test_featured_projects_manage_link_requires_edit(self):
        self.setUpRegistryExpert()
        view = create_initialized_view(
            self.root, 'index.html', principal=self.expert)
        # Stub out the getRecentBlogPosts which fetches a blog feed using
        # urlfetch.
        view.getRecentBlogPosts = lambda: []
        content = BeautifulSoup(view(), parseOnlyThese=SoupStrainer('a'))
        self.failUnless(
            content.find('a', href='+featuredprojects'),
            "Cannot find the +featuredprojects link on the first page")
