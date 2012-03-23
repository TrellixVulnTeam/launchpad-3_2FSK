# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for ProductJobs."""

__metaclass__ = type

from datetime import (
    datetime,
    timedelta,
    )

import pytz

from zope.interface import (
    classProvides,
    implements,
    )
from zope.security.proxy import removeSecurityProxy

from lp.registry.enums import ProductJobType
from lp.registry.interfaces.productjob import (
    IProductJob,
    IProductJobSource,
    IProductNotificationJobSource,
    )
from lp.registry.interfaces.person import TeamSubscriptionPolicy
from lp.registry.interfaces.teammembership import TeamMembershipStatus
from lp.registry.model.productjob import (
    ProductJob,
    ProductJobDerived,
    ProductNotificationJob,
    )
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.services.webapp.publisher import canonical_url


class ProductJobTestCase(TestCaseWithFactory):
    """Test case for basic ProductJob class."""

    layer = LaunchpadZopelessLayer

    def test_init(self):
        product = self.factory.makeProduct()
        metadata = ('some', 'arbitrary', 'metadata')
        product_job = ProductJob(
            product, ProductJobType.REVIEWER_NOTIFICATION, metadata)
        self.assertEqual(product, product_job.product)
        self.assertEqual(
            ProductJobType.REVIEWER_NOTIFICATION, product_job.job_type)
        expected_json_data = '["some", "arbitrary", "metadata"]'
        self.assertEqual(expected_json_data, product_job._json_data)

    def test_metadata(self):
        # The python structure stored as json is returned as python.
        product = self.factory.makeProduct()
        metadata = {
            'a_list': ('some', 'arbitrary', 'metadata'),
            'a_number': 1,
            'a_string': 'string',
            }
        product_job = ProductJob(
            product, ProductJobType.REVIEWER_NOTIFICATION, metadata)
        metadata['a_list'] = list(metadata['a_list'])
        self.assertEqual(metadata, product_job.metadata)


class IProductThingJob(IProductJob):
    """An interface for testing derived job classes."""


class IProductThingJobSource(IProductJobSource):
    """An interface for testing derived job source classes."""


class FakeProductJob(ProductJobDerived):
    """A class that reuses other interfaces and types for testing."""
    class_job_type = ProductJobType.REVIEWER_NOTIFICATION
    implements(IProductThingJob)
    classProvides(IProductThingJobSource)


class OtherFakeProductJob(ProductJobDerived):
    """A class that reuses other interfaces and types for testing."""
    class_job_type = ProductJobType.COMMERCIAL_EXPIRED
    implements(IProductThingJob)
    classProvides(IProductThingJobSource)


class ProductJobDerivedTestCase(TestCaseWithFactory):
    """Test case for the ProductJobDerived class."""

    layer = DatabaseFunctionalLayer

    def test_repr(self):
        product = self.factory.makeProduct('fnord')
        metadata = {'foo': 'bar'}
        job = FakeProductJob.create(product, metadata)
        self.assertEqual(
            '<FakeProductJob for fnord status=Waiting>', repr(job))

    def test_create_success(self):
        # Create an instance of ProductJobDerived that delegates to
        # ProductJob.
        product = self.factory.makeProduct()
        metadata = {'foo': 'bar'}
        self.assertIs(True, IProductJobSource.providedBy(ProductJobDerived))
        job = FakeProductJob.create(product, metadata)
        self.assertIsInstance(job, ProductJobDerived)
        self.assertIs(True, IProductJob.providedBy(job))
        self.assertIs(True, IProductJob.providedBy(job.context))

    def test_create_raises_error(self):
        # ProductJobDerived.create() raises an error because it
        # needs to be subclassed to work properly.
        product = self.factory.makeProduct()
        metadata = {'foo': 'bar'}
        self.assertRaises(
            AttributeError, ProductJobDerived.create, product, metadata)

    def test_iterReady(self):
        # iterReady finds job in the READY status that are of the same type.
        product = self.factory.makeProduct()
        metadata = {'foo': 'bar'}
        job_1 = FakeProductJob.create(product, metadata)
        job_2 = FakeProductJob.create(product, metadata)
        job_2.start()
        OtherFakeProductJob.create(product, metadata)
        jobs = list(FakeProductJob.iterReady())
        self.assertEqual(1, len(jobs))
        self.assertEqual(job_1, jobs[0])

    def test_find_product(self):
        # Find all the jobs for a product regardless of date or job type.
        product = self.factory.makeProduct()
        metadata = {'foo': 'bar'}
        job_1 = FakeProductJob.create(product, metadata)
        job_2 = OtherFakeProductJob.create(product, metadata)
        FakeProductJob.create(self.factory.makeProduct(), metadata)
        jobs = list(ProductJobDerived.find(product=product))
        self.assertEqual(2, len(jobs))
        self.assertContentEqual([job_1.id, job_2.id], [job.id for job in jobs])

    def test_find_job_type(self):
        # Find all the jobs for a product and job_type regardless of date.
        product = self.factory.makeProduct()
        metadata = {'foo': 'bar'}
        job_1 = FakeProductJob.create(product, metadata)
        job_2 = FakeProductJob.create(product, metadata)
        OtherFakeProductJob.create(product, metadata)
        jobs = list(ProductJobDerived.find(
            product, job_type=ProductJobType.REVIEWER_NOTIFICATION))
        self.assertEqual(2, len(jobs))
        self.assertContentEqual([job_1.id, job_2.id], [job.id for job in jobs])

    def test_find_date_since(self):
        # Find all the jobs for a product since a date regardless of job_type.
        now = datetime.now(pytz.utc)
        seven_days_ago = now - timedelta(7)
        thirty_days_ago = now - timedelta(30)
        product = self.factory.makeProduct()
        metadata = {'foo': 'bar'}
        job_1 = FakeProductJob.create(product, metadata)
        removeSecurityProxy(job_1.job).date_created = thirty_days_ago
        job_2 = FakeProductJob.create(product, metadata)
        removeSecurityProxy(job_2.job).date_created = seven_days_ago
        job_3 = OtherFakeProductJob.create(product, metadata)
        removeSecurityProxy(job_3.job).date_created = now
        jobs = list(ProductJobDerived.find(product, date_since=seven_days_ago))
        self.assertEqual(2, len(jobs))
        self.assertContentEqual([job_2.id, job_3.id], [job.id for job in jobs])

    def test_log_name(self):
        # The log_name is the name of the implementing class.
        product = self.factory.makeProduct('fnord')
        metadata = {'foo': 'bar'}
        job = FakeProductJob.create(product, metadata)
        self.assertEqual('FakeProductJob', job.log_name)

    def test_getOopsVars(self):
        # The project name is added to the oops vars.
        product = self.factory.makeProduct('fnord')
        metadata = {'foo': 'bar'}
        job = FakeProductJob.create(product, metadata)
        oops_vars = job.getOopsVars()
        self.assertIs(True, len(oops_vars) > 1)
        self.assertIn(('product', product.name), oops_vars)


class ProductNotificationJobTestCase(TestCaseWithFactory):
    """Test case for the ProductNotificationJob class."""

    layer = DatabaseFunctionalLayer

    def make_notification_data(self):
        product = self.factory.makeProduct()
        reviewer = self.factory.makePerson('reviewer@eg.com', name='reviewer')
        subject = "test subject"
        email_template_name = 'product-license-dont-know'
        return product, email_template_name, subject, reviewer

    def test_create(self):
        # Create an instance of ProductNotificationJob that stores
        # the notification information.
        data = self.make_notification_data()
        product, email_template_name, subject, reviewer = data
        self.assertIs(
            True,
            IProductNotificationJobSource.providedBy(ProductNotificationJob))
        job = ProductNotificationJob.create(
            product, email_template_name, subject, reviewer)
        self.assertIsInstance(job, ProductNotificationJob)
        self.assertEqual(product, job.product)
        self.assertEqual(email_template_name, job.email_template_name)
        self.assertEqual(subject, job.subject)
        self.assertEqual(reviewer, job.reviewer)

    def test_getErrorRecipients(self):
        # The reviewer is the error recipient.
        data = self.make_notification_data()
        job = ProductNotificationJob.create(*data)
        self.assertEqual(
            ['Reviewer <reviewer@eg.com>'], job.getErrorRecipients())

    def test_reply_to_commercial(self):
        # Commercial emails have the commercial@launchpad.net reply-to.
        data = list(self.make_notification_data())
        data[1] = 'product-commercial-expires-7-days'
        job = ProductNotificationJob.create(*data)
        self.assertEqual('Commercial <commercial@launchpad.net>', job.reply_to)

    def test_reply_to_non_commercial(self):
        # Non-commercial emails do not have a reply-to.
        data = list(self.make_notification_data())
        data[1] = 'product-license-dont-know'
        job = ProductNotificationJob.create(*data)
        self.assertIs(None, job.reply_to)

    def test_recipients_user(self):
        # The product maintainer is the recipient.
        data = self.make_notification_data()
        job = ProductNotificationJob.create(*data)
        product, email_template_name, subject, reviewer = data
        recipients = job.recipients
        self.assertEqual([product.owner], recipients.getRecipients())
        reason, header = recipients.getReason(product.owner)
        self.assertEqual('Maintainer', header)
        self.assertIn(canonical_url(product), reason)
        self.assertIn(
            'you are the maintainer of %s' % product.displayname, reason)

    def test_recipients_team(self):
        # The product maintainer team admins are the recipient.
        data = self.make_notification_data()
        job = ProductNotificationJob.create(*data)
        product, email_template_name, subject, reviewer = data
        team = self.factory.makeTeam(
            owner=product.owner,
            subscription_policy=TeamSubscriptionPolicy.MODERATED)
        team_admin = self.factory.makePerson()
        with person_logged_in(team.teamowner):
            team.addMember(
                team_admin, team.teamowner, status=TeamMembershipStatus.ADMIN)
            product.owner = team
        recipients = job.recipients
        self.assertContentEqual(
            [team.teamowner, team_admin], recipients.getRecipients())
        reason, header = recipients.getReason(team.teamowner)
        self.assertEqual('Maintainer', header)
        self.assertIn(canonical_url(product), reason)
        self.assertIn(
            'you are an admin of %s which is the maintainer of %s' %
            (team.displayname, product.displayname),
            reason)

    def test_message_data(self):
        # The message_data is a dict of interpolatable strings.
        data = self.make_notification_data()
        job = ProductNotificationJob.create(*data)
        product, email_template_name, subject, reviewer = data
        self.assertEqual(product.name, job.message_data['product_name'])
        self.assertEqual(
            product.displayname, job.message_data['product_displayname'])
        self.assertEqual(
            canonical_url(product), job.message_data['product_url'])
        self.assertEqual(reviewer.name, job.message_data['reviewer_name'])
        self.assertEqual(
            reviewer.displayname, job.message_data['reviewer_displayname'])

    def test_geBodyAndHeaders_with_reply_to(self):
        # The body and headers contain reasons and rationales.
        data = self.make_notification_data()
        job = ProductNotificationJob.create(*data)
        product, email_template_name, subject, reviewer = data
        [address] = job.recipients.getEmails()
        email_template = (
            'hello %(maintainer_name)s %(product_name)s %(reviewer_name)s')
        reply_to = 'me@eg.dom'
        body, headers = job.geBodyAndHeaders(email_template, address, reply_to)
        self.assertIn(reviewer.name, body)
        self.assertIn(product.name, body)
        self.assertIn(product.owner.name, body)
        self.assertIn('\n\n--\nYou received', body)
        expected_headers = [
            ('X-Launchpad-Project', '%s (%s)' %
              (product.displayname, product.name)),
            ('X-Launchpad-Message-Rationale', 'Maintainer'),
            ('Reply-To', reply_to),
            ]
        self.assertContentEqual(expected_headers, headers.items())

    def test_geBodyAndHeaders_without_reply_to(self):
        # The reply-to is an optional argument.
        data = self.make_notification_data()
        job = ProductNotificationJob.create(*data)
        product, email_template_name, subject, reviewer = data
        [address] = job.recipients.getEmails()
        email_template = 'hello'
        body, headers = job.geBodyAndHeaders(email_template, address)
        expected_headers = [
            ('X-Launchpad-Project', '%s (%s)' %
              (product.displayname, product.name)),
            ('X-Launchpad-Message-Rationale', 'Maintainer'),
            ]
        self.assertContentEqual(expected_headers, headers.items())
