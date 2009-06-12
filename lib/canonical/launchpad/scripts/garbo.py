# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Database garbage collection."""

__metaclass__ = type
__all__ = ['DailyDatabaseGarbageCollector', 'HourlyDatabaseGarbageCollector']

from datetime import datetime, timedelta
import time

import pytz
import transaction
from zope.component import getUtility
from zope.interface import implements
from storm.locals import SQL, Max, Min

from canonical.database.sqlbase import sqlvalues
from canonical.launchpad.database.emailaddress import EmailAddress
from canonical.launchpad.database.hwdb import HWSubmission
from canonical.launchpad.database.oauth import OAuthNonce
from canonical.launchpad.database.openidconsumer import OpenIDConsumerNonce
from canonical.launchpad.interfaces import IMasterStore, IRevisionSet
from canonical.launchpad.interfaces.emailaddress import EmailAddressStatus
from canonical.launchpad.interfaces.looptuner import ITunableLoop
from lp.services.scripts.base import LaunchpadCronScript
from canonical.launchpad.utilities.looptuner import DBLoopTuner
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, AUTH_STORE, MAIN_STORE, MASTER_FLAVOR)
from lp.code.model.codeimportresult import CodeImportResult
from lp.code.model.revision import RevisionAuthor, RevisionCache
from lp.registry.model.mailinglist import MailingListSubscription


ONE_DAY_IN_SECONDS = 24*60*60


class TunableLoop:
    implements(ITunableLoop)

    goal_seconds = 4
    minimum_chunk_size = 1
    maximum_chunk_size = None # Override
    cooldown_time = 0

    def __init__(self, log):
        self.log = log

    def run(self):
        assert self.maximum_chunk_size is not None, "Did not override."
        DBLoopTuner(
            self, self.goal_seconds,
            minimum_chunk_size = self.minimum_chunk_size,
            maximum_chunk_size = self.maximum_chunk_size,
            cooldown_time = self.cooldown_time).run()


class OAuthNoncePruner(TunableLoop):
    """An ITunableLoop to prune old OAuthNonce records.

    We remove all OAuthNonce records older than 1 day.
    """
    maximum_chunk_size = 6*60*60 # 6 hours in seconds.

    def __init__(self, log):
        super(OAuthNoncePruner, self).__init__(log)
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

    def __init__(self, log):
        super(OpenIDConsumerNoncePruner, self).__init__(log)
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


class OpenIDAssociationPruner(TunableLoop):
    minimum_chunk_size = 3500
    maximum_chunk_size = 50000

    table_name = 'OpenIDAssociation'
    store_name = AUTH_STORE

    _num_removed = None

    def __init__(self, log):
        super(OpenIDAssociationPruner, self).__init__(log)
        self.store = getUtility(IStoreSelector).get(
            self.store_name, MASTER_FLAVOR)

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


class OpenIDConsumerAssociationPruner(OpenIDAssociationPruner):
    table_name = 'OpenIDConsumerAssociation'
    store_name = MAIN_STORE


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
    and they are not one of the 4 most recent results for that
    CodeImport.
    """
    maximum_chunk_size = 1000
    def __init__(self, log):
        super(CodeImportResultPruner, self).__init__(log)
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
                    LIMIT 4)
            """ % sqlvalues(
                self.next_code_import_id,
                self.next_code_import_id,
                chunk_size))
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

    def __init__(self, log):
        super(RevisionAuthorEmailLinker, self).__init__(log)
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

    TODO: Instead of iterating over all submissions, we should extract
    the unmatched but matchable submissions into a temporary table and
    iterate over that:
        CREATE TEMPORARY TABLE NewlyMatchedSubmissions AS
        SELECT HWSubmission.id FROM HWSubmission, EmailAddress
        WHERE lower(HWSubmission.raw_emailaddress) = lower(EmailAddress.email)
            AND HWSubmission.owner IS NULL;
    """

    maximum_chunk_size = 1000

    def __init__(self, log):
        super(HWSubmissionEmailLinker, self).__init__(log)
        self.submission_store = IMasterStore(HWSubmission)
        self.email_store = IMasterStore(EmailAddress)

        (self.min_submission_id,
         self.max_submission_id) = self.submission_store.find(
            (Min(HWSubmission.id), Max(HWSubmission.id))).one()

        self.next_submission_id = self.min_submission_id

    def isDone(self):
        return (self.min_submission_id is None or
                self.next_submission_id > self.max_submission_id)

    def __call__(self, chunk_size):
        result = self.submission_store.find(
            HWSubmission,
            HWSubmission.id >= self.next_submission_id,
            HWSubmission.ownerID == None,
            HWSubmission.raw_emailaddress != None)
        result.order_by(HWSubmission.id)
        submissions = list(result[:chunk_size])

        # No more submissions found.
        if len(submissions) == 0:
            self.next_submission_id = self.max_submission_id + 1
            transaction.commit()
            return

        emails = dict(self.email_store.find(
            (EmailAddress.email.lower(), EmailAddress.personID),
            EmailAddress.email.lower().is_in(
                    [submission.raw_emailaddress.lower()
                     for submission in submissions]),
            EmailAddress.status.is_in([EmailAddressStatus.PREFERRED,
                                       EmailAddressStatus.VALIDATED]),
            EmailAddress.personID != None))

        if emails:
            for submission in submissions:
                personID = emails.get(submission.raw_emailaddress.lower())
                if personID is None:
                    continue
                submission.ownerID = personID

        self.next_submission_id = submissions[-1].id + 1
        transaction.commit()


class MailingListSubscriptionPruner(TunableLoop):
    """Prune `MailingListSubscription`s pointing at deleted email addresses.

    Users subscribe to mailing lists with one of their verified email
    addresses.  When they remove an address, the mailing list
    subscription should go away too.
    """

    maximum_chunk_size = 1000

    def __init__(self, log):
        super(MailingListSubscriptionPruner, self).__init__(log)
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


class BaseDatabaseGarbageCollector(LaunchpadCronScript):
    """Abstract base class to run a collection of TunableLoops."""
    script_name = None # Script name for locking and database user. Override.
    tunable_loops = None # Collection of TunableLoops. Override.

    # _maximum_chunk_size is used to override the defined
    # maximum_chunk_size to allow our tests to ensure multiple calls to
    # __call__ are required without creating huge amounts of test data.
    _maximum_chunk_size = None

    def __init__(self, test_args=None):
        super(BaseDatabaseGarbageCollector, self).__init__(
            self.script_name,
            dbuser=self.script_name.replace('-','_'),
            test_args=test_args)

    def main(self):
        for tunable_loop in self.tunable_loops:
            self.logger.info("Running %s" % tunable_loop.__name__)
            tunable_loop = tunable_loop(log=self.logger)
            if self._maximum_chunk_size is not None:
                tunable_loop.maximum_chunk_size = self._maximum_chunk_size
            tunable_loop.run()


class HourlyDatabaseGarbageCollector(BaseDatabaseGarbageCollector):
    script_name = 'garbo-hourly'
    tunable_loops = [
        OAuthNoncePruner,
        OpenIDConsumerNoncePruner,
        OpenIDAssociationPruner,
        OpenIDConsumerAssociationPruner,
        RevisionCachePruner,
        ]


class DailyDatabaseGarbageCollector(BaseDatabaseGarbageCollector):
    script_name = 'garbo-daily'
    tunable_loops = [
        CodeImportResultPruner,
        RevisionAuthorEmailLinker,
        HWSubmissionEmailLinker,
        MailingListSubscriptionPruner,
        ]

