# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Export translation snapshots to bzr branches where requested."""

__metaclass__ = type
__all__ = ['ExportTranslationsToBranch']


from datetime import (
    datetime,
    timedelta,
    )
import os.path

from bzrlib.errors import NotBranchError
import pytz
from storm.expr import (
    Join,
    SQL,
    )
from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.helpers import (
    get_contact_email_addresses,
    get_email_template,
    shortlist,
    )
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector,
    MAIN_STORE,
    SLAVE_FLAVOR,
    )
from lp.code.interfaces.branchjob import IRosettaUploadJobSource
from lp.code.model.directbranchcommit import (
    ConcurrentUpdateError,
    DirectBranchCommit,
    )
from lp.codehosting.vfs import get_rw_server
from lp.services.mail.sendmail import (
    format_address,
    simple_sendmail,
    )
from lp.services.scripts.base import LaunchpadCronScript
from lp.translations.interfaces.potemplate import IPOTemplateSet


class ExportTranslationsToBranch(LaunchpadCronScript):
    """Commit translations to translations_branches where requested."""

    commit_message = "Launchpad automatic translations update."

    # Don't bother looking for a previous translations commit if it's
    # longer than this ago.
    previous_commit_cutoff_age = timedelta(days=7)

    # We can find out when the last translations commit to a branch
    # completed, and we can find out when the last transaction changing
    # a POFile started.  This is exactly the wrong way around for
    # figuring out which POFiles need a fresh export, so assume a fudge
    # factor.
    fudge_factor = timedelta(hours=6)

    def add_my_options(self):
        """See `LaunchpadScript`."""
        self.parser.add_option(
            '-n', '--no-fudge', action='store_true', dest='no_fudge',
            default=False,
            help="For testing: no fudge period for POFile changes.")

    def _checkForObjections(self, source):
        """Check for reasons why we can't commit to this branch.

        Raises `ConcurrentUpdateError` if there is such a reason.

        :param source: the series being exported to its
            translations_branch.
        """
        if source.translations_branch is None:
            raise ConcurrentUpdateError(
                "Translations export for %s was just disabled." % (
                    source.title))

        branch = source.translations_branch
        jobsource = getUtility(IRosettaUploadJobSource)
        unfinished_jobs = jobsource.findUnfinishedJobs(
            branch, since=datetime.now(pytz.UTC) - timedelta(days=1))

        if unfinished_jobs.any():
            raise ConcurrentUpdateError(
                "Translations branch for %s has pending translations "
                "changes.  Not committing." % source.title)

    def _makeDirectBranchCommit(self, db_branch):
        """Create a `DirectBranchCommit`.

        :param db_branch: A `Branch` object as defined in Launchpad.
        :return: A `DirectBranchCommit` for `db_branch`.
        """
        committer_id = 'Launchpad Translations on behalf of %s' % (
            db_branch.owner.name)
        return DirectBranchCommit(db_branch, committer_id=committer_id)

    def _prepareBranchCommit(self, db_branch):
        """Prepare branch for use with `DirectBranchCommit`.

        Create a `DirectBranchCommit` for `db_branch`.  If `db_branch`
        is not in a format we can commit directly to, try to deal with
        that.

        :param db_branch: A `Branch`.
        :return: `DirectBranchCommit`.
        """
        # XXX JeroenVermeulen 2009-09-30 bug=375013: It should become
        # possible again to commit to these branches at some point.
        # When that happens, remove this workaround and just call
        # _makeDirectBranchCommit directly.
        if db_branch.stacked_on:
            bzrbranch = db_branch.getBzrBranch()
            self.logger.info("Unstacking branch to work around bug 375013.")
            bzrbranch.set_stacked_on_url(None)
            self.logger.info("Done unstacking branch.")

            # This may have taken a while, so commit for good
            # manners.
            if self.txn:
                self.txn.commit()

        return self._makeDirectBranchCommit(db_branch)

    def _commit(self, source, committer):
        """Commit changes to branch.  Check for race conditions."""
        self._checkForObjections(source)
        committer.commit(self.commit_message, txn=self.txn)

    def _isTranslationsCommit(self, revision):
        """Is `revision` an automatic translations commit?"""
        return revision.message == self.commit_message

    def _getRevisionTime(self, revision):
        """Get timestamp of `revision`."""
        # The bzr timestamp is a float representing UTC-based seconds
        # since the epoch.  It stores the timezone as well, but we can
        # ignore it here.
        return datetime.fromtimestamp(revision.timestamp, pytz.UTC)

    def _getLatestTranslationsCommit(self, branch):
        """Get date of last translations commit to `branch`, if any."""
        cutoff_date = datetime.now(pytz.UTC) - self.previous_commit_cutoff_age

        revno, current_rev = branch.last_revision_info()
        repository = branch.repository
        for rev_id in repository.iter_reverse_revision_history(current_rev):
            revision = repository.get_revision(rev_id)
            revision_date = self._getRevisionTime(revision)
            if self._isTranslationsCommit(revision):
                return revision_date

            if revision_date < cutoff_date:
                # Going too far back in history.  Give up.
                return None

        return None

    def _exportToBranch(self, source):
        """Export translations for source into source.translations_branch.

        :param source: a `ProductSeries`.
        """
        self.logger.info("Exporting %s." % source.title)
        self._checkForObjections(source)

        committer = self._prepareBranchCommit(source.translations_branch)
        self.logger.debug("Created DirectBranchCommit.")
        if self.txn:
            self.txn.commit()

        bzr_branch = committer.bzrbranch

        last_commit_date = self._getLatestTranslationsCommit(bzr_branch)

        if last_commit_date is None:
            self.logger.debug("No previous translations commit found.")
            changed_since = None
        else:
            # Export files that have been touched since the last export.
            # Subtract a fudge factor because the last-export date marks
            # the end of the previous export, and the POFiles'
            # last-touched timestamp marks the beginning of the last
            # transaction that changed them.
            self.logger.debug("Last commit was at %s." % last_commit_date)
            changed_since = last_commit_date - self.fudge_factor

        change_count = 0

        try:
            subset = getUtility(IPOTemplateSet).getSubset(
                productseries=source, iscurrent=True)
            for template in subset:
                base_path = os.path.dirname(template.path)

                for pofile in template.pofiles:
                    has_changed = (
                        changed_since is None or
                        pofile.date_changed > changed_since)
                    if not has_changed:
                        continue

                    language_code = pofile.getFullLanguageCode()
                    self.logger.debug("Exporting %s." % language_code)

                    pofile_path = os.path.join(
                        base_path, language_code + '.po')
                    pofile_contents = pofile.export()

                    committer.writeFile(pofile_path, pofile_contents)
                    change_count += 1

                    # We're not actually writing any changes to the
                    # database, but it's not polite to stay in one
                    # transaction for too long.
                    if self.txn:
                        self.txn.commit()

                    # We're done with this POFile.  Don't bother caching
                    # anything about it any longer.
                    template.clearPOFileCache()

            if change_count > 0:
                self.logger.debug("Writing to branch.")
                self._commit(source, committer)
        finally:
            committer.unlock()

    def _exportToBranches(self, productseries_iter):
        """Loop over `productseries_iter` and export their translations."""
        items_done = 0
        items_failed = 0
        unpushed_branches = 0

        productseries = shortlist(productseries_iter, longest_expected=2000)

        for source in productseries:
            try:
                self._exportToBranch(source)

                if self.txn:
                    self.txn.commit()
            except (KeyboardInterrupt, SystemExit):
                raise
            except NotBranchError:
                unpushed_branches += 1
                if self.txn:
                    self.txn.abort()
                self._handleUnpushedBranch(source)
                if self.txn:
                    self.txn.commit()
            except Exception, e:
                items_failed += 1
                self.logger.error("Failure: %s" % repr(e))
                if self.txn:
                    self.txn.abort()

            items_done += 1

        self.logger.info(
            "Processed %d item(s); %d failure(s), %d unpushed branch(es)." % (
                items_done, items_failed, unpushed_branches))

    def _sendMail(self, sender, recipients, subject, text):
        """Wrapper for `simple_sendmail`.  Fakeable for easy testing."""
        simple_sendmail(sender, recipients, subject, text)

    def _handleUnpushedBranch(self, productseries):
        """Branch has never been scanned.  Notify owner.

        This means that as far as the Launchpad database knows, there is
        no actual bzr branch behind this `IBranch` yet.
        """
        branch = productseries.translations_branch
        self.logger.info("Notifying %s of unpushed branch %s." % (
            branch.owner.name, branch.bzr_identity))

        template = get_email_template('unpushed-branch.txt', 'translations')
        text = template % {
            'productseries': productseries.title,
            'branch_url': branch.bzr_identity,
        }
        recipients = get_contact_email_addresses(branch.owner)
        sender = format_address(
            "Launchpad Translations", config.canonical.noreply_from_address)
        subject = "Launchpad: translations branch has not been set up."
        self._sendMail(sender, recipients, subject, text)

    def main(self):
        """See `LaunchpadScript`."""
        # Avoid circular imports.
        from lp.registry.model.product import Product
        from lp.registry.model.productseries import ProductSeries

        if self.options.no_fudge:
            self.fudge_factor = timedelta(0)

        self.logger.info("Exporting to translations branches.")

        self.store = getUtility(IStoreSelector).get(MAIN_STORE, SLAVE_FLAVOR)

        product_join = Join(
            ProductSeries, Product, ProductSeries.product == Product.id)
        productseries = self.store.using(product_join).find(
            ProductSeries, SQL(
                "translations_usage = %s AND translations_branch IS NOT NULL"
                % ServiceUsage.LAUNCHPAD))

        # Anything deterministic will do, and even that is only for
        # testing.
        productseries = productseries.order_by(ProductSeries.id)

        bzrserver = get_rw_server()
        bzrserver.start_server()
        try:
            self._exportToBranches(productseries)
        finally:
            bzrserver.stop_server()
