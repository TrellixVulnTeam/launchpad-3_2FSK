# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the webhook webservice objects."""

__metaclass__ = type

import json

from testtools.matchers import (
    ContainsDict,
    Equals,
    GreaterThan,
    )

from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    api_url,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import (
    LaunchpadWebServiceCaller,
    webservice_for_person,
    )


class TestWebhook(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestWebhook, self).setUp()
        target = self.factory.makeGitRepository()
        self.owner = target.owner
        with person_logged_in(self.owner):
            self.webhook = self.factory.makeWebhook(
                target=target, delivery_url=u'http://example.com/ep')
            self.webhook_url = api_url(self.webhook)
        self.webservice = webservice_for_person(
            self.owner, permission=OAuthPermission.WRITE_PRIVATE)

    def test_get(self):
        representation = self.webservice.get(
            self.webhook_url, api_version='devel').jsonBody()
        self.assertContentEqual(
            ['active', 'date_created', 'date_last_modified', 'delivery_url',
             'http_etag', 'registrant_link', 'resource_type_link',
             'self_link', 'target_link', 'web_link'],
            representation.keys())

    def test_patch(self):
        representation = self.webservice.get(
            self.webhook_url, api_version='devel').jsonBody()
        self.assertThat(
            representation,
            ContainsDict(
                {'active': Equals(True),
                 'delivery_url': Equals('http://example.com/ep')}))
        old_mtime = representation['date_last_modified']
        patch = json.dumps(
            {'active': False, 'delivery_url': 'http://example.com/ep2'})
        self.webservice.patch(
            self.webhook_url, 'application/json', patch, api_version='devel')
        representation = self.webservice.get(
            self.webhook_url, api_version='devel').jsonBody()
        self.assertThat(
            representation,
            ContainsDict(
                {'active': Equals(False),
                 'delivery_url': Equals('http://example.com/ep2'),
                 'date_last_modified': GreaterThan(old_mtime)}))

    def test_anon_forbidden(self):
        response = LaunchpadWebServiceCaller().get(
            self.webhook_url, api_version='devel')
        self.assertEqual(401, response.status)
        self.assertIn('launchpad.View', response.body)


class TestWebhookTarget(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestWebhookTarget, self).setUp()
        self.target = self.factory.makeGitRepository()
        self.owner = self.target.owner
        self.target_url = api_url(self.target)
        self.webservice = webservice_for_person(
            self.owner, permission=OAuthPermission.WRITE_PRIVATE)

    def test_webhooks(self):
        with person_logged_in(self.owner):
            for ep in (u'http://example.com/ep1', u'http://example.com/ep2'):
                self.factory.makeWebhook(target=self.target, delivery_url=ep)
        representation = self.webservice.get(
            self.target_url + '/webhooks', api_version='devel').jsonBody()
        self.assertContentEqual(
            ['http://example.com/ep1', 'http://example.com/ep2'],
            [entry['delivery_url'] for entry in representation['entries']])

    def test_webhooks_permissions(self):
        webservice = LaunchpadWebServiceCaller()
        response = webservice.get(
            self.target_url + '/webhooks', api_version='devel')
        self.assertEqual(401, response.status)
        self.assertIn('launchpad.Edit', response.body)

    def test_newWebhook(self):
        response = self.webservice.named_post(
            self.target_url, 'newWebhook',
            delivery_url='http://example.com/ep', api_version='devel')
        self.assertEqual(201, response.status)

        representation = self.webservice.get(
            self.target_url + '/webhooks', api_version='devel').jsonBody()
        self.assertContentEqual(
            [('http://example.com/ep', True)],
            [(entry['delivery_url'], entry['active'])
             for entry in representation['entries']])

    def test_newWebhook_permissions(self):
        webservice = LaunchpadWebServiceCaller()
        response = webservice.named_post(
            self.target_url, 'newWebhook',
            delivery_url='http://example.com/ep', api_version='devel')
        self.assertEqual(401, response.status)
        self.assertIn('launchpad.Edit', response.body)
