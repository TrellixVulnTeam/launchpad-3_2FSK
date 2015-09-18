# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Git reference views."""

__metaclass__ = type

__all__ = [
    'GitRefContextMenu',
    'GitRefNavigation',
    'GitRefRegisterMergeProposalView',
    'GitRefView',
    ]

import json

from lazr.restful.interface import copy_field
from zope.component import getUtility
from zope.formlib.widgets import TextAreaWidget
from zope.interface import Interface
from zope.publisher.interfaces import NotFound
from zope.schema import (
    Bool,
    Choice,
    Text,
    TextLine,
    )

from lp import _
from lp.app.browser.launchpadform import (
    action,
    custom_widget,
    LaunchpadFormView,
    )
from lp.app.widgets.suggestion import TargetGitRepositoryWidget
from lp.code.browser.branchmergeproposal import (
    latest_proposals_for_each_branch,
    )
from lp.code.errors import InvalidBranchMergeProposal
from lp.code.interfaces.branchmergeproposal import IBranchMergeProposal
from lp.code.interfaces.codereviewvote import ICodeReviewVoteReference
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import IGitRepositorySet
from lp.code.model.gitrepository import GitRepository
from lp.services.database.bulk import load_related
from lp.services.helpers import english_list
from lp.services.propertycache import cachedproperty
from lp.services.webapp import (
    canonical_url,
    ContextMenu,
    LaunchpadView,
    Link,
    Navigation,
    stepthrough,
    )
from lp.services.webapp.authorization import check_permission
from lp.snappy.browser.hassnaps import (
    HasSnapsMenuMixin,
    HasSnapsViewMixin,
    )


# XXX cjwatson 2015-05-26: We can get rid of this after a short while, since
# it's just a compatibility redirection.
class GitRefNavigation(Navigation):

    usedfor = IGitRef

    @stepthrough("+merge")
    def traverse_merge_proposal(self, id):
        """Traverse to an `IBranchMergeProposal`."""
        try:
            id = int(id)
        except ValueError:
            # Not a number.
            return None
        proposal = self.context.getMergeProposalByID(id)
        if proposal is not None:
            return self.redirectSubTree(canonical_url(proposal))


class GitRefContextMenu(ContextMenu, HasSnapsMenuMixin):
    """Context menu for Git references."""

    usedfor = IGitRef
    facet = 'branches'
    links = ['create_snap', 'register_merge']

    def register_merge(self):
        text = 'Propose for merging'
        enabled = self.context.namespace.supports_merge_proposals
        return Link('+register-merge', text, icon='add', enabled=enabled)


class GitRefView(LaunchpadView, HasSnapsViewMixin):

    @property
    def label(self):
        return self.context.display_name

    @property
    def tip_commit_info(self):
        return {
            "sha1": self.context.commit_sha1,
            "author": self.context.author,
            "author_date": self.context.author_date,
            "commit_message": self.context.commit_message,
            }

    @property
    def show_merge_links(self):
        """Return whether or not merge proposal links should be shown.

        Merge proposal links should not be shown if there is only one
        reference in the entire target.
        """
        if not self.context.namespace.supports_merge_proposals:
            return False
        repositories = self.context.namespace.collection.getRepositories()
        if repositories.count() > 1:
            return True
        repository = repositories.one()
        if repository is None:
            return False
        return repository.refs.count() > 1

    @cachedproperty
    def landing_targets(self):
        """Return a filtered list of landing targets."""
        return latest_proposals_for_each_branch(self.context.landing_targets)

    @cachedproperty
    def landing_candidates(self):
        """Return a decorated list of landing candidates."""
        candidates = list(self.context.landing_candidates)
        load_related(
            GitRepository, candidates,
            ["source_git_repositoryID", "prerequisite_git_repositoryID"])
        return [proposal for proposal in candidates
                if check_permission("launchpad.View", proposal)]

    def _getBranchCountText(self, count):
        """Help to show user friendly text."""
        if count == 0:
            return 'No branches'
        elif count == 1:
            return '1 branch'
        else:
            return '%s branches' % count

    @cachedproperty
    def landing_candidate_count_text(self):
        return self._getBranchCountText(len(self.landing_candidates))

    @cachedproperty
    def dependent_landings(self):
        return [proposal for proposal in self.context.dependent_landings
                if check_permission("launchpad.View", proposal)]

    @cachedproperty
    def dependent_landing_count_text(self):
        return self._getBranchCountText(len(self.dependent_landings))


class GitRefRegisterMergeProposalSchema(Interface):
    """The schema to define the form for registering a new merge proposal."""

    target_git_repository = Choice(
        title=_("Target repository"),
        vocabulary="GitRepository", required=True, readonly=True,
        description=_("The repository that the source will be merged into."))

    target_git_path = TextLine(
        title=_("Target reference path"), required=True, readonly=True,
        description=_(
            "The reference within the target repository that the source will "
            "be merged into."))

    prerequisite_git_repository = Choice(
        title=_("Prerequisite repository"),
        vocabulary="GitRepository", required=False, readonly=True,
        description=_("The repository that the source will be merged into."))

    prerequisite_git_path = TextLine(
        title=_("Prerequisite reference path"), required=False, readonly=True,
        description=_(
            "The reference within the target repository that the source will "
            "be merged into."))

    comment = Text(
        title=_('Description of the Change'), required=False,
        description=_('Describe what changes your branch introduces, '
                      'what bugs it fixes, or what features it implements. '
                      'Ideally include rationale and how to test.'))

    reviewer = copy_field(
        ICodeReviewVoteReference['reviewer'], required=False)

    review_type = copy_field(
        ICodeReviewVoteReference['review_type'],
        description=u'Lowercase keywords describing the type of review you '
                     'would like to be performed.')

    commit_message = IBranchMergeProposal['commit_message']

    needs_review = Bool(
        title=_("Needs review"), required=True, default=True,
        description=_(
            "Is the proposal ready for review now?"))


class GitRefRegisterMergeProposalView(LaunchpadFormView):
    """The view to register new Git merge proposals."""

    schema = GitRefRegisterMergeProposalSchema
    for_input = True

    custom_widget('target_git_repository', TargetGitRepositoryWidget)
    custom_widget('comment', TextAreaWidget, cssClass='comment-text')

    page_title = label = 'Propose for merging'

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    def initialize(self):
        """Show a 404 if the repository namespace doesn't support proposals."""
        if not self.context.namespace.supports_merge_proposals:
            raise NotFound(self.context, '+register-merge')
        super(GitRefRegisterMergeProposalView, self).initialize()

    @action('Propose Merge', name='register',
            failure=LaunchpadFormView.ajax_failure_handler)
    def register_action(self, action, data):
        """Register the new merge proposal."""

        registrant = self.user
        source_ref = self.context
        target_ref = data['target_git_repository'].getRefByPath(
            data['target_git_path'])
        if (data.get('prerequisite_git_repository') is not None and
                data.get('prerequisite_git_path') is not None):
            prerequisite_ref = (
                data['prerequisite_git_repository'].getRefByPath(
                    data['prerequisite_git_path']))
        else:
            prerequisite_ref = None

        review_requests = []
        reviewer = data.get('reviewer')
        review_type = data.get('review_type')
        if reviewer is None:
            reviewer = target_ref.code_reviewer
        if reviewer is not None:
            review_requests.append((reviewer, review_type))

        repository_names = [
            ref.repository.unique_name for ref in (source_ref, target_ref)]
        repository_set = getUtility(IGitRepositorySet)
        visibility_info = repository_set.getRepositoryVisibilityInfo(
            self.user, reviewer, repository_names)
        visible_repositories = list(visibility_info['visible_repositories'])
        if self.request.is_ajax and len(visible_repositories) < 2:
            self.request.response.setStatus(400, "Repository Visibility")
            self.request.response.setHeader(
                'Content-Type', 'application/json')
            return json.dumps({
                'person_name': visibility_info['person_name'],
                'repositories_to_check': repository_names,
                'visible_repositories': visible_repositories,
            })

        try:
            proposal = source_ref.addLandingTarget(
                registrant=registrant, merge_target=target_ref,
                merge_prerequisite=prerequisite_ref,
                needs_review=data['needs_review'],
                description=data.get('comment'),
                review_requests=review_requests,
                commit_message=data.get('commit_message'))
            if len(visible_repositories) < 2:
                invisible_repositories = [
                    ref.repository.unique_name
                    for ref in (source_ref, target_ref)
                    if ref.repository.unique_name not in visible_repositories]
                self.request.response.addNotification(
                    'To ensure visibility, %s is now subscribed to: %s'
                    % (visibility_info['person_name'],
                       english_list(invisible_repositories)))
            # Success so we do a client redirect to the new mp page.
            if self.request.is_ajax:
                self.request.response.setStatus(201)
                self.request.response.setHeader(
                    'Location', canonical_url(proposal))
                return None
            else:
                self.next_url = canonical_url(proposal)
        except InvalidBranchMergeProposal as error:
            self.addError(str(error))

    def _validateRef(self, data, name):
        repository = data.get('%s_git_repository' % name)
        path = data.get('%s_git_path' % name)
        if path:
            ref = repository.getRefByPath(path)
        else:
            ref = None
        if ref is None:
            self.setFieldError(
                '%s_git_path' % name,
                "The %s path must be the path of a reference in the "
                "%s repository." % (name, name))
        elif ref == self.context:
            self.setFieldError(
                '%s_git_path' % name,
                "The %s repository and path together cannot be the same "
                "as the source repository and path." % name)
        return repository

    def validate(self, data):
        source_ref = self.context
        target_repository = self._validateRef(data, 'target')
        if not target_repository.isRepositoryMergeable(source_ref.repository):
            self.setFieldError(
                'target_git_repository',
                "%s is not mergeable into this repository." %
                source_ref.repository.identity)
        if data.get('prerequisite_git_repository') is not None:
            prerequisite_repository = self._validateRef(data, 'prerequisite')
            if not target_repository.isRepositoryMergeable(
                    prerequisite_repository):
                self.setFieldError(
                    'prerequisite_git_repository',
                    "This repository is not mergeable into %s." %
                    target_repository.identity)
