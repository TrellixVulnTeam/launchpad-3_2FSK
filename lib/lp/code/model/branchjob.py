# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    'BranchJob',
    'RevisionsAddedJob',
    'RevisionMailJob',
    'RosettaUploadJob',
]

import os
import shutil
from StringIO import StringIO

from bzrlib.bzrdir import BzrDirMetaFormat1
from bzrlib.log import log_formatter, show_log
from bzrlib.diff import show_diff_trees
from bzrlib.revision import NULL_REVISION
from bzrlib.revisionspec import RevisionInfo, RevisionSpec
from bzrlib.upgrade import upgrade

from lazr.enum import DBEnumeratedType, DBItem
from lazr.delegates import delegates

import simplejson

from sqlobject import ForeignKey, StringCol
from storm.expr import And, SQL
from storm.locals import Store

import transaction

from zope.component import getUtility
from zope.interface import classProvides, implements

from canonical.config import config
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase
from canonical.launchpad.webapp import canonical_url
from lp.code.bzr import (
    BRANCH_FORMAT_UPGRADE_PATH, REPOSITORY_FORMAT_UPGRADE_PATH)
from lp.code.model.branch import Branch
from lp.code.model.branchmergeproposal import BranchMergeProposal
from lp.code.model.diff import StaticDiff
from lp.code.model.revision import RevisionSet
from lp.codehosting.vfs import branch_id_to_path
from lp.services.job.model.job import Job
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import BaseRunnableJob
from lp.registry.model.productseries import ProductSeries
from lp.translations.model.translationbranchapprover import (
    TranslationBranchApprover)
from lp.code.enums import (
    BranchSubscriptionDiffSize, BranchSubscriptionNotificationLevel)
from lp.code.interfaces.branchjob import (
    IBranchDiffJob, IBranchDiffJobSource, IBranchJob, IBranchUpgradeJob,
    IBranchUpgradeJobSource, IReclaimBranchSpaceJob,
    IReclaimBranchSpaceJobSource, IRevisionsAddedJob, IRevisionMailJob,
    IRevisionMailJobSource, IRosettaUploadJob, IRosettaUploadJobSource)
from lp.translations.interfaces.translations import (
    TranslationsBranchImportMode)
from lp.translations.interfaces.translationimportqueue import (
    ITranslationImportQueue)
from lp.code.mail.branch import BranchMailer
from lp.translations.utilities.translation_import import (
    TranslationImporter)
from canonical.launchpad.webapp.interfaces import (
        IStoreSelector, MAIN_STORE, MASTER_FLAVOR)


# Use at most the first 100 characters of the commit message for the subject
# the mail describing the revision.
SUBJECT_COMMIT_MESSAGE_LENGTH = 100


class BranchJobType(DBEnumeratedType):
    """Values that ICodeImportJob.state can take."""

    STATIC_DIFF = DBItem(0, """
        Static Diff

        This job runs against a branch to produce a diff that cannot change.
        """)

    REVISION_MAIL = DBItem(1, """
        Revision Mail

        This job runs against a branch to send emails about revisions.
        """)

    REVISIONS_ADDED_MAIL = DBItem(2, """
        Revisions Added Mail

        This job runs against a branch to send emails about added revisions.
        """)

    ROSETTA_UPLOAD = DBItem(3, """
        Rosetta Upload

        This job runs against a branch to upload translation files to rosetta.
        """)

    UPGRADE_BRANCH = DBItem(4, """
        Upgrade Branch

        This job upgrades the branch in the hosted area.
        """)

    RECLAIM_BRANCH_SPACE = DBItem(5, """
        Reclaim Branch Space

        This job removes a branch that have been deleted from the database
        from disk.
        """)


class BranchJob(SQLBase):
    """Base class for jobs related to branches."""

    implements(IBranchJob)

    _table = 'BranchJob'

    job = ForeignKey(foreignKey='Job', notNull=True)

    branch = ForeignKey(foreignKey='Branch')

    job_type = EnumCol(enum=BranchJobType, notNull=True)

    _json_data = StringCol(dbName='json_data')

    @property
    def metadata(self):
        return simplejson.loads(self._json_data)

    def __init__(self, branch, job_type, metadata, **job_args):
        """Constructor.

        Extra keyword parameters are used to construct the underlying Job
        object.

        :param branch: The database branch this job relates to.
        :param job_type: The BranchJobType of this job.
        :param metadata: The type-specific variables, as a JSON-compatible
            dict.
        """
        json_data = simplejson.dumps(metadata)
        SQLBase.__init__(
            self, job=Job(**job_args), branch=branch, job_type=job_type,
            _json_data=json_data)

    def destroySelf(self):
        """See `IBranchJob`."""
        SQLBase.destroySelf(self)
        self.job.destroySelf()


class BranchJobDerived(BaseRunnableJob):

    delegates(IBranchJob)

    def __init__(self, branch_job):
        self.context = branch_job

    # XXX: henninge 2009-02-20 bug=331919: These two standard operators
    # should be implemented by delegates().
    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.context == other.context)

    def __ne__(self, other):
        return not (self == other)

    @classmethod
    def iterReady(cls):
        """See `IRevisionMailJobSource`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, MASTER_FLAVOR)
        jobs = store.find(
            (BranchJob),
            And(BranchJob.job_type == cls.class_job_type,
                BranchJob.job == Job.id,
                Job.id.is_in(Job.ready_jobs)))
        return (cls(job) for job in jobs)


class BranchDiffJob(BranchJobDerived):
    """A Job that calculates the a diff related to a Branch."""

    implements(IBranchDiffJob)

    classProvides(IBranchDiffJobSource)
    @classmethod
    def create(cls, branch, from_revision_spec, to_revision_spec):
        """See `IBranchDiffJobSource`."""
        metadata = cls.getMetadata(from_revision_spec, to_revision_spec)
        branch_job = BranchJob(branch, BranchJobType.STATIC_DIFF, metadata)
        return cls(branch_job)

    @staticmethod
    def getMetadata(from_revision_spec, to_revision_spec):
        return {
            'from_revision_spec': from_revision_spec,
            'to_revision_spec': to_revision_spec,
        }

    @property
    def from_revision_spec(self):
        return self.metadata['from_revision_spec']

    @property
    def to_revision_spec(self):
        return self.metadata['to_revision_spec']

    def _get_revision_id(self, bzr_branch, spec_string):
        spec = RevisionSpec.from_string(spec_string)
        return spec.as_revision_id(bzr_branch)

    def run(self):
        """See IBranchDiffJob."""
        bzr_branch = self.branch.getBzrBranch()
        from_revision_id = self._get_revision_id(
            bzr_branch, self.from_revision_spec)
        to_revision_id = self._get_revision_id(
            bzr_branch, self.to_revision_spec)
        static_diff = StaticDiff.acquire(
            from_revision_id, to_revision_id, bzr_branch.repository)
        return static_diff


class BranchUpgradeJob(BranchJobDerived):
    """A Job that upgrades branches to the current stable format."""

    implements(IBranchUpgradeJob)

    classProvides(IBranchUpgradeJobSource)
    @classmethod
    def create(cls, branch):
        """See `IBranchUpgradeJobSource`."""
        branch_job = BranchJob(branch, BranchJobType.UPGRADE_BRANCH, {})
        return cls(branch_job)

    def run(self):
        """See `IBranchUpgradeJob`."""
        branch = self.branch.getBzrBranch()
        to_format = self.upgrade_format
        upgrade(branch.base, to_format)

    @property
    def upgrade_format(self):
        """See `IBranch`."""
        format = BzrDirMetaFormat1()
        branch_format = BRANCH_FORMAT_UPGRADE_PATH.get(
            self.branch.branch_format)
        repository_format = REPOSITORY_FORMAT_UPGRADE_PATH.get(
            self.branch.repository_format)
        if branch_format is None or repository_format is None:
            branch = self.branch.getBzrBranch()
            if branch_format is None:
                branch_format = type(branch._format)
            if repository_format is None:
                repository_format = type(branch.repository._format)
        format.set_branch_format(branch_format())
        format._set_repository_format(repository_format())
        return format


class RevisionMailJob(BranchDiffJob):
    """A Job that calculates the a diff related to a Branch."""

    implements(IRevisionMailJob)

    classProvides(IRevisionMailJobSource)

    class_job_type = BranchJobType.REVISION_MAIL

    @classmethod
    def create(
        cls, branch, revno, from_address, body, perform_diff, subject):
        """See `IRevisionMailJobSource`."""
        metadata = {
            'revno': revno,
            'from_address': from_address,
            'body': body,
            'perform_diff': perform_diff,
            'subject': subject,
        }
        if isinstance(revno, int) and revno > 0:
            from_revision_spec = str(revno - 1)
            to_revision_spec = str(revno)
        else:
            from_revision_spec = None
            to_revision_spec = None
        metadata.update(BranchDiffJob.getMetadata(from_revision_spec,
                        to_revision_spec))
        branch_job = BranchJob(branch, BranchJobType.REVISION_MAIL, metadata)
        return cls(branch_job)

    @property
    def revno(self):
        revno = self.metadata['revno']
        if isinstance(revno, int):
            revno = long(revno)
        return revno

    @property
    def from_address(self):
        return str(self.metadata['from_address'])

    @property
    def perform_diff(self):
        return self.metadata['perform_diff']

    @property
    def body(self):
        return self.metadata['body']

    @property
    def subject(self):
        return self.metadata['subject']

    def getMailer(self):
        """Return a BranchMailer for this job."""
        if self.perform_diff and self.to_revision_spec is not None:
            diff = BranchDiffJob.run(self)
            transaction.commit()
            diff_text = diff.diff.text
        else:
            diff_text = None
        return BranchMailer.forRevision(
            self.branch, self.revno, self.from_address, self.body,
            diff_text, self.subject)

    def run(self):
        """See `IRevisionMailJob`."""
        self.getMailer().sendAll()


class RevisionsAddedJob(BranchJobDerived):
    """A job for sending emails about added revisions."""
    implements(IRevisionsAddedJob)

    class_job_type = BranchJobType.REVISIONS_ADDED_MAIL

    @classmethod
    def create(cls, branch, last_scanned_id, last_revision_id,
               from_address):
        metadata = {'last_scanned_id': last_scanned_id,
                    'last_revision_id': last_revision_id,
                    'from_address': from_address}
        branch_job = BranchJob(branch, cls.class_job_type, metadata)
        return RevisionsAddedJob(branch_job)

    def __init__(self, context):
        super(RevisionsAddedJob, self).__init__(context)
        self._bzr_branch = None
        self._tree_cache = {}

    @property
    def bzr_branch(self):
        if self._bzr_branch is None:
            self._bzr_branch = self.branch.getBzrBranch()
        return self._bzr_branch

    @property
    def last_scanned_id(self):
        return self.metadata['last_scanned_id']

    @property
    def last_revision_id(self):
        return self.metadata['last_revision_id']

    @property
    def from_address(self):
        return self.metadata['from_address']

    def iterAddedMainline(self):
        """Iterate through revisions added to the mainline."""
        repository = self.bzr_branch.repository
        added_revisions = repository.get_graph().find_unique_ancestors(
            self.last_revision_id, [self.last_scanned_id])
        # Avoid hitting the database since bzrlib makes it easy to check.
        # There are possibly more efficient ways to get the mainline
        # revisions, but this is simple and it works.
        history = self.bzr_branch.revision_history()
        for num, revid in enumerate(history):
            if revid in added_revisions:
                yield repository.get_revision(revid), num+1

    def generateDiffs(self):
        """Determine whether to generate diffs."""
        for subscription in self.branch.subscriptions:
            if (subscription.max_diff_lines !=
                BranchSubscriptionDiffSize.NODIFF):
                return True
        else:
            return False

    def run(self):
        """Send all the emails about all the added revisions."""
        diff_levels = (BranchSubscriptionNotificationLevel.DIFFSONLY,
                       BranchSubscriptionNotificationLevel.FULL)
        subscriptions = self.branch.getSubscriptionsByLevel(diff_levels)
        if not subscriptions:
            return

        self.bzr_branch.lock_read()
        try:
            for revision, revno in self.iterAddedMainline():
                assert revno is not None
                mailer = self.getMailerForRevision(
                    revision, revno, self.generateDiffs())
                mailer.sendAll()
        finally:
            self.bzr_branch.unlock()

    def getDiffForRevisions(self, from_revision_id, to_revision_id):
        """Generate the diff between from_revision_id and to_revision_id."""
        # Try to reuse a tree from the last time through.
        repository = self.bzr_branch.repository
        from_tree = self._tree_cache.get(from_revision_id)
        if from_tree is None:
            from_tree = repository.revision_tree(from_revision_id)
        to_tree = self._tree_cache.get(to_revision_id)
        if to_tree is None:
            to_tree = repository.revision_tree(to_revision_id)
        # Replace the tree cache with these two trees.
        self._tree_cache = {
            from_revision_id: from_tree, to_revision_id: to_tree}
        # Now generate the diff.
        diff_content = StringIO()
        show_diff_trees(
            from_tree, to_tree, diff_content, old_label='', new_label='')
        return diff_content.getvalue()

    def getMailerForRevision(self, revision, revno, generate_diff):
        """Return a BranchMailer for a revision.

        :param revision: A bzr revision.
        :param revno: The revno of the revision in this branch.
        :param generate_diffs: If true, generate a diff for the revision.
        """
        message = self.getRevisionMessage(revision.revision_id, revno)
        # Use the first (non blank) line of the commit message
        # as part of the subject, limiting it to 100 characters
        # if it is longer.
        message_lines = [
            line.strip() for line in revision.message.split('\n')
            if len(line.strip()) > 0]
        if len(message_lines) == 0:
            first_line = 'no commit message given'
        else:
            first_line = message_lines[0]
            if len(first_line) > SUBJECT_COMMIT_MESSAGE_LENGTH:
                offset = SUBJECT_COMMIT_MESSAGE_LENGTH - 3
                first_line = first_line[:offset] + '...'
        subject = '[Branch %s] Rev %s: %s' % (
            self.branch.unique_name, revno, first_line)
        if generate_diff:
            if len(revision.parent_ids) > 0:
                parent_id = revision.parent_ids[0]
            else:
                parent_id = NULL_REVISION

            diff_text = self.getDiffForRevisions(
                parent_id, revision.revision_id)
        else:
            diff_text = None
        return BranchMailer.forRevision(
            self.branch, revno, self.from_address, message, diff_text,
            subject)

    def getMergedRevisionIDs(self, revision_id, graph):
        """Determine which revisions were merged by this revision.

        :param revision_id: ID of the revision to examine.
        :param graph: a bzrlib.graph.Graph.
        :return: a set of revision IDs.
        """
        parents = graph.get_parent_map([revision_id])[revision_id]
        merged_revision_ids = set()
        for merge_parent in parents[1:]:
            merged = graph.find_difference(parents[0], merge_parent)[1]
            merged_revision_ids.update(merged)
        return merged_revision_ids

    def getAuthors(self, revision_ids, graph):
        """Determine authors of the revisions merged by this revision.

        Ghost revisions are skipped.
        :param revision_ids: The revision to examine.
        :return: a set of author commit-ids
        """
        present_ids = graph.get_parent_map(revision_ids).keys()
        present_revisions = self.bzr_branch.repository.get_revisions(
            present_ids)
        authors = set()
        for revision in present_revisions:
            authors.update(revision.get_apparent_authors())
        return authors

    def findRelatedBMP(self, revision_ids):
        """Find merge proposals related to the revision-ids and branch.

        Only proposals whose source branch last-scanned-id is in the set of
        revision-ids and whose target_branch is the BranchJob branch are
        returned.
        """
        store = Store.of(self.branch)
        result = store.find(BranchMergeProposal,
                            BranchMergeProposal.target_branch==self.branch.id,
                            BranchMergeProposal.source_branch==Branch.id,
                            Branch.last_scanned_id.is_in(revision_ids))
        return result

    def getRevisionMessage(self, revision_id, revno):
        """Return the log message for a revision.

        :param revision_id: The revision-id of the revision.
        :param revno: The revno of the revision in the branch.
        :return: The log message entered for this revision.
        """
        self.bzr_branch.lock_read()
        try:
            graph = self.bzr_branch.repository.get_graph()
            merged_revisions = self.getMergedRevisionIDs(revision_id, graph)
            authors = self.getAuthors(merged_revisions, graph)
            revision_set = RevisionSet()
            rev_authors = set(revision_set.acquireRevisionAuthor(author) for
                              author in authors)
            outf = StringIO()
            pretty_authors = []
            for rev_author in rev_authors:
                if rev_author.person is None:
                    displayname = rev_author.name
                else:
                    displayname = rev_author.person.unique_displayname
                pretty_authors.append('  %s' % displayname)

            if len(pretty_authors) > 0:
                outf.write('Merge authors:\n')
                pretty_authors.sort(key=lambda x: x.lower())
                outf.write('\n'.join(pretty_authors[:5]))
                if len(pretty_authors) > 5:
                    outf.write('...\n')
                outf.write('\n')
            bmps = list(self.findRelatedBMP(merged_revisions))
            if len(bmps) > 0:
                outf.write('Related merge proposals:\n')
            for bmp in bmps:
                outf.write('  %s\n' % canonical_url(bmp))
                proposer = bmp.registrant
                outf.write('  proposed by: %s\n' %
                           proposer.unique_displayname)
                for review in bmp.votes:
                    outf.write('  review: %s - %s\n' %
                        (review.comment.vote.title,
                         review.reviewer.unique_displayname))
            info = RevisionInfo(self.bzr_branch, revno, revision_id)
            lf = log_formatter('long', to_file=outf)
            show_log(self.bzr_branch,
                     lf,
                     start_revision=info,
                     end_revision=info,
                     verbose=True)
        finally:
            self.bzr_branch.unlock()
        return outf.getvalue()


class RosettaUploadJob(BranchJobDerived):
    """A Job that uploads translation files to Rosetta."""

    implements(IRosettaUploadJob)

    classProvides(IRosettaUploadJobSource)

    class_job_type = BranchJobType.ROSETTA_UPLOAD

    def __init__(self, branch_job):
        super(RosettaUploadJob, self).__init__(branch_job)

        self.template_file_names = []
        self.template_files_changed = []
        self.translation_file_names = []
        self.translation_files_changed = []

    @staticmethod
    def getMetadata(from_revision_id, force_translations_upload):
        return {
            'from_revision_id': from_revision_id,
            'force_translations_upload': force_translations_upload,
        }

    @property
    def from_revision_id(self):
        return self.metadata['from_revision_id']

    @property
    def force_translations_upload(self):
        return self.metadata['force_translations_upload']

    @classmethod
    def _get_any_product_series(cls, branch, force_translations_upload):
        """Find an affected product series.

        This is used to check if any product series is related to the branch
        in order to decide if a job needs to be created.

        :param branch: The IBranch that is being scanned.
        :param force_translations_upload: Flag to override the settings in the
            product series and upload all translation files.
        :returns: a list of IProductSeries objects.
        """
        return cls._find_product_series(branch,
                                        force_translations_upload).any()

    @staticmethod
    def _find_product_series(branch, force_translations_upload):
        """Find affected product series.

        :param branch: The IBranch that is being scanned.
        :param force_translations_upload: Flag to override the settings in the
            product series and upload all translation files.
        :returns: a list of IProductSeries objects.
        """
        store = getUtility(IStoreSelector).get(MAIN_STORE, MASTER_FLAVOR)
        if force_translations_upload:
            productseries = store.find(
                (ProductSeries),
                ProductSeries.branch == branch)
        else:
            productseries = store.find(
                (ProductSeries),
                ProductSeries.branch == branch,
                ProductSeries.translations_autoimport_mode !=
                   TranslationsBranchImportMode.NO_IMPORT)
        return productseries

    @classmethod
    def create(cls, branch, from_revision_id,
               force_translations_upload=False):
        """See `IRosettaUploadJobSource`."""
        if branch is None:
            return None
        if from_revision_id is None:
            from_revision_id = NULL_REVISION
        productseries = cls._get_any_product_series(branch,
                                                    force_translations_upload)
        if productseries is not None:
            metadata = cls.getMetadata(from_revision_id,
                                       force_translations_upload)
            branch_job = BranchJob(
                branch, BranchJobType.ROSETTA_UPLOAD, metadata)
            return cls(branch_job)
        else:
            return None

    def _iter_all_lists(self):
        """Iterate through all the file lists.

        File names and files are stored in different lists according to their
        type (template or translation). But some operations need to be
        performed on both lists. This generator yields a pair of lists, one
        containing all file names for the given type, the other containing
        all file names *and* content of the changed files.
        """
        yield (self.template_file_names, self.template_files_changed)
        yield (self.translation_file_names, self.translation_files_changed)

    def _iter_lists_and_uploaders(self, productseries):
        """Iterate through all files for a productseries.

        File names and files are stored in different lists according to their
        type (template or translation). Which of these are needed depends on
        the configuration of the product series these uploads are for. This
        generator checks the configuration of the series and produces the
        a lists of lists and a person object. The first list contains all
        file names or the given type, the second contains all file names
        *and* content of the changed files. The person is who is to be
        credited as the importer of these files and will vary depending on
        the file type.
        """
        if (productseries.translations_autoimport_mode in (
            TranslationsBranchImportMode.IMPORT_TEMPLATES,
            TranslationsBranchImportMode.IMPORT_TRANSLATIONS) or
            self.force_translations_upload):
            #
            yield (self.template_file_names,
                   self.template_files_changed,
                   self._uploader_person_pot(productseries))

        if (productseries.translations_autoimport_mode ==
            TranslationsBranchImportMode.IMPORT_TRANSLATIONS or
            self.force_translations_upload):
            #
            yield (self.translation_file_names,
                   self.translation_files_changed,
                   self._uploader_person_po(productseries))

    @property
    def file_names(self):
        """A contatenation of all lists of filenames."""
        return self.template_file_names + self.translation_file_names

    def _init_translation_file_lists(self):
        """Initialize the member variables that hold the information about
        the relevant files.

        The information is collected from the branch tree and stored in the
        following member variables:
        * file_names is a dictionary of two lists ('pot', 'po') of file names
          that are POT or PO files respectively. This includes all files,
          changed or unchanged.
        * changed_files is a dictionary of two lists ('pot', 'po') of tuples
          of (file_name, file_content) of all changed files that are POT or
          PO files respectively.
        """

        bzrbranch = self.branch.getBzrBranch()
        from_tree = bzrbranch.repository.revision_tree(
            self.from_revision_id)
        to_tree = bzrbranch.repository.revision_tree(
            self.branch.last_scanned_id)

        importer = TranslationImporter()

        to_tree.lock_read()
        try:
            for dir, files in to_tree.walkdirs():
                for afile in files:
                    file_path, file_name, file_type = afile[:3]
                    if file_type != 'file':
                        continue
                    if importer.isTemplateName(file_name):
                        append_to = self.template_file_names
                    elif importer.isTranslationName(file_name):
                        append_to = self.translation_file_names
                    else:
                        continue
                    append_to.append(file_path)
            from_tree.lock_read()
            try:
                for file_names, changed_files in self._iter_all_lists():
                    for changed_file in to_tree.iter_changes(
                            from_tree, specific_files=file_names):
                        file_id, (from_path, to_path) = changed_file[:2]
                        changed_files.append((
                            to_path, to_tree.get_file_text(file_id)))
            finally:
                from_tree.unlock()
        finally:
            to_tree.unlock()

    def _uploader_person_pot(self, series):
        """Determine which person is the uploader for a pot file."""
        # Default uploader is the driver or owner of the series.
        uploader = series.driver
        if uploader is None:
            uploader = series.owner
        return uploader

    def _uploader_person_po(self, series):
        """Determine which person is the uploader for a po file."""
        # For po files, try to determine the author of the latest push.
        uploader = None
        revision = self.branch.getTipRevision()
        if revision is not None and revision.revision_author is not None:
            uploader = revision.revision_author.person
        if uploader is None:
            uploader = self._uploader_person_pot(series)
        return uploader

    def run(self):
        """See `IRosettaUploadJob`."""
        # This is not called upon job creation because the branch would
        # neither have been mirrored nor scanned then.
        self._init_translation_file_lists()
        # Get the product series that are connected to this branch and
        # that want to upload translations.
        productseries = self._find_product_series(
            self.branch, self.force_translations_upload)
        translation_import_queue = getUtility(ITranslationImportQueue)
        for series in productseries:
            approver = TranslationBranchApprover(self.file_names,
                                                 productseries=series)
            for iter_info in self._iter_lists_and_uploaders(series):
                file_names, changed_files, uploader = iter_info
                for upload_file_name, upload_file_content in changed_files:
                    if len(upload_file_content) == 0:
                        continue # Skip empty files
                    entry = translation_import_queue.addOrUpdateEntry(
                        upload_file_name, upload_file_content,
                        True, uploader, productseries=series)
                    approver.approve(entry)

    @staticmethod
    def iterReady():
        """See `IRosettaUploadJobSource`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, MASTER_FLAVOR)
        jobs = store.using(BranchJob, Job, Branch).find(
            (BranchJob),
            And(BranchJob.job_type == BranchJobType.ROSETTA_UPLOAD,
                BranchJob.job == Job.id,
                BranchJob.branch == Branch.id,
                Branch.last_mirrored_id == Branch.last_scanned_id,
                Job.id.is_in(Job.ready_jobs)))
        return (RosettaUploadJob(job) for job in jobs)

    @staticmethod
    def findUnfinishedJobs(branch):
        """See `IRosettaUploadJobSource`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, MASTER_FLAVOR)
        jobs = store.using(BranchJob, Job).find((BranchJob), And(
            Job.id == BranchJob.id,
            BranchJob.branch == branch,
            BranchJob.job_type == BranchJobType.ROSETTA_UPLOAD,
            Job._status != JobStatus.COMPLETED,
            Job._status != JobStatus.FAILED))
        return jobs


class ReclaimBranchSpaceJob(BranchJobDerived):
    """Reclaim the disk space used by a branch that's deleted from the DB."""

    implements(IReclaimBranchSpaceJob)

    classProvides(IReclaimBranchSpaceJobSource)

    class_job_type = BranchJobType.RECLAIM_BRANCH_SPACE

    @classmethod
    def create(cls, branch_id):
        """See `IBranchDiffJobSource`."""
        metadata = {'branch_id': branch_id}
        # The branch_job has a branch of None, as there is no branch left in
        # the database to refer to.
        start = SQL("CURRENT_TIMESTAMP AT TIME ZONE 'UTC' + '7 days'")
        branch_job = BranchJob(
            None, cls.class_job_type, metadata, scheduled_start=start)
        return cls(branch_job)

    @property
    def branch_id(self):
        return self.metadata['branch_id']

    def run(self):
        mirrored_path = os.path.join(
            config.codehosting.mirrored_branches_root,
            branch_id_to_path(self.branch_id))
        hosted_path = os.path.join(
            config.codehosting.hosted_branches_root,
            branch_id_to_path(self.branch_id))
        if os.path.exists(mirrored_path):
            shutil.rmtree(mirrored_path)
        if os.path.exists(hosted_path):
            shutil.rmtree(hosted_path)

