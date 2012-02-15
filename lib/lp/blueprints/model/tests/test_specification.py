# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for blueprints here."""

__metaclass__ = type

from testtools.matchers import Equals

from lp.app.validators import LaunchpadValidationError
from lp.blueprints.interfaces.specification import ISpecification
from lp.blueprints.interfaces.specificationworkitem import (
    SpecificationWorkItemStatus,
    )
from lp.blueprints.model.specificationworkitem import SpecificationWorkItem
from lp.services.webapp import canonical_url
from lp.testing import (
    TestCaseWithFactory,
    ANONYMOUS,
    login,
    login_person,
    )
from lp.testing.layers import DatabaseFunctionalLayer
from zope.security.interfaces import Unauthorized


class TestSpecificationDependencies(TestCaseWithFactory):
    """Test the methods for getting the dependencies for blueprints."""

    layer = DatabaseFunctionalLayer

    def test_no_deps(self):
        blueprint = self.factory.makeBlueprint()
        self.assertThat(list(blueprint.dependencies), Equals([]))
        self.assertThat(list(blueprint.all_deps), Equals([]))
        self.assertThat(list(blueprint.blocked_specs), Equals([]))
        self.assertThat(list(blueprint.all_blocked), Equals([]))

    def test_single_dependency(self):
        do_first = self.factory.makeBlueprint()
        do_next = self.factory.makeBlueprint()
        do_next.createDependency(do_first)
        self.assertThat(list(do_first.blocked_specs), Equals([do_next]))
        self.assertThat(list(do_first.all_blocked), Equals([do_next]))
        self.assertThat(list(do_next.dependencies), Equals([do_first]))
        self.assertThat(list(do_next.all_deps), Equals([do_first]))

    def test_linear_dependency(self):
        do_first = self.factory.makeBlueprint()
        do_next = self.factory.makeBlueprint()
        do_next.createDependency(do_first)
        do_last = self.factory.makeBlueprint()
        do_last.createDependency(do_next)
        self.assertThat(sorted(do_first.blocked_specs), Equals([do_next]))
        self.assertThat(
            sorted(do_first.all_blocked),
            Equals(sorted([do_next, do_last])))
        self.assertThat(sorted(do_last.dependencies), Equals([do_next]))
        self.assertThat(
            sorted(do_last.all_deps),
            Equals(sorted([do_first, do_next])))

    def test_diamond_dependency(self):
        #             do_first
        #            /        \
        #    do_next_lhs    do_next_rhs
        #            \        /
        #             do_last
        do_first = self.factory.makeBlueprint()
        do_next_lhs = self.factory.makeBlueprint()
        do_next_lhs.createDependency(do_first)
        do_next_rhs = self.factory.makeBlueprint()
        do_next_rhs.createDependency(do_first)
        do_last = self.factory.makeBlueprint()
        do_last.createDependency(do_next_lhs)
        do_last.createDependency(do_next_rhs)
        self.assertThat(
            sorted(do_first.blocked_specs),
            Equals(sorted([do_next_lhs, do_next_rhs])))
        self.assertThat(
            sorted(do_first.all_blocked),
            Equals(sorted([do_next_lhs, do_next_rhs, do_last])))
        self.assertThat(
            sorted(do_last.dependencies),
            Equals(sorted([do_next_lhs, do_next_rhs])))
        self.assertThat(
            sorted(do_last.all_deps),
            Equals(sorted([do_first, do_next_lhs, do_next_rhs])))


class TestSpecificationSubscriptionSort(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_subscribers(self):
        # Subscriptions are sorted by subscriber's displayname without regard
        # to case
        spec = self.factory.makeBlueprint()
        bob = self.factory.makePerson(name='zbob', displayname='Bob')
        ced = self.factory.makePerson(name='xed', displayname='ced')
        dave = self.factory.makePerson(name='wdave', displayname='Dave')
        spec.subscribe(bob, bob, True)
        spec.subscribe(ced, bob, True)
        spec.subscribe(dave, bob, True)
        sorted_subscriptions = [bob.displayname, ced.displayname,
            dave.displayname]
        people = [sub.person.displayname for sub in spec.subscriptions]
        self.assertEqual(sorted_subscriptions, people)


class TestSpecificationValidation(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_specurl_validation_duplicate(self):
        existing = self.factory.makeSpecification(
            specurl=u'http://ubuntu.com')
        spec = self.factory.makeSpecification()
        url = canonical_url(existing)
        field = ISpecification['specurl'].bind(spec)
        e = self.assertRaises(LaunchpadValidationError, field.validate,
            u'http://ubuntu.com')
        self.assertEqual(
            '%s is already registered by <a href="%s">%s</a>.'
            % (u'http://ubuntu.com', url, existing.title), str(e))

    def test_specurl_validation_valid(self):
        spec = self.factory.makeSpecification()
        field = ISpecification['specurl'].bind(spec)
        field.validate(u'http://example.com/nigelb')

    def test_specurl_validation_escape(self):
        existing = self.factory.makeSpecification(
                specurl=u'http://ubuntu.com/foo',
                title='<script>alert("foo");</script>')
        cleaned_title = '&lt;script&gt;alert("foo");&lt;/script&gt;'
        spec = self.factory.makeSpecification()
        url = canonical_url(existing)
        field = ISpecification['specurl'].bind(spec)
        e = self.assertRaises(LaunchpadValidationError, field.validate,
            u'http://ubuntu.com/foo')
        self.assertEqual(
            '%s is already registered by <a href="%s">%s</a>.'
            % (u'http://ubuntu.com/foo', url, cleaned_title), str(e))


class TestSpecificationWorkItems(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_anonymous_newworkitem_not_allowed(self):
        spec = self.factory.makeSpecification()
        login(ANONYMOUS)
        self.assertRaises(Unauthorized, getattr, spec, 'newWorkItem')

    def test_owner_newworkitem_allowed(self):
        spec = self.factory.makeSpecification()
        login_person(spec.owner)
        work_item = spec.newWorkItem(title=u'new-work-item', sequence=0)
        self.assertIsInstance(work_item, SpecificationWorkItem)

    def test_newworkitem_uses_passed_arguments(self):
        title = u'new-work-item'
        spec = self.factory.makeSpecification()
        assignee = self.factory.makePerson()
        milestone = self.factory.makeMilestone()
        status = SpecificationWorkItemStatus.DONE
        login_person(spec.owner)
        work_item = spec.newWorkItem(
            title=title, assignee=assignee, milestone=milestone,
            status=status, sequence=0)
        self.assertEqual(spec, work_item.specification)
        self.assertEqual(assignee, work_item.assignee)
        self.assertEqual(status, work_item.status)
        self.assertEqual(title, work_item.title)
        self.assertEqual(milestone, work_item.milestone)
