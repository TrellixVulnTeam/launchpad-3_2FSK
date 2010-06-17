# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version (see the file LICENSE).

"""Unit tests for bug configuration views."""

__metaclass__ = type

import unittest

from lp.testing import login_person, TestCaseWithFactory
from lp.testing.views import create_initialized_view
from canonical.testing import DatabaseFunctionalLayer


class TestProductBugConfigurationView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProductBugConfigurationView, self).setUp()
        self.owner = self.factory.makePerson(name='boing-owner')
        self.product = self.factory.makeProduct(
            name='boing', owner=self.owner)
        login_person(self.owner)

    def _makeForm(self):
        return {
            'field.bug_supervisor': 'boing-owner',
            'field.security_contact': 'boing-owner',
            'field.bugtracker': 'malone',
            'field.enable_bug_expiration': 'on',
            'field.remote_product': 'sf-boing',
            'field.bug_reporting_guidelines': 'guidelines',
            'field.actions.change': 'Change',
            }

    def test_view_attributes(self):
        view = create_initialized_view(
            self.product, name='+configure-bugtracker')
        label = 'Configure bug tracker'
        self.assertEqual(label, view.label)
        fields = [
            'bug_supervisor', 'security_contact', 'bugtracker',
            'enable_bug_expiration', 'remote_product',
            'bug_reporting_guidelines']
        self.assertEqual(fields, view.field_names)
        self.assertEqual('http://launchpad.dev/boing', view.next_url)
        self.assertEqual('http://launchpad.dev/boing', view.cancel_url)

    def test_all_data_change(self):
        # Verify that the composed interface supports all fields.
        # This is a sanity check. The bug_supervisor, security_contact and
        # bugtracker field are rigorously tested in their respective tests.
        form = self._makeForm()
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertEqual(self.owner, self.product.bug_supervisor)
        self.assertEqual(self.owner, self.product.security_contact)
        self.assertTrue(self.product.official_malone)
        self.assertTrue(self.product.enable_bug_expiration)
        self.assertEqual('sf-boing', self.product.remote_product)
        self.assertEqual('guidelines', self.product.bug_reporting_guidelines)

    def test_bug_supervisor_invalid(self):
        # Verify that invalid bug_supervisor states are reported.
        # This is a sanity check. The bug_supervisor is rigorously tested
        # in its own test.
        other_person = self.factory.makePerson()
        form = self._makeForm()
        form['field.bug_supervisor'] = other_person.name
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual(1, len(view.errors))

    def test_security_contact_invalid(self):
        # Verify that invalid security_contact states are reported.
        # This is a sanity check. The security_contact is rigorously tested
        # in its own test.
        other_person = self.factory.makePerson()
        form = self._makeForm()
        form['field.security_contact'] = other_person.name
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual(1, len(view.errors))

    def test_enable_bug_expiration_with_launchpad(self):
        # Verify that enable_bug_expiration can be True bugs are tracked
        # in Launchpad.
        form = self._makeForm()
        form['field.enable_bug_expiration'] = 'on'
        form['field.bugtracker'] = 'malone'
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertTrue(self.product.enable_bug_expiration)

    def test_enable_bug_expiration_with_external_bug_tracker(self):
        # Verify that enable_bug_expiration is forced to False when the
        # bug tracker is external.
        form = self._makeForm()
        form['field.enable_bug_expiration'] = 'on'
        form['field.bugtracker'] = 'external'
        form['field.bugtracker.bugtracker'] = 'debbugs'
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertFalse(self.product.enable_bug_expiration)

    def test_enable_bug_expiration_with_no_bug_tracker(self):
        # Verify that enable_bug_expiration is forced to False when the
        # bug tracker is unknown.
        form = self._makeForm()
        form['field.enable_bug_expiration'] = 'on'
        form['field.bugtracker'] = 'project'
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertFalse(self.product.enable_bug_expiration)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
