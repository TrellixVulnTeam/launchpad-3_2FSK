# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the database garbage collector."""

__metaclass__ = type
__all__ = []

from datetime import datetime, timedelta
import tempfile
import time
import unittest

from pytz import UTC
from storm.expr import Min, SQL
from storm.store import Store
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.database.constants import THIRTY_DAYS_AGO, UTC_NOW
from canonical.launchpad.database.emailaddress import EmailAddress
from canonical.launchpad.database.message import Message
from canonical.launchpad.database.oauth import OAuthNonce
from canonical.launchpad.database.openidconsumer import OpenIDConsumerNonce
from canonical.launchpad.interfaces import IMasterStore
from canonical.launchpad.interfaces.emailaddress import EmailAddressStatus
from lp.code.enums import CodeImportResultStatus
from lp.testing import TestCase, TestCaseWithFactory
from canonical.launchpad.scripts.garbo import (
    DailyDatabaseGarbageCollector, HourlyDatabaseGarbageCollector,
    OpenIDAssociationPruner, OpenIDConsumerAssociationPruner)
from canonical.launchpad.scripts.tests import run_script
from canonical.launchpad.scripts.logger import QuietFakeLogger
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, MASTER_FLAVOR)
from canonical.testing.layers import (
    DatabaseLayer, LaunchpadScriptLayer, LaunchpadZopelessLayer)
from lp.bugs.model.bugnotification import (
    BugNotification, BugNotificationRecipient)
from lp.code.bzr import BranchFormat, RepositoryFormat
from lp.code.model.branchjob import BranchJob, BranchUpgradeJob
from lp.code.model.codeimportresult import CodeImportResult
from lp.registry.interfaces.person import IPersonSet, PersonCreationRationale
from lp.registry.model.person import Person
from lp.services.job.model.job import Job


class TestGarboScript(TestCase):
    layer = LaunchpadScriptLayer

    def test_daily_script(self):
        """Ensure garbo-daily.py actually runs."""
        rv, out, err = run_script(
            "cronscripts/garbo-daily.py", ["-q"], expect_returncode=0)
        self.failIf(out.strip(), "Output to stdout: %s" % out)
        self.failIf(err.strip(), "Output to stderr: %s" % err)
        DatabaseLayer.force_dirty_database()

    def test_hourly_script(self):
        """Ensure garbo-hourly.py actually runs."""
        rv, out, err = run_script(
            "cronscripts/garbo-hourly.py", ["-q"], expect_returncode=0)
        self.failIf(out.strip(), "Output to stdout: %s" % out)
        self.failIf(err.strip(), "Output to stderr: %s" % err)


class TestGarbo(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestGarbo, self).setUp()
        # Run the garbage collectors to remove any existing garbage,
        # starting us in a known state.
        self.runDaily()
        self.runHourly()

    def runDaily(self, maximum_chunk_size=2, test_args=()):
        LaunchpadZopelessLayer.switchDbUser('garbo_daily')
        collector = DailyDatabaseGarbageCollector(test_args=list(test_args))
        collector._maximum_chunk_size = maximum_chunk_size
        collector.logger = QuietFakeLogger()
        collector.main()
        return collector

    def runHourly(self, maximum_chunk_size=2, test_args=()):
        LaunchpadZopelessLayer.switchDbUser('garbo_hourly')
        collector = HourlyDatabaseGarbageCollector(test_args=list(test_args))
        collector._maximum_chunk_size = maximum_chunk_size
        collector.logger = QuietFakeLogger()
        collector.main()
        return collector

    def test_OAuthNoncePruner(self):
        now = datetime.utcnow().replace(tzinfo=UTC)
        timestamps = [
            now - timedelta(days=2), # Garbage
            now - timedelta(days=1) - timedelta(seconds=60), # Garbage
            now - timedelta(days=1) + timedelta(seconds=60), # Not garbage
            now, # Not garbage
            ]
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        store = IMasterStore(OAuthNonce)

        # Make sure we start with 0 nonces.
        self.failUnlessEqual(store.find(OAuthNonce).count(), 0)

        for timestamp in timestamps:
            OAuthNonce(
                access_tokenID=1,
                request_timestamp = timestamp,
                nonce = str(timestamp))
        transaction.commit()

        # Make sure we have 4 nonces now.
        self.failUnlessEqual(store.find(OAuthNonce).count(), 4)

        self.runHourly(maximum_chunk_size=60) # 1 minute maximum chunk size

        store = IMasterStore(OAuthNonce)

        # Now back to two, having removed the two garbage entries.
        self.failUnlessEqual(store.find(OAuthNonce).count(), 2)

        # And none of them are older than a day.
        # Hmm... why is it I'm putting tz aware datetimes in and getting
        # naive datetimes back? Bug in the SQLObject compatibility layer?
        # Test is still fine as we know the timezone.
        self.failUnless(
            store.find(
                Min(OAuthNonce.request_timestamp)).one().replace(tzinfo=UTC)
            >= now - timedelta(days=1))

    def test_OpenIDConsumerNoncePruner(self):
        now = int(time.mktime(time.gmtime()))
        MINUTES = 60
        HOURS = 60 * 60
        DAYS = 24 * HOURS
        timestamps = [
            now - 2 * DAYS, # Garbage
            now - 1 * DAYS - 1 * MINUTES, # Garbage
            now - 1 * DAYS + 1 * MINUTES, # Not garbage
            now, # Not garbage
            ]
        LaunchpadZopelessLayer.switchDbUser('testadmin')

        store = IMasterStore(OpenIDConsumerNonce)

        # Make sure we start with 0 nonces.
        self.failUnlessEqual(store.find(OpenIDConsumerNonce).count(), 0)

        for timestamp in timestamps:
            store.add(OpenIDConsumerNonce(
                    u'http://server/', timestamp, u'aa'))
        transaction.commit()

        # Make sure we have 4 nonces now.
        self.failUnlessEqual(store.find(OpenIDConsumerNonce).count(), 4)

        # Run the garbage collector.
        self.runHourly(maximum_chunk_size=60) # 1 minute maximum chunks.

        store = IMasterStore(OpenIDConsumerNonce)

        # We should now have 2 nonces.
        self.failUnlessEqual(store.find(OpenIDConsumerNonce).count(), 2)

        # And none of them are older than 1 day
        earliest = store.find(Min(OpenIDConsumerNonce.timestamp)).one()
        self.failUnless(earliest >= now - 24*60*60, 'Still have old nonces')

    def test_CodeImportResultPruner(self):
        now = datetime.utcnow().replace(tzinfo=UTC)
        store = IMasterStore(CodeImportResult)

        results_to_keep_count = (
            config.codeimport.consecutive_failure_limit - 1)

        def new_code_import_result(timestamp):
            LaunchpadZopelessLayer.switchDbUser('testadmin')
            CodeImportResult(
                date_created=timestamp,
                code_importID=1, machineID=1, requesting_userID=1,
                status=CodeImportResultStatus.FAILURE,
                date_job_started=timestamp)
            transaction.commit()

        new_code_import_result(now - timedelta(days=60))
        for i in range(results_to_keep_count - 1):
            new_code_import_result(now - timedelta(days=19+i))

        # Run the garbage collector
        self.runDaily()

        # Nothing is removed, because we always keep the
        # ``results_to_keep_count`` latest.
        store = IMasterStore(CodeImportResult)
        self.failUnlessEqual(
            results_to_keep_count,
            store.find(CodeImportResult).count())

        new_code_import_result(now - timedelta(days=31))
        self.runDaily()
        store = IMasterStore(CodeImportResult)
        self.failUnlessEqual(
            results_to_keep_count,
            store.find(CodeImportResult).count())

        new_code_import_result(now - timedelta(days=29))
        self.runDaily()
        store = IMasterStore(CodeImportResult)
        self.failUnlessEqual(
            results_to_keep_count,
            store.find(CodeImportResult).count())

        # We now have no CodeImportResults older than 30 days
        self.failUnless(
            store.find(
                Min(CodeImportResult.date_created)).one().replace(tzinfo=UTC)
            >= now - timedelta(days=30))

    def test_OpenIDAssociationPruner(self, pruner=OpenIDAssociationPruner):
        store_name = pruner.store_name
        table_name = pruner.table_name
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        store_selector = getUtility(IStoreSelector)
        store = store_selector.get(store_name, MASTER_FLAVOR)
        now = time.time()
        # Create some associations in the past with lifetimes
        for delta in range(0, 20):
            store.execute("""
                INSERT INTO %s (server_url, handle, issued, lifetime)
                VALUES (%s, %s, %d, %d)
                """ % (table_name, str(delta), str(delta), now-10, delta))
        transaction.commit()

        # Ensure that we created at least one expirable row (using the
        # test start time as 'now').
        num_expired = store.execute("""
            SELECT COUNT(*) FROM %s
            WHERE issued + lifetime < %f
            """ % (table_name, now)).get_one()[0]
        self.failUnless(num_expired > 0)

        # Expire all those expirable rows, and possibly a few more if this
        # test is running slow.
        self.runHourly()

        LaunchpadZopelessLayer.switchDbUser('testadmin')
        store = store_selector.get(store_name, MASTER_FLAVOR)
        # Confirm all the rows we know should have been expired have
        # been expired. These are the ones that would be expired using
        # the test start time as 'now'.
        num_expired = store.execute("""
            SELECT COUNT(*) FROM %s
            WHERE issued + lifetime < %f
            """ % (table_name, now)).get_one()[0]
        self.failUnlessEqual(num_expired, 0)

        # Confirm that we haven't expired everything. This test will fail
        # if it has taken 10 seconds to get this far.
        num_unexpired = store.execute(
            "SELECT COUNT(*) FROM %s" % table_name).get_one()[0]
        self.failUnless(num_unexpired > 0)

    def test_OpenIDConsumerAssociationPruner(self):
        self.test_OpenIDAssociationPruner(OpenIDConsumerAssociationPruner)

    def test_RevisionAuthorEmailLinker(self):
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        rev1 = self.factory.makeRevision('Author 1 <author-1@Example.Org>')
        rev2 = self.factory.makeRevision('Author 2 <author-2@Example.Org>')
        rev3 = self.factory.makeRevision('Author 3 <author-3@Example.Org>')

        person1 = self.factory.makePerson(email='Author-1@example.org')
        person2 = self.factory.makePerson(
            email='Author-2@example.org',
            email_address_status=EmailAddressStatus.NEW)
        account3 = self.factory.makeAccount(
            'Author 3', 'Author-3@example.org')

        self.assertEqual(rev1.revision_author.person, None)
        self.assertEqual(rev2.revision_author.person, None)
        self.assertEqual(rev3.revision_author.person, None)

        self.runDaily()

        # Only the validated email address associated with a Person
        # causes a linkage.
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        self.assertEqual(rev1.revision_author.person, person1)
        self.assertEqual(rev2.revision_author.person, None)
        self.assertEqual(rev3.revision_author.person, None)

        # Validating an email address creates a linkage.
        person2.validateAndEnsurePreferredEmail(person2.guessedemails[0])
        self.assertEqual(rev2.revision_author.person, None)
        transaction.commit()

        self.runDaily()
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        self.assertEqual(rev2.revision_author.person, person2)

        # Creating a person for an existing account creates a linkage.
        person3 = account3.createPerson(PersonCreationRationale.UNKNOWN)
        self.assertEqual(rev3.revision_author.person, None)
        transaction.commit()

        self.runDaily()
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        self.assertEqual(rev3.revision_author.person, person3)

    def test_HWSubmissionEmailLinker(self):
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        sub1 = self.factory.makeHWSubmission(
            emailaddress='author-1@Example.Org')
        sub2 = self.factory.makeHWSubmission(
            emailaddress='author-2@Example.Org')
        sub3 = self.factory.makeHWSubmission(
            emailaddress='author-3@Example.Org')

        person1 = self.factory.makePerson(email='Author-1@example.org')
        person2 = self.factory.makePerson(
            email='Author-2@example.org',
            email_address_status=EmailAddressStatus.NEW)
        account3 = self.factory.makeAccount(
            'Author 3', 'Author-3@example.org')

        self.assertEqual(sub1.owner, None)
        self.assertEqual(sub2.owner, None)
        self.assertEqual(sub3.owner, None)

        self.runDaily()

        # Only the validated email address associated with a Person
        # causes a linkage.
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        self.assertEqual(sub1.owner, person1)
        self.assertEqual(sub2.owner, None)
        self.assertEqual(sub3.owner, None)

        # Validating an email address creates a linkage.
        person2.validateAndEnsurePreferredEmail(person2.guessedemails[0])
        self.assertEqual(sub2.owner, None)
        transaction.commit()

        self.runDaily()
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        self.assertEqual(sub2.owner, person2)

        # Creating a person for an existing account creates a linkage.
        person3 = account3.createPerson(PersonCreationRationale.UNKNOWN)
        self.assertEqual(sub3.owner, None)
        transaction.commit()

        self.runDaily()
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        self.assertEqual(sub3.owner, person3)

    def test_MailingListSubscriptionPruner(self):
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        team, mailing_list = self.factory.makeTeamAndMailingList(
            'mlist-team', 'mlist-owner')
        person = self.factory.makePerson(email='preferred@example.org')
        email = self.factory.makeEmail('secondary@example.org', person)
        transaction.commit()
        mailing_list.subscribe(person, email)
        transaction.commit()

        # User remains subscribed if we run the garbage collector.
        self.runDaily()
        self.assertNotEqual(mailing_list.getSubscription(person), None)

        # If we remove the email address that was subscribed, the
        # garbage collector removes the subscription.
        Store.of(email).remove(email)
        transaction.commit()
        self.runDaily()
        self.assertEqual(mailing_list.getSubscription(person), None)

    def test_PersonPruner(self):
        personset = getUtility(IPersonSet)
        # Switch the DB user because the garbo_daily user isn't allowed to
        # create person entries.
        LaunchpadZopelessLayer.switchDbUser('testadmin')

        # Create two new person entries, both not linked to anything. One of
        # them will have the present day as its date created, and so will not
        # be deleted, whereas the other will have a creation date far in the
        # past, so it will be deleted.
        person = self.factory.makePerson(name='test-unlinked-person-new')
        person_old = self.factory.makePerson(name='test-unlinked-person-old')
        removeSecurityProxy(person_old).datecreated = datetime(
            2008, 01, 01, tzinfo=UTC)
        transaction.commit()

        # Normally, the garbage collector will do nothing because the
        # PersonPruner is experimental
        self.runDaily()
        self.assertIsNot(
            personset.getByName('test-unlinked-person-new'), None)
        self.assertIsNot(
            personset.getByName('test-unlinked-person-old'), None)

        # When we run the garbage collector with experimental jobs turned
        # on, the old unlinked Person is removed.
        self.runDaily(test_args=['--experimental'])
        self.assertIsNot(
            personset.getByName('test-unlinked-person-new'), None)
        self.assertIs(personset.getByName('test-unlinked-person-old'), None)

    def test_BugNotificationPruner(self):
        # Create some sample data
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        notification = BugNotification(
            messageID=1,
            bugID=1,
            is_comment=True,
            date_emailed=None)
        recipient = BugNotificationRecipient(
            bug_notification=notification,
            personID=1,
            reason_header='Whatever',
            reason_body='Whatever')
        # We don't create an entry exactly 30 days old to avoid
        # races in the test.
        for delta in range(-45, -14, 2):
            message = Message(rfc822msgid=str(delta))
            notification = BugNotification(
                message=message,
                bugID=1,
                is_comment=True,
                date_emailed=UTC_NOW + SQL("interval '%d days'" % delta))
            recipient = BugNotificationRecipient(
                bug_notification=notification,
                personID=1,
                reason_header='Whatever',
                reason_body='Whatever')

        store = IMasterStore(BugNotification)

        # Ensure we are at a known starting point.
        num_unsent = store.find(
            BugNotification,
            BugNotification.date_emailed == None).count()
        num_old = store.find(
            BugNotification,
            BugNotification.date_emailed < THIRTY_DAYS_AGO).count()
        num_new = store.find(
            BugNotification,
            BugNotification.date_emailed > THIRTY_DAYS_AGO).count()

        self.assertEqual(num_unsent, 1)
        self.assertEqual(num_old, 8)
        self.assertEqual(num_new, 8)

        # Run the garbage collector.
        transaction.commit()
        self.runDaily()

        # We should have 9 BugNotifications left.
        self.assertEqual(
            store.find(
                BugNotification,
                BugNotification.date_emailed == None).count(),
            num_unsent)
        self.assertEqual(
            store.find(
                BugNotification,
                BugNotification.date_emailed > THIRTY_DAYS_AGO).count(),
            num_new)
        self.assertEqual(
            store.find(
                BugNotification,
                BugNotification.date_emailed < THIRTY_DAYS_AGO).count(),
            0)

    def test_PersonEmailAddressLinkChecker(self):
        LaunchpadZopelessLayer.switchDbUser('testadmin')

        # Make an EmailAddress record reference a non-existant Person.
        emailaddress = IMasterStore(EmailAddress).get(EmailAddress, 16)
        emailaddress.personID = -1

        # Make a Person record reference a different Account to its
        # EmailAddress records.
        person = IMasterStore(Person).get(Person, 1)
        person_email = Store.of(person).find(
            EmailAddress, person=person).any()
        person.accountID = -1

        transaction.commit()

        # Run the garbage collector. We should get two ERROR reports
        # about the corrupt data.
        collector = self.runDaily()

        # The PersonEmailAddressLinkChecker is not intelligent enough
        # to repair corruption. It is only there to alert us to the
        # issue so data can be manually repaired and the cause
        # tracked down and fixed.
        self.assertEqual(emailaddress.personID, -1)
        self.assertNotEqual(person.accountID, person_email.accountID)

        # The corruption has been reported though as a ERROR messages.
        log_output = collector.logger.output_file.getvalue()
        error_message_1 = (
            "ERROR Corruption - "
            "'test@canonical.com' is linked to a non-existant Person.")
        self.assertNotEqual(log_output.find(error_message_1), -1)
        error_message_2 = (
            "ERROR Corruption - "
            "'mark@example.com' and 'mark' reference different Accounts")
        self.assertNotEqual(log_output.find(error_message_2), -1)

    def test_BranchJobPruner(self):

        self.useBzrBranches()
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        store = IMasterStore(Job)

        db_branch, tree = self.create_branch_and_tree(
            hosted=True, format='knit')
        db_branch.branch_format = BranchFormat.BZR_BRANCH_5
        db_branch.repository_format = RepositoryFormat.BZR_KNIT_1

        branch_job = BranchUpgradeJob.create(db_branch)
        branch_job.job.date_finished = THIRTY_DAYS_AGO
        job_id = branch_job.job.id

        self.assertEqual(
            store.find(
                BranchJob,
                BranchJob.branch == db_branch.id).count(),
                1)
        transaction.commit()

        collector = self.runDaily()

        LaunchpadZopelessLayer.switchDbUser('testadmin')
        self.assertEqual(
            store.find(
                BranchJob,
                BranchJob.branch == db_branch.id).count(),
                0)


    def test_BranchJobPruner_doesnt_prune_recent_jobs(self):

        self.useBzrBranches()
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        store = IMasterStore(Job)

        db_branch, tree = self.create_branch_and_tree(
            hosted=True, format='knit')
        db_branch.branch_format = BranchFormat.BZR_BRANCH_5
        db_branch.repository_format = RepositoryFormat.BZR_KNIT_1

        branch_job = BranchUpgradeJob.create(db_branch)
        branch_job.job.date_finished = THIRTY_DAYS_AGO
        job_id = branch_job.job.id

        tree_location = tempfile.mkdtemp()
        db_branch_newer, tree_newer = self.create_branch_and_tree(
            tree_location=tree_location, hosted=True, format='knit')
        db_branch_newer.branch_format = BranchFormat.BZR_BRANCH_5
        db_branch_newer.repository_format = RepositoryFormat.BZR_KNIT_1

        branch_job_newer = BranchUpgradeJob.create(db_branch_newer)
        job_id_newer = branch_job_newer.job.id

        self.assertEqual(
            store.find(
                BranchJob,
                BranchJob.branch == db_branch.id).count(),
                1)
        transaction.commit()

        collector = self.runDaily()

        LaunchpadZopelessLayer.switchDbUser('testadmin')
        self.assertEqual(
            store.find(
                BranchJob).count(),
            1)

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
