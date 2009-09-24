"""Land an approved merge proposal."""

import os

from launchpadlib.launchpad import (
    Launchpad, EDGE_SERVICE_ROOT, STAGING_SERVICE_ROOT)
from lazr.uri import URI

# XXX: JonathanLange 2009-09-24: Both of these are available in more recent
# versions of launchpadlib. When we start using such versions, we should
# instead import these from launchpadlib.
DEV_SERVICE_ROOT = 'https://api.launchpad.dev/beta/'
LPNET_SERVICE_ROOT = 'https://api.launchpad.net/beta/'


class MissingReviewError(Exception):
    """Raised when we try to get a review message without enough reviewers."""


class LaunchpadBranchLander:

    name = 'launchpad-branch-lander'
    cache_dir = '~/.launchpadlib/cache'

    def __init__(self, launchpad):
        self._launchpad = launchpad

    @classmethod
    def load(cls, service_root=EDGE_SERVICE_ROOT):
        # XXX: JonathanLange 2009-09-24: No unit tests.
        cache_dir = os.path.expanduser(cls.cache_dir)
        # XXX: JonathanLange 2009-09-24 bug=435813: If cached data invalid,
        # there's no easy way to delete it and try again.
        launchpad = Launchpad.login_with(cls.name, service_root, cache_dir)
        return cls(launchpad)

    def load_merge_proposal(self, mp_url):
        """Get the merge proposal object for the 'mp_url'."""
        # XXX: JonathanLange 2009-09-24: No unit tests.
        web_mp_uri = URI(mp_url)
        api_mp_uri = self._launchpad._root_uri.append(
            web_mp_uri.path.lstrip('/'))
        return MergeProposal(self._launchpad.load(str(api_mp_uri)))


class MergeProposal:
    """Wrapper around launchpadlib `IBranchMergeProposal` for landing."""

    def __init__(self, mp):
        """Construct a merge proposal.

        :param mp: A launchpadlib `IBranchMergeProposal`.
        """
        self._mp = mp
        self._launchpad = mp._root

    @property
    def source_branch(self):
        """The push URL of the source branch."""
        return str(self._get_push_url(self._mp.source_branch))

    @property
    def target_branch(self):
        """The push URL of the target branch."""
        return str(self._get_push_url(self._mp.target_branch))

    @property
    def commit_message(self):
        """The commit message specified on the merge proposal."""
        return self._mp.commit_message

    @property
    def is_approved(self):
        """Is this merge proposal approved for landing."""
        return self._mp.queue_status == 'Approved'

    def get_stakeholder_emails(self):
        """Return a collection of people who should know about branch landing.

        Used to determine who to email with the ec2 test results.

        :return: A set of `IPerson`s.
        """
        # XXX: JonathanLange 2009-09-24: No unit tests.
        return map(
            get_email,
            set([self._mp.source_branch.owner, self._launchpad.me]))

    def get_reviews(self):
        """Return a dictionary of all Approved reviews.

        Used to determine who has actually approved a branch for landing. The
        key of the dictionary is the type of review, and the value is the list
        of people who have voted Approve with that type.

        Common types include 'code', 'db', 'ui' and of course `None`.
        """
        reviews = {}
        for vote in self._mp.votes:
            comment = vote.comment
            if comment is None or comment.vote != "Approve":
                continue
            reviewers = reviews.setdefault(vote.review_type, [])
            reviewers.append(vote.reviewer)
        return reviews

    def get_bugs(self):
        """Return a collection of bugs linked to the source branch."""
        return self._mp.source_branch.linked_bugs

    def _get_push_url(self, branch):
        """Return the push URL for 'branch'.

        This function is a work-around for Launchpad's lack of exposing the
        branch's push URL.

        :param branch: A launchpadlib `IBranch`.
        """
        # XXX: JonathanLange 2009-09-24: No unit tests.
        host = get_bazaar_host(str(self._launchpad._root_uri))
        # XXX: JonathanLange 2009-09-24 bug=435790: lazr.uri allows a path
        # without a leading '/' and then doesn't insert a '/' in the final
        # URL. Do it ourselves.
        return URI(scheme='bzr+ssh', host=host, path='/' + branch.unique_name)

    def get_commit_message(self, commit_text, testfix=False):
        """Get the Launchpad-style commit message for a merge proposal."""
        reviews = self.get_reviews()
        bugs = self.get_bugs()
        if testfix:
            testfix = '[testfix]'
        else:
            testfix = ''
        return '%s%s%s %s' % (
            testfix,
            get_reviewer_clause(reviews),
            get_bugs_clause(bugs),
            commit_text)


def get_email(person):
    """Get the preferred email address for 'person'."""
    email_object = person.preferred_email_address
    # XXX: JonathanLange 2009-09-24 bug=319432: This raises a very obscure
    # error when the email address isn't set. e.g. with name12 in the sample
    # data. e.g. "httplib2.RelativeURIError: Only absolute URIs are allowed.
    # uri = tag:launchpad.net:2008:redacted".
    return email_object.email


def get_bugs_clause(bugs):
    """Return the bugs clause of a commit message.

    :param bugs: A collection of `IBug` objects.
    :return: A string of the form "[bug=A,B,C]".
    """
    if not bugs:
        return ''
    return '[bug=%s]' % ','.join(str(bug.id) for bug in bugs)


def get_reviewer_handle(reviewer):
    """Get the handle for 'reviewer'.

    The handles of reviewers are included in the commit message for Launchpad
    changes. Historically, these handles have been the IRC nicks. Thus, if
    'reviewer' has an IRC nickname for Freenode, we use that. Otherwise we use
    their Launchpad username.

    :param reviewer: A launchpadlib `IPerson` object.
    :return: unicode text.
    """
    irc_handles = reviewer.irc_nicknames
    for handle in irc_handles:
        if handle.network == 'irc.freenode.net':
            return handle.nickname
    return reviewer.name


def _comma_separated_names(things):
    """Return a string of comma-separated names of 'things'."""
    return ','.join(thing.name for thing in things)


def get_reviewer_clause(reviewers):
    """Get the reviewer section of a commit message, given the reviewers.

    :param reviewers: A dict mapping review types to lists of reviewers, as
        returned by 'get_reviews'.
    :return: A string like u'[r=foo,bar][ui=plop]'.
    """
    code_reviewers = reviewers.get(None, [])
    code_reviewers.extend(reviewers.get('code', []))
    code_reviewers.extend(reviewers.get('db', []))
    if not code_reviewers:
        raise MissingReviewError("Need approved votes in order to land.")
    ui_reviewers = reviewers.get('ui', [])
    if ui_reviewers:
        ui_clause = _comma_separated_names(ui_reviewers)
    else:
        ui_clause = 'none'
    rc_reviewers = reviewers.get('release-critical', [])
    if rc_reviewers:
        rc_clause = (
            '[release-critical=%s]' % _comma_separated_names(rc_reviewers))
    else:
        rc_clause = ''
    return '%s[r=%s][ui=%s]' % (
        rc_clause, _comma_separated_names(code_reviewers), ui_clause)


def get_bazaar_host(api_root):
    """Get the Bazaar service for the given API root."""
    # XXX: JonathanLange 2009-09-24 bug=435803: This is only needed because
    # Launchpad doesn't expose the push URL for branches.
    if api_root == EDGE_SERVICE_ROOT:
        return 'bazaar.launchpad.net'
    elif api_root == DEV_SERVICE_ROOT:
        return 'bazaar.launchpad.dev'
    elif api_root == STAGING_SERVICE_ROOT:
        return 'bazaar.staging.launchpad.net'
    elif api_root == LPNET_SERVICE_ROOT:
        return 'bazaar.launchpad.net'
    else:
        raise ValueError(
            'Cannot determine Bazaar host. "%s" not a recognized Launchpad '
            'API root.' % (api_root,))
