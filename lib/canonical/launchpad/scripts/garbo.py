# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database garbage collection."""

__metaclass__ = type
__all__ = ['DailyDatabaseGarbageCollector', 'HourlyDatabaseGarbageCollector']

from datetime import datetime, timedelta
import time

import pytz
import transaction
from psycopg2 import IntegrityError
from zope.component import getUtility
from storm.locals import In, SQL, Max, Min

from canonical.config import config
from canonical.database import postgresql
from canonical.database.constants import THIRTY_DAYS_AGO
from canonical.database.sqlbase import cursor, sqlvalues
from canonical.launchpad.database.emailaddress import EmailAddress
from lp.hardwaredb.model.hwdb import HWSubmission
from canonical.launchpad.database.librarian import LibraryFileAlias
from canonical.launchpad.database.oauth import OAuthNonce
from canonical.launchpad.database.openidconsumer import OpenIDConsumerNonce
from canonical.launchpad.interfaces import IMasterStore
from canonical.launchpad.interfaces.emailaddress import EmailAddressStatus
from canonical.launchpad.interfaces.looptuner import ITunableLoop
from canonical.launchpad.utilities.looptuner import (
    DBLoopTuner, TunableLoop)
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, MAIN_STORE, MASTER_FLAVOR)
from lp.bugs.interfaces.bug import IBugSet
from lp.bugs.model.bugattachment import BugAttachment
from lp.bugs.interfaces.bugjob import ICalculateBugHeatJobSource
from lp.bugs.model.bugnotification import BugNotification
from lp.bugs.model.bugwatch import BugWatch
from lp.bugs.scripts.checkwatches.scheduler import (
    BugWatchScheduler, MAX_SAMPLE_SIZE)
from lp.code.interfaces.revision import IRevisionSet
from lp.code.model.branchjob import BranchJob
from lp.code.model.codeimportresult import CodeImportResult
from lp.code.model.revision import RevisionAuthor, RevisionCache
from lp.registry.model.mailinglist import MailingListSubscription
from lp.registry.model.person import Person
from lp.services.job.model.job import Job
from lp.services.scripts.base import (
    LaunchpadCronScript, SilentLaunchpadScriptFailure)


ONE_DAY_IN_SECONDS = 24*60*60


class OAuthNoncePruner(TunableLoop):
    """An ITunableLoop to prune old OAuthNonce records.

    We remove all OAuthNonce records older than 1 day.
    """
    maximum_chunk_size = 6*60*60 # 6 hours in seconds.

    def __init__(self, log, abort_time=None):
        super(OAuthNoncePruner, self).__init__(log, abort_time)
        self.store = IMasterStore(OAuthNonce)
        self.oldest_age = self.store.execute("""
            SELECT COALESCE(EXTRACT(EPOCH FROM
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                - MIN(request_timestamp)), 0)
            FROM OAuthNonce
            """).get_one()[0]

    def isDone(self):
        return self.oldest_age <= ONE_DAY_IN_SECONDS

    def __call__(self, chunk_size):
        self.oldest_age = max(
            ONE_DAY_IN_SECONDS, self.oldest_age - chunk_size)

        self.log.debug(
            "Removed OAuthNonce rows older than %d seconds"
            % self.oldest_age)

        self.store.find(
            OAuthNonce,
            OAuthNonce.request_timestamp < SQL(
                "CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - interval '%d seconds'"
                % self.oldest_age)).remove()
        transaction.commit()


class OpenIDConsumerNoncePruner(TunableLoop):
    """An ITunableLoop to prune old OpenIDConsumerNonce records.

    We remove all OpenIDConsumerNonce records older than 1 day.
    """
    maximum_chunk_size = 6*60*60 # 6 hours in seconds.

    def __init__(self, log, abort_time=None):
        super(OpenIDConsumerNoncePruner, self).__init__(log, abort_time)
        self.store = getUtility(IStoreSelector).get(MAIN_STORE, MASTER_FLAVOR)
        self.earliest_timestamp = self.store.find(
            Min(OpenIDConsumerNonce.timestamp)).one()
        utc_now = int(time.mktime(time.gmtime()))
        self.earliest_wanted_timestamp = utc_now - ONE_DAY_IN_SECONDS

    def isDone(self):
        return (
            self.earliest_timestamp is None
            or self.earliest_timestamp >= self.earliest_wanted_timestamp)

    def __call__(self, chunk_size):
        self.earliest_timestamp = min(
            self.earliest_wanted_timestamp,
            self.earliest_timestamp + chunk_size)

        self.log.debug(
            "Removing OpenIDConsumerNonce rows older than %s"
            % self.earliest_timestamp)

        self.store.find(
            OpenIDConsumerNonce,
            OpenIDConsumerNonce.timestamp < self.earliest_timestamp).remove()
        transaction.commit()


class OpenIDConsumerAssociationPruner(TunableLoop):
    minimum_chunk_size = 3500
    maximum_chunk_size = 50000

    table_name = 'OpenIDConsumerAssociation'

    _num_removed = None

    def __init__(self, log, abort_time=None):
        super(OpenIDConsumerAssociationPruner, self).__init__(log, abort_time)
        self.store = getUtility(IStoreSelector).get(MAIN_STORE, MASTER_FLAVOR)

    def __call__(self, chunksize):
        result = self.store.execute("""
            DELETE FROM %s
            WHERE (server_url, handle) IN (
                SELECT server_url, handle FROM %s
                WHERE issued + lifetime <
                    EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)
                LIMIT %d
                )
            """ % (self.table_name, self.table_name, int(chunksize)))
        self._num_removed = result._raw_cursor.rowcount
        transaction.commit()

    def isDone(self):
        return self._num_removed == 0


class RevisionCachePruner(TunableLoop):
    """A tunable loop to remove old revisions from the cache."""

    maximum_chunk_size = 100

    def isDone(self):
        """We are done when there are no old revisions to delete."""
        epoch = datetime.now(pytz.UTC) - timedelta(days=30)
        store = IMasterStore(RevisionCache)
        results = store.find(
            RevisionCache, RevisionCache.revision_date < epoch)
        return results.count() == 0

    def __call__(self, chunk_size):
        """Delegate to the `IRevisionSet` implementation."""
        getUtility(IRevisionSet).pruneRevisionCache(chunk_size)
        transaction.commit()


class CodeImportResultPruner(TunableLoop):
    """A TunableLoop to prune unwanted CodeImportResult rows.

    Removes CodeImportResult rows if they are older than 30 days
    and they are not one of the most recent results for that
    CodeImport.
    """
    maximum_chunk_size = 1000
    def __init__(self, log, abort_time=None):
        super(CodeImportResultPruner, self).__init__(log, abort_time)
        self.store = IMasterStore(CodeImportResult)

        self.min_code_import = self.store.find(
            Min(CodeImportResult.code_importID)).one()
        self.max_code_import = self.store.find(
            Max(CodeImportResult.code_importID)).one()

        self.next_code_import_id = self.min_code_import

    def isDone(self):
        return (
            self.min_code_import is None
            or self.next_code_import_id > self.max_code_import)

    def __call__(self, chunk_size):
        self.log.debug(
            "Removing expired CodeImportResults for CodeImports %d -> %d" % (
                self.next_code_import_id,
                self.next_code_import_id + chunk_size - 1))

        self.store.execute("""
            DELETE FROM CodeImportResult
            WHERE
                CodeImportResult.date_created
                    < CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                        - interval '30 days'
                AND CodeImportResult.code_import >= %s
                AND CodeImportResult.code_import < %s + %s
                AND CodeImportResult.id NOT IN (
                    SELECT LatestResult.id
                    FROM CodeImportResult AS LatestResult
                    WHERE
                        LatestResult.code_import
                            = CodeImportResult.code_import
                    ORDER BY LatestResult.date_created DESC
                    LIMIT %s)
            """ % sqlvalues(
                self.next_code_import_id,
                self.next_code_import_id,
                chunk_size,
                config.codeimport.consecutive_failure_limit - 1))
        self.next_code_import_id += chunk_size
        transaction.commit()


class RevisionAuthorEmailLinker(TunableLoop):
    """A TunableLoop that links `RevisionAuthor` objects to `Person` objects.

    `EmailAddress` objects are looked up for `RevisionAuthor` objects
    that have not yet been linked to a `Person`.  If the
    `EmailAddress` is linked to a person, then the `RevisionAuthor` is
    linked to the same.
    """

    maximum_chunk_size = 1000

    def __init__(self, log, abort_time=None):
        super(RevisionAuthorEmailLinker, self).__init__(log, abort_time)
        self.author_store = IMasterStore(RevisionAuthor)
        self.email_store = IMasterStore(EmailAddress)

        (self.min_author_id,
         self.max_author_id) = self.author_store.find(
            (Min(RevisionAuthor.id), Max(RevisionAuthor.id))).one()

        self.next_author_id = self.min_author_id

    def isDone(self):
        return (self.min_author_id is None or
                self.next_author_id > self.max_author_id)

    def __call__(self, chunk_size):
        result = self.author_store.find(
            RevisionAuthor,
            RevisionAuthor.id >= self.next_author_id,
            RevisionAuthor.personID == None,
            RevisionAuthor.email != None)
        result.order_by(RevisionAuthor.id)
        authors = list(result[:chunk_size])

        # No more authors found.
        if len(authors) == 0:
            self.next_author_id = self.max_author_id + 1
            transaction.commit()
            return

        emails = dict(self.email_store.find(
            (EmailAddress.email.lower(), EmailAddress.personID),
            EmailAddress.email.lower().is_in(
                    [author.email.lower() for author in authors]),
            EmailAddress.status.is_in([EmailAddressStatus.PREFERRED,
                                       EmailAddressStatus.VALIDATED]),
            EmailAddress.personID != None))

        if emails:
            for author in authors:
                personID = emails.get(author.email.lower())
                if personID is None:
                    continue
                author.personID = personID

        self.next_author_id = authors[-1].id + 1
        transaction.commit()


class HWSubmissionEmailLinker(TunableLoop):
    """A TunableLoop that links `HWSubmission` objects to `Person` objects.

    `EmailAddress` objects are looked up for `HWSubmission` objects
    that have not yet been linked to a `Person`.  If the
    `EmailAddress` is linked to a person, then the `HWSubmission` is
    linked to the same.
    """
    maximum_chunk_size = 50000
    def __init__(self, log, abort_time=None):
        super(HWSubmissionEmailLinker, self).__init__(log, abort_time)
        self.submission_store = IMasterStore(HWSubmission)
        self.submission_store.execute(
            "DROP TABLE IF EXISTS NewlyMatchedSubmission")
        # The join with the Person table is to avoid any replication
        # lag issues - EmailAddress.person might reference a Person
        # that does not yet exist.
        self.submission_store.execute("""
            CREATE TEMPORARY TABLE NewlyMatchedSubmission AS
            SELECT
                HWSubmission.id AS submission,
                EmailAddress.person AS owner
            FROM HWSubmission, EmailAddress, Person
            WHERE HWSubmission.owner IS NULL
                AND EmailAddress.person = Person.id
                AND EmailAddress.status IN %s
                AND lower(HWSubmission.raw_emailaddress)
                    = lower(EmailAddress.email)
            """ % sqlvalues(
                [EmailAddressStatus.VALIDATED, EmailAddressStatus.PREFERRED]),
            noresult=True)
        self.submission_store.execute("""
            CREATE INDEX newlymatchsubmission__submission__idx
            ON NewlyMatchedSubmission(submission)
            """, noresult=True)
        self.matched_submission_count = self.submission_store.execute("""
            SELECT COUNT(*) FROM NewlyMatchedSubmission
            """).get_one()[0]
        self.offset = 0

    def isDone(self):
        return self.offset >= self.matched_submission_count

    def __call__(self, chunk_size):
        self.submission_store.execute("""
            UPDATE HWSubmission
            SET owner=NewlyMatchedSubmission.owner
            FROM (
                SELECT submission, owner
                FROM NewlyMatchedSubmission
                ORDER BY submission
                OFFSET %d
                LIMIT %d
                ) AS NewlyMatchedSubmission
            WHERE HWSubmission.id = NewlyMatchedSubmission.submission
            """ % (self.offset, chunk_size), noresult=True)
        self.offset += chunk_size
        transaction.commit()


class MailingListSubscriptionPruner(TunableLoop):
    """Prune `MailingListSubscription`s pointing at deleted email addresses.

    Users subscribe to mailing lists with one of their verified email
    addresses.  When they remove an address, the mailing list
    subscription should go away too.
    """

    maximum_chunk_size = 1000

    def __init__(self, log, abort_time=None):
        super(MailingListSubscriptionPruner, self).__init__(log, abort_time)
        self.subscription_store = IMasterStore(MailingListSubscription)
        self.email_store = IMasterStore(EmailAddress)

        (self.min_subscription_id,
         self.max_subscription_id) = self.subscription_store.find(
            (Min(MailingListSubscription.id),
             Max(MailingListSubscription.id))).one()

        self.next_subscription_id = self.min_subscription_id

    def isDone(self):
        return (self.min_subscription_id is None or
                self.next_subscription_id > self.max_subscription_id)

    def __call__(self, chunk_size):
        result = self.subscription_store.find(
            MailingListSubscription,
            MailingListSubscription.id >= self.next_subscription_id,
            MailingListSubscription.id < (self.next_subscription_id +
                                          chunk_size))
        used_ids = set(result.values(MailingListSubscription.email_addressID))
        existing_ids = set(self.email_store.find(
                EmailAddress.id, EmailAddress.id.is_in(used_ids)))
        deleted_ids = used_ids - existing_ids

        self.subscription_store.find(
            MailingListSubscription,
            MailingListSubscription.id >= self.next_subscription_id,
            MailingListSubscription.id < (self.next_subscription_id +
                                          chunk_size),
            MailingListSubscription.email_addressID.is_in(deleted_ids)
            ).remove()

        self.next_subscription_id += chunk_size
        transaction.commit()


class PersonPruner(TunableLoop):

    maximum_chunk_size = 1000

    def __init__(self, log, abort_time=None):
        super(PersonPruner, self).__init__(log, abort_time)
        self.offset = 1
        self.store = IMasterStore(Person)
        self.log.debug("Creating LinkedPeople temporary table.")
        self.store.execute(
            "CREATE TEMPORARY TABLE LinkedPeople(person integer primary key)")
        # Prefill with Person entries created after our OpenID provider
        # started creating personless accounts on signup.
        self.log.debug(
            "Populating LinkedPeople with post-OpenID created Person.")
        self.store.execute("""
            INSERT INTO LinkedPeople
            SELECT id FROM Person
            WHERE datecreated > '2009-04-01'
            """)
        transaction.commit()
        for (from_table, from_column, to_table, to_column, uflag, dflag) in (
                postgresql.listReferences(cursor(), 'person', 'id')):
            # Skip things that don't link to Person.id or that link to it from
            # TeamParticipation or EmailAddress, as all Person entries will be
            # linked to from these tables.
            if (to_table != 'person' or to_column != 'id'
                or from_table in ('teamparticipation', 'emailaddress')):
                continue
            self.log.debug(
                "Populating LinkedPeople from %s.%s"
                % (from_table, from_column))
            self.store.execute("""
                INSERT INTO LinkedPeople
                SELECT DISTINCT %(from_column)s AS person
                FROM %(from_table)s
                WHERE %(from_column)s IS NOT NULL
                EXCEPT ALL
                SELECT person FROM LinkedPeople
                """ % dict(from_table=from_table, from_column=from_column))
            transaction.commit()

        self.log.debug("Creating UnlinkedPeople temporary table.")
        self.store.execute("""
            CREATE TEMPORARY TABLE UnlinkedPeople(
                id serial primary key, person integer);
            """)
        self.log.debug("Populating UnlinkedPeople.")
        self.store.execute("""
            INSERT INTO UnlinkedPeople (person) (
                SELECT id AS person FROM Person
                WHERE teamowner IS NULL
                EXCEPT ALL
                SELECT person FROM LinkedPeople);
            """)
        transaction.commit()
        self.log.debug("Indexing UnlinkedPeople.")
        self.store.execute("""
            CREATE UNIQUE INDEX unlinkedpeople__person__idx ON
                UnlinkedPeople(person);
            """)
        self.log.debug("Analyzing UnlinkedPeople.")
        self.store.execute("""
            ANALYZE UnlinkedPeople;
            """)
        self.log.debug("Counting UnlinkedPeople.")
        self.max_offset = self.store.execute(
            "SELECT MAX(id) FROM UnlinkedPeople").get_one()[0]
        if self.max_offset is None:
            self.max_offset = -1 # Trigger isDone() now.
            self.log.debug("No Person records to remove.")
        else:
            self.log.info("%d Person records to remove." % self.max_offset)
        # Don't keep any locks open - we might block.
        transaction.commit()

    def isDone(self):
        return self.offset > self.max_offset

    def __call__(self, chunk_size):
        subquery = """
            SELECT person FROM UnlinkedPeople
            WHERE id BETWEEN %d AND %d
            """ % (self.offset, self.offset + chunk_size - 1)
        people_ids = ",".join(
            str(item[0]) for item in self.store.execute(subquery).get_all())
        self.offset += chunk_size
        try:
            # This would be dangerous if we were deleting a
            # team, so join with Person to ensure it isn't one
            # even in the rare case a person is converted to
            # a team during this run.
            self.store.execute("""
                DELETE FROM TeamParticipation
                USING Person
                WHERE TeamParticipation.person = Person.id
                    AND Person.teamowner IS NULL
                    AND Person.id IN (%s)
                """ % people_ids)
            self.store.execute("""
                UPDATE EmailAddress SET person=NULL
                WHERE person IN (%s)
                """ % people_ids)
            self.store.execute("""
                DELETE FROM Person
                WHERE id IN (%s)
                """ % people_ids)
            transaction.commit()
            self.log.debug(
                "Deleted the following unlinked people: %s" % people_ids)
        except IntegrityError:
            # This case happens when a Person is linked to something
            # during the run. It is unlikely to occur, so just ignore
            # it again. Everything will clear up next run.
            transaction.abort()
            self.log.warning(
                "Failed to delete %d Person records. Left for next time."
                % chunk_size)


class BugNotificationPruner(TunableLoop):
    """Prune `BugNotificationRecipient` records no longer of interest.

    We discard all rows older than 30 days that have been sent. We
    keep 30 days worth or records to help diagnose email delivery issues.
    """
    maximum_chunk_size = 10000

    def _to_remove(self):
        return IMasterStore(BugNotification).find(
            BugNotification.id,
            BugNotification.date_emailed < THIRTY_DAYS_AGO)

    def isDone(self):
        return self._to_remove().any() is None

    def __call__(self, chunk_size):
        chunk_size = int(chunk_size)
        ids_to_remove = list(self._to_remove()[:chunk_size])
        num_removed = IMasterStore(BugNotification).find(
            BugNotification,
            In(BugNotification.id, ids_to_remove)).remove()
        transaction.commit()
        self.log.debug("Removed %d rows" % num_removed)


class BranchJobPruner(TunableLoop):
    """Prune `BranchJob`s that are in a final state and older than a month old.

    When a BranchJob is completed, it gets set to a final state.  These jobs
    should be pruned from the database after a month.
    """

    maximum_chunk_size = 1000

    def __init__(self, log, abort_time=None):
        super(BranchJobPruner, self).__init__(log, abort_time)
        self.job_store = IMasterStore(BranchJob)

    def isDone(self):
        return self._ids_to_remove().any() is None

    def _ids_to_remove(self):
        jobs = self.job_store.find(
            BranchJob.id,
            BranchJob.job == Job.id,
            Job.date_finished < THIRTY_DAYS_AGO)
        return jobs

    def __call__(self, chunk_size):
        chunk_size = int(chunk_size)
        ids_to_remove = list(self._ids_to_remove()[:chunk_size])
        num_removed = self.job_store.find(
            BranchJob,
            In(BranchJob.id, ids_to_remove)).remove()
        transaction.commit()


class BugHeatUpdater(TunableLoop):
    """A `TunableLoop` for bug heat calculations."""

    maximum_chunk_size = 1000

    def __init__(self, log, abort_time=None, max_heat_age=None):
        super(BugHeatUpdater, self).__init__(log, abort_time)
        self.transaction = transaction
        self.total_processed = 0
        self.is_done = False
        self.offset = 0
        if max_heat_age is None:
            max_heat_age = config.calculate_bug_heat.max_heat_age
        self.max_heat_age = max_heat_age

    def isDone(self):
        """See `ITunableLoop`."""
        # When the main loop has no more Bugs to process it sets
        # offset to None. Until then, it always has a numerical
        # value.
        return self.is_done

    def __call__(self, chunk_size):
        """Retrieve a batch of Bugs and update their heat.

        See `ITunableLoop`.
        """
        # XXX 2010-01-08 gmb bug=198767:
        #     We cast chunk_size to an integer to ensure that we're not
        #     trying to slice using floats or anything similarly
        #     foolish. We shouldn't have to do this.
        chunk_size = int(chunk_size)
        start = self.offset
        end = self.offset + chunk_size

        transaction.begin()
        bugs = getUtility(IBugSet).getBugsWithOutdatedHeat(
            self.max_heat_age)[start:end]

        bug_count = bugs.count()
        if bug_count > 0:
            starting_id = bugs.first().id
            self.log.debug(
                "Adding CalculateBugHeatJobs for %i Bugs (starting id: %i)" %
                (bug_count, starting_id))
        else:
            self.is_done = True

        self.offset = None
        for bug in bugs:
            # We set the starting point of the next batch to the Bug
            # id after the one we're looking at now. If there aren't any
            # bugs this loop will run for 0 iterations and starting_id
            # will remain set to None.
            start += 1
            self.offset = start
            self.log.debug("Adding CalculateBugHeatJob for bug %s" % bug.id)
            getUtility(ICalculateBugHeatJobSource).create(bug)
            self.total_processed += 1
        transaction.commit()


class BugWatchActivityPruner(TunableLoop):
    """A TunableLoop to prune BugWatchActivity entries."""

    maximum_chunk_size = 1000

    def getPrunableBugWatchIds(self, chunk_size):
        """Return the set of BugWatch IDs whose activity is prunable."""
        query = """
            SELECT
                watch_activity.id
            FROM (
                SELECT
                    BugWatch.id AS id,
                    COUNT(BugWatchActivity.id) as activity_count
                FROM BugWatch, BugWatchActivity
                WHERE BugWatchActivity.bug_watch = BugWatch.id
                GROUP BY BugWatch.id) AS watch_activity
            WHERE watch_activity.activity_count > %s
            LIMIT %s;
        """ % sqlvalues(MAX_SAMPLE_SIZE, chunk_size)
        store = IMasterStore(BugWatch)
        results = store.execute(query)
        return set(result[0] for result in results)

    def pruneBugWatchActivity(self, bug_watch_ids):
        """Prune the BugWatchActivity for bug_watch_ids."""
        query = """
            DELETE FROM BugWatchActivity
            WHERE id IN (
                SELECT id
                FROM BugWatchActivity
                WHERE bug_watch = %s
                ORDER BY id DESC
                OFFSET %s);
        """
        store = IMasterStore(BugWatch)
        for bug_watch_id in bug_watch_ids:
            results = store.execute(
                query % sqlvalues(bug_watch_id, MAX_SAMPLE_SIZE))
            self.log.debug(
                "Pruned %s BugWatchActivity entries for watch %s" %
                (results.rowcount, bug_watch_id))

    def __call__(self, chunk_size):
        transaction.begin()
        prunable_ids = self.getPrunableBugWatchIds(chunk_size)
        self.pruneBugWatchActivity(prunable_ids)
        transaction.commit()

    def isDone(self):
        """Return True if there are no watches left to prune."""
        return len(self.getPrunableBugWatchIds(1)) == 0


class ObsoleteBugAttachmentDeleter(TunableLoop):
    """Delete bug attachments without a LibraryFileContent record.

    Our database schema allows LibraryFileAlias records that have no
    corresponding LibraryFileContent records.

    This class deletes bug attachments that reference such "content free"
    and thus completely useless LFA records.
    """

    maximum_chunk_size = 1000

    def __init__(self, log, abort_time=None):
        super(ObsoleteBugAttachmentDeleter, self).__init__(log, abort_time)
        self.store = IMasterStore(BugAttachment)

    def _to_remove(self):
        return self.store.find(
            BugAttachment.id,
            BugAttachment.libraryfile == LibraryFileAlias.id,
            LibraryFileAlias.content == None)

    def isDone(self):
        return self._to_remove().any() is None

    def __call__(self, chunk_size):
        chunk_size = int(chunk_size)
        ids_to_remove = list(self._to_remove()[:chunk_size])
        self.store.find(
            BugAttachment, In(BugAttachment.id, ids_to_remove)).remove()
        transaction.commit()


class BaseDatabaseGarbageCollector(LaunchpadCronScript):
    """Abstract base class to run a collection of TunableLoops."""
    script_name = None # Script name for locking and database user. Override.
    tunable_loops = None # Collection of TunableLoops. Override.
    continue_on_failure = False # If True, an exception in a tunable loop
                                # does not cause the script to abort.

    # _maximum_chunk_size is used to override the defined
    # maximum_chunk_size to allow our tests to ensure multiple calls to
    # __call__ are required without creating huge amounts of test data.
    _maximum_chunk_size = None

    def __init__(self, test_args=None):
        super(BaseDatabaseGarbageCollector, self).__init__(
            self.script_name,
            dbuser=self.script_name.replace('-', '_'),
            test_args=test_args)

    def add_my_options(self):
        self.parser.add_option("-x", "--experimental", dest="experimental",
            default=False, action="store_true",
            help="Run experimental jobs. Normally this is just for staging.")
        self.parser.add_option("--abort-script",
            dest="abort_script", default=None, action="store", type="int",
            metavar="SECS", help="Abort script after SECS seconds.")
        self.parser.add_option("--abort-task",
            dest="abort_task", default=None, action="store", type="int",
            metavar="SECS", help="Abort a task if it runs over SECS seconds.")

    def main(self):
        start_time = time.time()
        failure_count = 0

        if self.options.experimental:
            tunable_loops = (
                self.tunable_loops + self.experimental_tunable_loops)
        else:
            tunable_loops = self.tunable_loops

        a_very_long_time = 31536000 # 1 year
        abort_task = self.options.abort_task or a_very_long_time
        abort_script = self.options.abort_script or a_very_long_time

        for tunable_loop in tunable_loops:
            self.logger.info("Running %s" % tunable_loop.__name__)

            if abort_script <= 0:
                self.logger.warn(
                    "Script aborted after %d seconds." % abort_script)
                break

            abort_time = min(
                abort_task, abort_script + start_time - time.time())

            tunable_loop = tunable_loop(
                abort_time=abort_time, log=self.logger)

            if self._maximum_chunk_size is not None:
                tunable_loop.maximum_chunk_size = self._maximum_chunk_size

            try:
                tunable_loop.run()
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                if not self.continue_on_failure:
                    raise
                self.logger.exception("Unhandled exception")
                failure_count += 1
                transaction.abort()
            transaction.abort()
        if failure_count:
            raise SilentLaunchpadScriptFailure(failure_count)


class HourlyDatabaseGarbageCollector(BaseDatabaseGarbageCollector):
    script_name = 'garbo-hourly'
    tunable_loops = [
        OAuthNoncePruner,
        OpenIDConsumerNoncePruner,
        OpenIDConsumerAssociationPruner,
        RevisionCachePruner,
        BugHeatUpdater,
        BugWatchScheduler,
        ]
    experimental_tunable_loops = []

    def add_my_options(self):
        super(HourlyDatabaseGarbageCollector, self).add_my_options()
        # By default, abort any tunable loop taking more than 15 minutes.
        self.parser.set_defaults(abort_task=900)
        # And abort the script if it takes more than 55 minutes.
        self.parser.set_defaults(abort_script=55*60)


class DailyDatabaseGarbageCollector(BaseDatabaseGarbageCollector):
    script_name = 'garbo-daily'
    tunable_loops = [
        CodeImportResultPruner,
        RevisionAuthorEmailLinker,
        HWSubmissionEmailLinker,
        MailingListSubscriptionPruner,
        BugNotificationPruner,
        BranchJobPruner,
        BugWatchActivityPruner,
        ObsoleteBugAttachmentDeleter,
        ]
    experimental_tunable_loops = [
        PersonPruner,
        ]

    def add_my_options(self):
        super(DailyDatabaseGarbageCollector, self).add_my_options()
        # Abort script after 24 hours by default.
        self.parser.set_defaults(abort_script=86400)

