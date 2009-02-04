# Copyright 2007-2008 Canonical Ltd.  All rights reserved.

"""Testing infrastructure for the Launchpad application.

This module should not have any actual tests.
"""

__metaclass__ = type
__all__ = [
    'LaunchpadObjectFactory',
    'ObjectFactory',
    'time_counter',
    ]

from datetime import datetime, timedelta
from email.Encoders import encode_base64
from email.Utils import make_msgid, formatdate
from email.Message import Message as EmailMessage
from email.MIMEText import MIMEText
from email.MIMEMultipart import MIMEMultipart
from itertools import count
from StringIO import StringIO

import pytz
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.codehosting.codeimport.worker import CodeImportSourceDetails
from canonical.librarian.interfaces import ILibrarianClient
from canonical.launchpad.components.packagelocation import PackageLocation
from canonical.launchpad.database.message import Message, MessageChunk
from canonical.launchpad.database.milestone import Milestone
from canonical.launchpad.database.sourcepackage import SourcePackage
from canonical.launchpad.interfaces.account import AccountStatus
from canonical.launchpad.interfaces.archive import (
    IArchiveSet, ArchivePurpose)
from canonical.launchpad.interfaces.branchmergequeue import (
    IBranchMergeQueueSet)
from canonical.launchpad.interfaces.branch import (
    BranchType, IBranchSet, UnknownBranchTypeError)
from canonical.launchpad.interfaces.branchmergeproposal import (
    BranchMergeProposalStatus)
from canonical.launchpad.interfaces.branchsubscription import (
    BranchSubscriptionNotificationLevel, CodeReviewNotificationLevel)
from canonical.launchpad.interfaces.bug import CreateBugParams, IBugSet
from canonical.launchpad.interfaces.bugtask import BugTaskStatus, IBugTaskSet
from canonical.launchpad.interfaces.bugtracker import (
    BugTrackerType, IBugTrackerSet)
from canonical.launchpad.interfaces.bugwatch import IBugWatchSet
from canonical.launchpad.interfaces.codeimport import ICodeImportSet
from canonical.launchpad.interfaces.codeimportevent import ICodeImportEventSet
from canonical.launchpad.interfaces.codeimportmachine import (
    CodeImportMachineState, ICodeImportMachineSet)
from canonical.launchpad.interfaces.codeimportresult import (
    CodeImportResultStatus, ICodeImportResultSet)
from canonical.launchpad.interfaces.codeimport import CodeImportReviewStatus
from canonical.launchpad.interfaces.country import ICountrySet
from canonical.launchpad.interfaces.distribution import (
    IDistribution, IDistributionSet)
from canonical.launchpad.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage)
from canonical.launchpad.interfaces.distroseries import (
    DistroSeriesStatus, IDistroSeries)
from canonical.launchpad.interfaces.emailaddress import (
    EmailAddressStatus, IEmailAddressSet)
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.interfaces.mailinglist import (
    IMailingListSet, MailingListStatus)
from canonical.launchpad.interfaces.mailinglistsubscription import (
    MailingListAutoSubscribePolicy)
from canonical.launchpad.interfaces.poll import (
    IPollSet, PollAlgorithm, PollSecrecy)
from canonical.launchpad.interfaces.potemplate import IPOTemplateSet
from canonical.launchpad.interfaces.person import (
    IPersonSet, PersonCreationRationale, TeamSubscriptionPolicy)
from canonical.launchpad.interfaces.product import (
    IProduct, IProductSet, License)
from canonical.launchpad.interfaces.productseries import (
    IProductSeries, RevisionControlSystems)
from canonical.launchpad.interfaces.project import IProjectSet
from canonical.launchpad.interfaces.publishing import PackagePublishingPocket
from canonical.launchpad.interfaces.revision import IRevisionSet
from canonical.launchpad.interfaces.shipit import (
    IShippingRequestSet, IStandardShipItRequestSet, ShipItFlavour,
    ShippingRequestStatus)
from canonical.launchpad.interfaces.sourcepackage import ISourcePackage
from canonical.launchpad.interfaces.sourcepackagename import (
    ISourcePackageNameSet)
from canonical.launchpad.interfaces.specification import (
    ISpecificationSet, SpecificationDefinitionStatus)
from canonical.launchpad.interfaces.translationgroup import (
    ITranslationGroupSet)
from canonical.launchpad.ftests import syncUpdate
from canonical.launchpad.mail.signedmessage import SignedMessage

SPACE = ' '


def time_counter(origin=None, delta=timedelta(seconds=5)):
    """A generator for yielding datetime values.

    Each time the generator yields a value, the origin is incremented
    by the delta.

    >>> now = time_counter(datetime(2007, 12, 1), timedelta(days=1))
    >>> now.next()
    datetime.datetime(2007, 12, 1, 0, 0)
    >>> now.next()
    datetime.datetime(2007, 12, 2, 0, 0)
    >>> now.next()
    datetime.datetime(2007, 12, 3, 0, 0)
    """
    if origin is None:
        origin = datetime.now(pytz.UTC)
    now = origin
    while True:
        yield now
        now += delta


# We use this for default paramters where None has a specific meaning.  For
# example, makeBranch(product=None) means "make a junk branch".
# None, because None means "junk branch".
_DEFAULT = object()


class ObjectFactory:
    """Factory methods for creating basic Python objects."""

    def __init__(self):
        # Initialise the unique identifier.
        self._integer = count(1)

    def getUniqueEmailAddress(self):
        return "%s@example.com" % self.getUniqueString('email')

    def getUniqueInteger(self):
        """Return an integer unique to this factory instance."""
        return self._integer.next()

    def getUniqueString(self, prefix=None):
        """Return a string unique to this factory instance.

        The string returned will always be a valid name that can be used in
        Launchpad URLs.

        :param prefix: Used as a prefix for the unique string. If unspecified,
            defaults to 'generic-string'.
        """
        if prefix is None:
            prefix = "generic-string"
        string = "%s%s" % (prefix, self.getUniqueInteger())
        return string.replace('_', '-').lower()

    def getUniqueURL(self, scheme=None, host=None):
        """Return a URL unique to this run of the test case."""
        if scheme is None:
            scheme = 'http'
        if host is None:
            host = "%s.domain.com" % self.getUniqueString('domain')
        return '%s://%s/%s' % (scheme, host, self.getUniqueString('path'))


class LaunchpadObjectFactory(ObjectFactory):
    """Factory methods for creating Launchpad objects.

    All the factory methods should be callable with no parameters.
    When this is done, the returned object should have unique references
    for any other required objects.
    """

    def makeCopyArchiveLocation(self, distribution=None, owner=None,
        name=None):
        """Create and return a new arbitrary location for copy packages."""
        copy_archive = self._makeArchive(distribution, owner, name,
                                         ArchivePurpose.COPY)

        distribution = copy_archive.distribution
        distroseries = distribution.currentseries
        pocket = PackagePublishingPocket.RELEASE

        location = PackageLocation(copy_archive, distribution, distroseries,
            pocket)
        return location

    def makePerson(self, email=None, name=None, password=None,
                   email_address_status=None, hide_email_addresses=False,
                   displayname=None, time_zone=None, latitude=None,
                   longitude=None):
        """Create and return a new, arbitrary Person.

        :param email: The email address for the new person.
        :param name: The name for the new person.
        :param password: The password for the person.
            This password can be used in setupBrowser in combination
            with the email address to create a browser for this new
            person.
        :param email_address_status: If specified, the status of the email
            address is set to the email_address_status.
        :param displayname: The display name to use for the person.
        :param hide_email_addresses: Whether or not to hide the person's email
            address(es) from other users.
        :param time_zone: This person's time zone, as a string.
        :param latitude: This person's latitude, as a float.
        :param longitude: This person's longitude, as a float.
        """
        if email is None:
            email = self.getUniqueEmailAddress()
        if name is None:
            name = self.getUniqueString('person-name')
        if password is None:
            password = self.getUniqueString('password')
        # By default, make the email address preferred.
        if (email_address_status is None
                or email_address_status == EmailAddressStatus.VALIDATED):
            email_address_status = EmailAddressStatus.PREFERRED
        # Set the password to test in order to allow people that have
        # been created this way can be logged in.
        person, email = getUtility(IPersonSet).createPersonAndEmail(
            email, rationale=PersonCreationRationale.UNKNOWN, name=name,
            password=password, displayname=displayname,
            hide_email_addresses=hide_email_addresses)

        if (time_zone is not None or latitude is not None or
            longitude is not None):
            # Remove the security proxy because setLocation() is protected
            # with launchpad.EditLocation.
            removeSecurityProxy(person).setLocation(
                latitude, longitude, time_zone, person)

        # To make the person someone valid in Launchpad, validate the
        # email.
        if email_address_status == EmailAddressStatus.PREFERRED:
            person.validateAndEnsurePreferredEmail(email)
            removeSecurityProxy(person.account).status = AccountStatus.ACTIVE
        # Make the account ACTIVE if we have a preferred email address now.
        if (person.preferredemail is not None and
            person.preferredemail.status == EmailAddressStatus.PREFERRED):
            removeSecurityProxy(person.account).status = AccountStatus.ACTIVE
        removeSecurityProxy(email).status = email_address_status
        syncUpdate(email)
        return person

    def makePersonByName(self, first_name, set_preferred_email=True,
                         use_default_autosubscribe_policy=False):
        """Create a new person with the given first name.

        The person will be given two email addresses, with the 'long form'
        (e.g. anne.person@example.com) as the preferred address.  Return
        the new person object.

        The person will also have their mailing list auto-subscription
        policy set to 'NEVER' unless 'use_default_autosubscribe_policy' is
        set to True. (This requires the Launchpad.Edit permission).  This
        is useful for testing, where we often want precise control over
        when a person gets subscribed to a mailing list.

        :param first_name: First name of the person, capitalized.
        :type first_name: string
        :param set_preferred_email: Flag specifying whether
            <name>.person@example.com should be set as the user's
            preferred email address.
        :type set_preferred_email: bool
        :param use_default_autosubscribe_policy: Flag specifying whether
            the person's `mailing_list_auto_subscribe_policy` should be set.
        :type use_default_autosubscribe_policy: bool
        :return: The newly created person.
        :rtype: `IPerson`
        """
        variable_name = first_name.lower()
        full_name = first_name + ' Person'
        # E.g. firstname.person@example.com will be an alternative address.
        preferred_address = variable_name + '.person@example.com'
        # E.g. aperson@example.org will be the preferred address.
        alternative_address = variable_name[0] + 'person@example.org'
        person, email = getUtility(IPersonSet).createPersonAndEmail(
            preferred_address,
            PersonCreationRationale.OWNER_CREATED_LAUNCHPAD,
            name=variable_name, displayname=full_name)
        if set_preferred_email:
            person.setPreferredEmail(email)

        if not use_default_autosubscribe_policy:
            # Shut off list auto-subscription so that we have direct control
            # over subscriptions in the doctests.
            person.mailing_list_auto_subscribe_policy = \
                MailingListAutoSubscribePolicy.NEVER
        getUtility(IEmailAddressSet).new(alternative_address, person,
                                         EmailAddressStatus.VALIDATED,
                                         person.account)
        return person

    def makeEmail(self, address, person, email_status=None):
        """Create a new email address for a person.

        :param address: The email address to create.
        :type address: string
        :param person: The person to assign the email address to.
        :type person: `IPerson`
        :param email_status: The default status of the email address,
            if given.  If not given, `EmailAddressStatus.VALIDATED`
            will be used.
        :type email_status: `EmailAddressStatus`
        :return: The newly created email address.
        :rtype: `IEmailAddress`
        """
        if email_status is None:
            email_status = EmailAddressStatus.VALIDATED
        return getUtility(IEmailAddressSet).new(
            address, person, email_status, person.account)

    def makeTeam(self, owner, displayname=None, email=None, name=None,
                 subscription_policy=TeamSubscriptionPolicy.OPEN,
                 visibility=None):
        """Create and return a new, arbitrary Team.

        :param owner: The IPerson to use as the team's owner.
        :param displayname: The team's display name.  If not given we'll use
            the auto-generated name.
        :param email: The email address to use as the team's contact address.
        :param subscription_policy: The subscription policy of the team.
        :param visibility: The team's visibility. If it's None, the default
            (public) will be used.
        """
        if name is None:
            name = self.getUniqueString('team-name')
        if displayname is None:
            displayname = SPACE.join(
                word.capitalize() for word in name.split('-'))
        team = getUtility(IPersonSet).newTeam(
            owner, name, displayname, subscriptionpolicy=subscription_policy)
        if visibility is not None:
            team.visibility = visibility
        if email is not None:
            team.setContactAddress(
                getUtility(IEmailAddressSet).new(email, team))
        return team

    def makePoll(self, team, name, title, proposition):
        """Create a new poll which starts tomorrow and lasts for a week."""
        dateopens = datetime.now(pytz.UTC) + timedelta(days=1)
        datecloses = dateopens + timedelta(days=7)
        return getUtility(IPollSet).new(
            team, name, title, proposition, dateopens, datecloses,
            PollSecrecy.SECRET, allowspoilt=True,
            poll_type=PollAlgorithm.SIMPLE)

    def makeTranslationGroup(
        self, owner, name=None, title=None, summary=None, url=None):
        """Create a new, arbitrary `TranslationGroup`."""
        if name is None:
            name = self.getUniqueString("translationgroup")
        if title is None:
            title = self.getUniqueString("title")
        if summary is None:
            summary = self.getUniqueString("summary")
        return getUtility(ITranslationGroupSet).new(
            name, title, summary, url, owner)

    def makeMilestone(self, product=None, distribution=None, name=None):
        if product is None and distribution is None:
            product = self.makeProduct()
        if name is None:
            name = self.getUniqueString()
        return Milestone(product=product, distribution=distribution,
                         name=name)

    def makeProduct(self, name=None, project=None, displayname=None,
                    licenses=None, owner=None, registrant=None,
                    title=None, summary=None):
        """Create and return a new, arbitrary Product."""
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueString('product-name')
        if displayname is None:
            if name is None:
                displayname = self.getUniqueString('displayname')
            else:
                displayname = name.capitalize()
        if licenses is None:
            licenses = [License.GNU_GPL_V2]
        if title is None:
            title = self.getUniqueString('title')
        if summary is None:
            summary = self.getUniqueString('summary')
        return getUtility(IProductSet).createProduct(
            owner,
            name,
            displayname,
            title,
            summary,
            self.getUniqueString('description'),
            licenses=licenses,
            project=project,
            registrant=registrant)

    def makeProductSeries(self, product=None, name=None, owner=None,
                          summary=None):
        """Create and return a new ProductSeries."""
        if product is None:
            product = self.makeProduct()
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueString()
        if summary is None:
            summary = self.getUniqueString()
        # We don't want to login() as the person used to create the product,
        # so we remove the security proxy before creating the series.
        naked_product = removeSecurityProxy(product)
        return naked_product.newSeries(owner=owner, name=name,
                                       summary=summary)

    def makeProject(self, name=None, displayname=None, title=None,
                    homepageurl=None, summary=None, owner=None,
                    description=None):
        """Create and return a new, arbitrary Project."""
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueString('project-name')
        if displayname is None:
            displayname = self.getUniqueString('displayname')
        if summary is None:
            summary = self.getUniqueString('summary')
        if description is None:
            description = self.getUniqueString('description')
        if title is None:
            title = self.getUniqueString('title')
        return getUtility(IProjectSet).new(
            name=name,
            displayname=displayname,
            title=title,
            homepageurl=homepageurl,
            summary=summary,
            description=description,
            owner=owner)

    def makeBranch(self, branch_type=None, owner=None,
                   name=None, product=_DEFAULT, url=_DEFAULT, registrant=None,
                   private=False, stacked_on=None, sourcepackage=None,
                   **optional_branch_args):
        """Create and return a new, arbitrary Branch of the given type.

        Any parameters for IBranchSet.new can be specified to override the
        default ones.
        """
        if branch_type is None:
            branch_type = BranchType.HOSTED
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueString('branch')

        if sourcepackage is None:
            if product is _DEFAULT:
                product = self.makeProduct()
            sourcepackagename = None
            distroseries = None
        else:
            assert product is _DEFAULT, (
                "Passed source package AND product details")
            product = None
            sourcepackagename = sourcepackage.sourcepackagename
            distroseries = sourcepackage.distroseries

        if registrant is None:
            registrant = owner

        if branch_type in (BranchType.HOSTED, BranchType.IMPORTED):
            url = None
        elif branch_type in (BranchType.MIRRORED, BranchType.REMOTE):
            if url is _DEFAULT:
                url = self.getUniqueURL()
        else:
            raise UnknownBranchTypeError(
                'Unrecognized branch type: %r' % (branch_type,))
        branch = getUtility(IBranchSet).new(
            branch_type, name, registrant, owner, product, url,
            distroseries=distroseries, sourcepackagename=sourcepackagename,
            **optional_branch_args)
        if private:
            removeSecurityProxy(branch).private = True
        if stacked_on is not None:
            removeSecurityProxy(branch).stacked_on = stacked_on
        return branch

    def makePackageBranch(self, sourcepackage=None, **kwargs):
        """Make a package branch on an arbitrary package.

        See `makeBranch` for more information on arguments.
        """
        if sourcepackage is None:
            sourcepackage = self.makeSourcePackage()
        return self.makeBranch(sourcepackage=sourcepackage, **kwargs)

    def makePersonalBranch(self, owner=None, **kwargs):
        """Make a personal branch on an arbitrary person.

        See `makeBranch` for more information on arguments.
        """
        if owner is None:
            owner = self.makePerson()
        return self.makeBranch(
            owner=owner, product=None, sourcepackage=None, **kwargs)

    def makeProductBranch(self, product=None, **kwargs):
        """Make a product branch on an arbitrary product.

        See `makeBranch` for more information on arguments.
        """
        if product is None:
            product = self.makeProduct()
        return self.makeBranch(product=product, **kwargs)

    def makeAnyBranch(self, **kwargs):
        """Make a branch without caring about its container.

        See `makeBranch` for more information on arguments.
        """
        return self.makeProductBranch(**kwargs)

    def enableDefaultStackingForProduct(self, product, branch=None):
        """Give 'product' a default stacked-on branch.

        :param product: The product to give a default stacked-on branch to.
        :param branch: The branch that should be the default stacked-on
            branch.  If not supplied, a fresh branch will be created.
        """
        if branch is None:
            branch = self.makeBranch(product=product)
        # 'branch' might be private, so we remove the security proxy to get at
        # the methods.
        naked_branch = removeSecurityProxy(branch)
        naked_branch.startMirroring()
        naked_branch.mirrorComplete('rev1')
        # Likewise, we might not have permission to set the user_branch of the
        # development focus series.
        naked_series = removeSecurityProxy(product.development_focus)
        naked_series.user_branch = branch
        return branch

    def makeBranchMergeQueue(self, name=None):
        """Create a new multi branch merge queue."""
        if name is None:
            name = self.getUniqueString('name')
        return getUtility(IBranchMergeQueueSet).newMultiBranchMergeQueue(
            registrant=self.makePerson(),
            owner=self.makePerson(),
            name=name,
            summary=self.getUniqueString())

    def makeBranchMergeProposal(self, target_branch=None, registrant=None,
                                set_state=None, dependent_branch=None,
                                product=None, review_diff=None,
                                initial_comment=None):
        """Create a proposal to merge based on anonymous branches."""
        if not product:
            product = _DEFAULT
        if dependent_branch is not None:
            product = dependent_branch.product
        if target_branch is None:
            target_branch = self.makeBranch(product=product)
        product = target_branch.product
        if registrant is None:
            registrant = self.makePerson()
        source_branch = self.makeBranch(product=product)
        proposal = source_branch.addLandingTarget(
            registrant, target_branch, dependent_branch=dependent_branch,
            review_diff=review_diff, initial_comment=initial_comment)

        if (set_state is None or
            set_state == BranchMergeProposalStatus.WORK_IN_PROGRESS):
            # The initial state is work in progress, so do nothing.
            pass
        elif set_state == BranchMergeProposalStatus.NEEDS_REVIEW:
            proposal.requestReview()
        elif set_state == BranchMergeProposalStatus.CODE_APPROVED:
            proposal.approveBranch(
                proposal.target_branch.owner, 'some_revision')
        elif set_state == BranchMergeProposalStatus.REJECTED:
            proposal.rejectBranch(
                proposal.target_branch.owner, 'some_revision')
        elif set_state == BranchMergeProposalStatus.MERGED:
            proposal.markAsMerged()
        elif set_state == BranchMergeProposalStatus.MERGE_FAILED:
            proposal.mergeFailed(proposal.target_branch.owner)
        elif set_state == BranchMergeProposalStatus.QUEUED:
            proposal.commit_message = self.getUniqueString('commit message')
            proposal.enqueue(
                proposal.target_branch.owner, 'some_revision')
        elif set_state == BranchMergeProposalStatus.SUPERSEDED:
            proposal.resubmit(proposal.registrant)
        else:
            raise AssertionError('Unknown status: %s' % set_state)

        return proposal

    def makeBranchSubscription(self, branch=None, person=None):
        """Create a BranchSubscription.

        :param branch_title: The title to use for the created Branch
        :param person_displayname: The displayname for the created Person
        """
        if branch is None:
            branch = self.makeBranch()
        if person is None:
            person = self.makePerson()
        return branch.subscribe(person,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.NOEMAIL)

    def makeRevision(self, author=None, revision_date=None, parent_ids=None,
                     rev_id=None, log_body=None):
        """Create a single `Revision`."""
        if author is None:
            author = self.getUniqueString('author')
        if revision_date is None:
            revision_date = datetime.now(pytz.UTC)
        if parent_ids is None:
            parent_ids = []
        if rev_id is None:
            rev_id = self.getUniqueString('revision-id')
        if log_body is None:
            log_body = self.getUniqueString('log-body')
        return getUtility(IRevisionSet).new(
            revision_id=rev_id, log_body=log_body,
            revision_date=revision_date, revision_author=author,
            parent_ids=parent_ids, properties={})

    def makeRevisionsForBranch(self, branch, count=5, author=None,
                               date_generator=None):
        """Add `count` revisions to the revision history of `branch`.

        :param branch: The branch to add the revisions to.
        :param count: The number of revisions to add.
        :param author: A string for the author name.
        :param date_generator: A `time_counter` instance, defaults to starting
                               from 1-Jan-2007 if not set.
        """
        if date_generator is None:
            date_generator = time_counter(
                datetime(2007, 1, 1, tzinfo=pytz.UTC),
                delta=timedelta(days=1))
        sequence = branch.revision_count
        parent = branch.getTipRevision()
        if parent is None:
            parent_ids = []
        else:
            parent_ids = [parent.revision_id]

        revision_set = getUtility(IRevisionSet)
        if author is None:
            author = self.getUniqueString('author')
        for index in range(count):
            revision = revision_set.new(
                revision_id = self.getUniqueString('revision-id'),
                log_body=self.getUniqueString('log-body'),
                revision_date=date_generator.next(),
                revision_author=author,
                parent_ids=parent_ids,
                properties={})
            sequence += 1
            branch.createBranchRevision(sequence, revision)
            parent = revision
            parent_ids = [parent.revision_id]
        branch.updateScannedDetails(parent, sequence)

    def makeBug(self, product=None, owner=None, bug_watch_url=None,
                private=False, date_closed=None, title=None,
                date_created=None):
        """Create and return a new, arbitrary Bug.

        The bug returned uses default values where possible. See
        `IBugSet.new` for more information.

        :param product: If the product is not set, one is created
            and this is used as the primary bug target.
        :param owner: The reporter of the bug. If not set, one is created.
        :param bug_watch_url: If specified, create a bug watch pointing
            to this URL.
        """
        if product is None:
            product = self.makeProduct()
        if owner is None:
            owner = self.makePerson()
        if title is None:
            title = self.getUniqueString()
        create_bug_params = CreateBugParams(
            owner, title, comment=self.getUniqueString(), private=private,
            datecreated=date_created)
        create_bug_params.setBugTarget(product=product)
        bug = getUtility(IBugSet).createBug(create_bug_params)
        if bug_watch_url is not None:
            # fromText() creates a bug watch associated with the bug.
            getUtility(IBugWatchSet).fromText(bug_watch_url, bug, owner)
        if date_closed is not None:
            [bugtask] = bug.bugtasks
            bugtask.transitionToStatus(
                BugTaskStatus.FIXRELEASED, owner, when=date_closed)
        return bug

    def makeBugTask(self, bug=None, target=None):
        """Create and return a bug task.

        If the bug is already targeted to the given target, the existing
        bug task is returned.

        :param bug: The `IBug` the bug tasks should be part of. If None,
            one will be created.
        :param target: The `IBugTarget`, to which the bug will be
            targeted to.
        """
        if bug is None:
            bug = self.makeBug()
        if target is None:
            target = self.makeProduct()
        existing_bugtask = bug.getBugTask(target)
        if existing_bugtask is not None:
            return existing_bugtask
        owner = self.makePerson()

        if IProduct.providedBy(target):
            target_params = {'product': target}
        elif IProductSeries.providedBy(target):
            # We can't have a series task without a distribution task.
            self.makeBugTask(bug, target.product)
            target_params = {'productseries': target}
        elif IDistribution.providedBy(target):
            target_params = {'distribution': target}
        elif IDistributionSourcePackage.providedBy(target):
            target_params = {
                'distribution': target.distribution,
                'sourcepackagename': target.sourcepackagename,
                }
        elif IDistroSeries.providedBy(target):
            # We can't have a series task without a distribution task.
            self.makeBugTask(bug, target.distribution)
            target_params = {'distroseries': target}
        elif ISourcePackage.providedBy(target):
            distribution_package = target.distribution.getSourcePackage(
                target.sourcepackagename)
            # We can't have a series task without a distribution task.
            self.makeBugTask(bug, distribution_package)
            target_params = {
                'distroseries': target.distroseries,
                'sourcepackagename': target.sourcepackagename,
                }
        else:
            raise AssertionError('Unknown IBugTarget: %r' % target)

        return getUtility(IBugTaskSet).createTask(
            bug=bug, owner=owner, **target_params)

    def makeBugTracker(self, base_url=None, bugtrackertype=None):
        """Make a new bug tracker."""
        owner = self.makePerson()

        if base_url is None:
            base_url = 'http://%s.example.com/' % self.getUniqueString()
        if bugtrackertype is None:
            bugtrackertype = BugTrackerType.BUGZILLA

        return getUtility(IBugTrackerSet).ensureBugTracker(
            base_url, owner, bugtrackertype)

    def makeBugWatch(self, remote_bug=None, bugtracker=None, bug=None):
        """Make a new bug watch."""
        if remote_bug is None:
            remote_bug = self.getUniqueInteger()

        if bugtracker is None:
            bugtracker = self.makeBugTracker()

        if bug is None:
            bug = self.makeBug()
        owner = self.makePerson()
        return getUtility(IBugWatchSet).createBugWatch(
            bug, owner, bugtracker, str(remote_bug))

    def makeBugAttachment(self, bug=None, owner=None, data=None,
                          comment=None, filename=None, content_type=None):
        """Create and return a new bug attachment.

        :param bug: An `IBug` or a bug ID or name, or None, in which
            case a new bug is created.
        :param owner: An `IPerson`, or None, in which case a new
            person is created.
        :param data: A file-like object or a string, or None, in which
            case a unique string will be used.
        :param comment: An `IMessage` or a string, or None, in which
            case a new message will be generated.
        :param filename: A string, or None, in which case a unique
            string will be used.
        :param content_type: The MIME-type of this file.
        :return: An `IBugAttachment`.
        """
        if bug is None:
            bug = self.makeBug()
        elif isinstance(bug, (int, long, basestring)):
            bug = getUtility(IBugSet).getByNameOrID(str(bug))
        if owner is None:
            owner = self.makePerson()
        if data is None:
            data = self.getUniqueString()
        if comment is None:
            comment = self.getUniqueString()
        if filename is None:
            filename = self.getUniqueString()
        return bug.addAttachment(
            owner, data, comment, filename, content_type=content_type)

    def makeSignedMessage(self, msgid=None, body=None, subject=None,
            attachment_contents=None, force_transfer_encoding=False,
            email_address=None):
        mail = SignedMessage()
        if email_address is None:
            person = self.makePerson()
            email_address = person.preferredemail.email
        mail['From'] = email_address
        if subject is None:
            subject = self.getUniqueString('subject')
        mail['Subject'] = subject
        if msgid is None:
            msgid = self.makeUniqueRFC822MsgId()
        if body is None:
            body = self.getUniqueString('body')
        mail['Message-Id'] = msgid
        mail['Date'] = formatdate()
        if attachment_contents is None:
            mail.set_payload(body)
            body_part = mail
        else:
            body_part = EmailMessage()
            body_part.set_payload(body)
            mail.attach(body_part)
            attach_part = EmailMessage()
            attach_part.set_payload(attachment_contents)
            attach_part['Content-type'] = 'application/octet-stream'
            if force_transfer_encoding:
                encode_base64(attach_part)
            mail.attach(attach_part)
            mail['Content-type'] = 'multipart/mixed'
        body_part['Content-type'] = 'text/plain'
        if force_transfer_encoding:
            encode_base64(body_part)
        mail.parsed_string = mail.as_string()
        return mail

    def makeSpecification(self, product=None, title=None):
        """Create and return a new, arbitrary Blueprint.

        :param product: The product to make the blueprint on.  If one is
            not specified, an arbitrary product is created.
        """
        if product is None:
            product = self.makeProduct()
        if title is None:
            title = self.getUniqueString('title')
        return getUtility(ISpecificationSet).new(
            name=self.getUniqueString('name'),
            title=title,
            specurl=None,
            summary=self.getUniqueString('summary'),
            definition_status=SpecificationDefinitionStatus.NEW,
            owner=self.makePerson(),
            product=product)

    def makeCodeImport(self, svn_branch_url=None, cvs_root=None,
                       cvs_module=None, product=None, branch_name=None):
        """Create and return a new, arbitrary code import.

        The code import will be an import from a Subversion repository located
        at `url`, or an arbitrary unique url if the parameter is not supplied.
        """
        if svn_branch_url is cvs_root is cvs_module is None:
            svn_branch_url = self.getUniqueURL()

        if product is None:
            product = self.makeProduct()
        if branch_name is None:
            branch_name = self.getUniqueString('name')
        # The registrant gets emailed, so needs a preferred email.
        registrant = self.makePerson()

        code_import_set = getUtility(ICodeImportSet)
        if svn_branch_url is not None:
            return code_import_set.new(
                registrant, product, branch_name,
                rcs_type=RevisionControlSystems.SVN,
                svn_branch_url=svn_branch_url)
        else:
            return code_import_set.new(
                registrant, product, branch_name,
                rcs_type=RevisionControlSystems.CVS,
                cvs_root=cvs_root, cvs_module=cvs_module)

    def makeCodeImportEvent(self):
        """Create and return a CodeImportEvent."""
        code_import = self.makeCodeImport()
        person = self.makePerson()
        code_import_event_set = getUtility(ICodeImportEventSet)
        return code_import_event_set.newCreate(code_import, person)

    def makeCodeImportJob(self, code_import=None):
        """Create and return a new code import job for the given import.

        This implies setting the import's review_status to REVIEWED.
        """
        if code_import is None:
            code_import = self.makeCodeImport()
        code_import.updateFromData(
            {'review_status': CodeImportReviewStatus.REVIEWED},
            code_import.registrant)
        return code_import.import_job

    def makeCodeImportMachine(self, set_online=False, hostname=None):
        """Return a new CodeImportMachine.

        The machine will be in the OFFLINE state."""
        if hostname is None:
            hostname = self.getUniqueString('machine-')
        if set_online:
            state = CodeImportMachineState.ONLINE
        else:
            state = CodeImportMachineState.OFFLINE
        machine = getUtility(ICodeImportMachineSet).new(hostname, state)
        return machine

    def makeCodeImportResult(self, code_import=None, result_status=None,
                             date_started=None, date_finished=None,
                             log_excerpt=None, log_alias=None, machine=None):
        """Create and return a new CodeImportResult."""
        if code_import is None:
            code_import = self.makeCodeImport()
        if machine is None:
            machine = self.makeCodeImportMachine()
        requesting_user = None
        if log_excerpt is None:
            log_excerpt = self.getUniqueString()
        if result_status is None:
            result_status = CodeImportResultStatus.FAILURE
        if date_finished is None:
            # If a date_started is specified, then base the finish time
            # on that.
            if date_started is None:
                date_finished = time_counter().next()
            else:
                date_finished = date_started + timedelta(hours=4)
        if date_started is None:
            date_started = date_finished - timedelta(hours=4)
        if log_alias is None:
            log_alias = self.makeLibraryFileAlias()
        return getUtility(ICodeImportResultSet).new(
            code_import, machine, requesting_user, log_excerpt, log_alias,
            result_status, date_started, date_finished)

    def makeCodeImportSourceDetails(self, branch_id=None, rcstype=None,
                                    svn_branch_url=None, cvs_root=None,
                                    cvs_module=None):
        if branch_id is None:
            branch_id = self.getUniqueInteger()
        if rcstype is None:
            rcstype = 'svn'
        if rcstype == 'svn':
            assert cvs_root is cvs_module is None
            if svn_branch_url is None:
                svn_branch_url = self.getUniqueURL()
        elif rcstype == 'cvs':
            assert svn_branch_url is None
            if cvs_root is None:
                cvs_root = self.getUniqueString()
            if cvs_module is None:
                cvs_module = self.getUniqueString()
        else:
            raise AssertionError("Unknown rcstype %r." % rcstype)
        return CodeImportSourceDetails(
            branch_id, rcstype, svn_branch_url, cvs_root, cvs_module)

    def makeCodeReviewComment(self, sender=None, subject=None, body=None,
                              vote=None, vote_tag=None, parent=None,
                              merge_proposal=None):
        if sender is None:
            sender = self.makePerson()
        if subject is None:
            subject = self.getUniqueString('subject')
        if body is None:
            body = self.getUniqueString('content')
        if merge_proposal is None:
            if parent:
                merge_proposal = parent.branch_merge_proposal
            else:
                merge_proposal = self.makeBranchMergeProposal(
                    registrant=sender)
        return merge_proposal.createComment(
            sender, subject, body, vote, vote_tag, parent)

    def makeMessage(self, subject=None, content=None, parent=None,
                    owner=None):
        if subject is None:
            subject = self.getUniqueString()
        if content is None:
            content = self.getUniqueString()
        if owner is None:
            owner = self.makePerson()
        rfc822msgid = self.makeUniqueRFC822MsgId()
        message = Message(rfc822msgid=rfc822msgid, subject=subject,
            owner=owner, parent=parent)
        MessageChunk(message=message, sequence=1, content=content)
        return message

    def makeSeries(self, user_branch=None, import_branch=None,
                   name=None, product=None):
        """Create a new, arbitrary ProductSeries.

        :param user_branch: If supplied, the branch to set as
            ProductSeries.user_branch.
        :param import_branch: If supplied, the branch to set as
            ProductSeries.import_branch.
        :param product: If supplied, the name of the series.
        :param product: If supplied, the series is created for this product.
            Otherwise, a new product is created.
        """
        if product is None:
            product = self.makeProduct()
        if name is None:
            name = self.getUniqueString()
        # We don't want to login() as the person used to create the product,
        # so we remove the security proxy before creating the series.
        naked_product = removeSecurityProxy(product)
        series = naked_product.newSeries(
            product.owner, name, self.getUniqueString(), user_branch)
        if import_branch is not None:
            series.import_branch = import_branch
        syncUpdate(series)
        return series

    def makeShipItRequest(self, flavour=ShipItFlavour.UBUNTU):
        """Create a `ShipItRequest` associated with a newly created person.

        The request's status will be approved and it will contain an arbitrary
        number of CDs of the given flavour.
        """
        brazil = getUtility(ICountrySet)['BR']
        city = 'Sao Carlos'
        addressline = 'Antonio Rodrigues Cajado 1506'
        name = 'Guilherme Salgado'
        phone = '+551635015218'
        person = self.makePerson()
        request = getUtility(IShippingRequestSet).new(
            person, name, brazil, city, addressline, phone)
        # We don't want to login() as the person used to create the request,
        # so we remove the security proxy for changing the status.
        removeSecurityProxy(request).status = ShippingRequestStatus.APPROVED
        template = getUtility(IStandardShipItRequestSet).getByFlavour(
            flavour)[0]
        request.setQuantities({flavour: template.quantities})
        return request

    def makeLibraryFileAlias(self, log_data=None):
        """Make a library file, and return the alias."""
        if log_data is None:
            log_data = self.getUniqueString()
        filename = self.getUniqueString('filename')
        log_alias_id = getUtility(ILibrarianClient).addFile(
            filename, len(log_data), StringIO(log_data), 'text/plain')
        return getUtility(ILibraryFileAliasSet)[log_alias_id]

    def makeDistribution(self, name=None, displayname=None):
        """Make a new distribution."""
        if name is None:
            name = self.getUniqueString()
        if displayname is None:
            displayname = self.getUniqueString()
        title = self.getUniqueString()
        description = self.getUniqueString()
        summary = self.getUniqueString()
        domainname = self.getUniqueString()
        owner = self.makePerson()
        members = self.makeTeam(owner)
        return getUtility(IDistributionSet).new(
            name, displayname, title, description, summary, domainname,
            members, owner)

    def makeDistroRelease(self, distribution=None, version=None,
                          status=DistroSeriesStatus.DEVELOPMENT,
                          parent_series=None, name=None):
        """Make a new distro release."""
        if distribution is None:
            distribution = self.makeDistribution()
        if name is None:
            name = self.getUniqueString()

        # We don't want to login() as the person used to create the product,
        # so we remove the security proxy before creating the series.
        naked_distribution = removeSecurityProxy(distribution)
        return naked_distribution.newSeries(
            version="%s.0" % self.getUniqueInteger(),
            name=name,
            displayname=self.getUniqueString(),
            title=self.getUniqueString(), summary=self.getUniqueString(),
            description=self.getUniqueString(),
            parent_series=parent_series, owner=distribution.owner)

    def _makeArchive(self, distribution=None, owner=None, name=None,
                    purpose = None):
        """Create and return a new arbitrary archive.

        Note: this shouldn't generally be used except by other factory
        methods such as makeCopyArchiveLocation.
        """
        if distribution is None:
            distribution = self.makeDistribution()
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueString()
        if purpose is None:
            purpose = ArchivePurpose.PPA

        return getUtility(IArchiveSet).new(
            owner=owner, purpose=purpose,
            distribution=distribution, name=name)

    def makePOTemplate(self, productseries=None, distroseries=None,
                       sourcepackagename=None, owner=None, name=None,
                       translation_domain=None):
        """Make a new translation template."""
        if productseries is None and distroseries is None:
            # No context for this template; set up a productseries.
            productseries = self.makeProductSeries(owner=owner)
            # Make it use Translations, otherwise there's little point
            # to us creating a template for it.
            productseries.product.official_rosetta = True
        templateset = getUtility(IPOTemplateSet)
        subset = templateset.getSubset(
            distroseries, sourcepackagename, productseries)

        if name is None:
            name = self.getUniqueString()
        if translation_domain is None:
            translation_domain = self.getUniqueString()

        if owner is None:
            if productseries is None:
                owner = distroseries.owner
            else:
                owner = productseries.owner

        return subset.new(name, translation_domain, 'messages.pot', owner)

    def makePOFile(self, language_code, potemplate=None, owner=None):
        """Make a new translation file."""
        if potemplate is None:
            potemplate = self.makePOTemplate(owner=owner)
        return potemplate.newPOFile(language_code, requester=potemplate.owner)

    def makePOTMsgSet(self, potemplate, singular=None, plural=None,
                      sequence=None):
        """Make a new `POTMsgSet` in the given template."""
        if singular is None and plural is None:
            singular = self.getUniqueString()
        potmsgset = potemplate.createMessageSetFromText(singular, plural)
        if sequence is not None:
            potmsgset.setSequence(potemplate, sequence)
        return potmsgset

    def makeTranslationMessage(self, pofile=None, potmsgset=None,
                               translator=None, reviewer=None,
                               translations=None, lock_timestamp=None):
        """Make a new `TranslationMessage` in the given PO file."""
        if pofile is None:
            pofile = self.makePOFile('sr')
        if potmsgset is None:
            potmsgset = self.makePOTMsgSet(pofile.potemplate)
        if translator is None:
            translator = self.makePerson()
        if translations is None:
            translations = [self.getUniqueString()]

        return potmsgset.updateTranslation(pofile, translator, translations,
                                           is_imported=False,
                                           lock_timestamp=lock_timestamp)

    def makeTranslation(self, pofile, sequence,
                        english=None, translated=None,
                        is_imported=False):
        """Add a single current translation entry to the given pofile.
        This should only be used on pristine pofiles with pristine
        potemplates to avoid conflicts in the sequence numbers.
        For each entry a new POTMsgSet is created.

        :pofile: The pofile to add to.
        :sequence: The sequence number for the POTMsgSet.
        :english: The english string which becomes the msgid in the POTMsgSet.
        :translated: The translated string which becomes the msgstr.
        :is_imported: The is_imported flag of the translation message.
        """
        if english is None:
            english = self.getUniqueString('english')
        if translated is None:
            translated = self.getUniqueString('translated')
        naked_pofile = removeSecurityProxy(pofile)
        potmsgset = self.makePOTMsgSet(naked_pofile.potemplate, english,
            sequence=sequence)
        translation = removeSecurityProxy(
            self.makeTranslationMessage(naked_pofile, potmsgset,
                translations=[translated]))
        translation.is_imported = is_imported
        translation.is_current = True

    def makeTeamAndMailingList(self, team_name, owner_name):
        """Make a new active mailing list for the named team.

        :param team_name: The new team's name.
        :type team_name: string
        :param owner_name: The name of the team's owner.
        :type owner: string
        :return: The new team and mailing list.
        :rtype: (`ITeam`, `IMailingList`)
        """
        owner = getUtility(IPersonSet).getByName(owner_name)
        display_name = SPACE.join(
            word.capitalize() for word in team_name.split('-'))
        team = getUtility(IPersonSet).getByName(team_name)
        if team is None:
            team = self.makeTeam(
                owner, displayname=display_name, name=team_name)
        # Any member of the mailing-list-experts team can review a list
        # registration.  It doesn't matter which one.
        experts = getUtility(ILaunchpadCelebrities).mailing_list_experts
        reviewer = list(experts.allmembers)[0]
        team_list = getUtility(IMailingListSet).new(team, owner)
        team_list.review(reviewer, MailingListStatus.APPROVED)
        team_list.startConstructing()
        team_list.transitionToStatus(MailingListStatus.ACTIVE)
        return team, team_list

    def makeUniqueRFC822MsgId(self):
        """Make a unique RFC 822 message id.

        The created message id is guaranteed not to exist in the
        `Message` table already.
        """
        msg_id = make_msgid('launchpad')
        while Message.selectBy(rfc822msgid=msg_id).count() > 0:
            msg_id = make_msgid('launchpad')
        return msg_id

    def makeSourcePackageName(self, name=None):
        """Make an `ISourcePackageName`."""
        if name is None:
            name = self.getUniqueString()
        return getUtility(ISourcePackageNameSet).new(name)

    def makeSourcePackage(self, sourcepackagename=None, distroseries=None):
        """Make an `ISourcePackage`."""
        if sourcepackagename is None:
            sourcepackagename = self.makeSourcePackageName()
        if distroseries is None:
            distroseries = self.makeDistroRelease()
        return SourcePackage(sourcepackagename, distroseries)

    def makeEmailMessage(self, body=None, sender=None, to=None,
                         attachments=None):
        """Make an email message with possible attachments.

        :param attachments: Should be an interable of tuples containing
           (filename, content-type, payload)
        """
        if sender is None:
            sender = self.makePerson()
        if body is None:
            body = self.getUniqueString('body')
        if to is None:
            to = self.getUniqueEmailAddress()

        msg = MIMEMultipart()
        msg['Message-Id'] = make_msgid('launchpad')
        msg['Date'] = formatdate()
        msg['To'] = to
        msg['From'] = sender.preferredemail.email
        msg['Subject'] = 'Sample'

        if attachments is None:
            msg.set_payload(body)
        else:
            msg.attach(MIMEText(body))
            for filename, content_type, payload in attachments:
                attachment = EmailMessage()
                attachment.set_payload(payload)
                attachment['Content-Type'] = content_type
                attachment['Content-Disposition'] = (
                    'attachment; filename="%s"' % filename)
                msg.attach(attachment)
        return msg

    def makeMergeDirective(self, source_branch=None, target_branch=None,
        source_branch_url=None, target_branch_url=None):
        """Return a bzr merge directive object.

        :param source_branch: The source branch in the merge directive.
        :param target_branch: The target branch in the merge directive.
        :param source_branch_url: The URL of the source for the merge
            directive.
        :param target_branch_url: The URL of the target for the merge
            directive.
        """
        from bzrlib.merge_directive import MergeDirective2
        if source_branch_url is None:
            if source_branch is None:
                source_branch = self.makeAnyBranch()
            source_branch_url = (
                config.codehosting.supermirror_root +
                source_branch.unique_name)
        if target_branch_url is None:
            if target_branch is None:
                target_branch = self.makeAnyBranch()
            target_branch_url = (
                config.codehosting.supermirror_root +
                target_branch.unique_name)
        return MergeDirective2(
            'revid', 'sha', 0, 0, target_branch_url,
            source_branch=source_branch_url, base_revision_id='base-revid',
            patch='booga')

    def makeMergeDirectiveEmail(self, body='Hi!\n'):
        """Create an email with a merge directive attached.

        :param body: The message body to use for the email.
        :return: message, file_alias, source_branch, target_branch
        """
        target_branch = self.makeProductBranch()
        source_branch = self.makeProductBranch(
            product=target_branch.product)
        md = self.makeMergeDirective(source_branch, target_branch)
        message = self.makeSignedMessage(body=body,
            subject='My subject', attachment_contents=''.join(md.to_lines()))
        message_string = message.as_string()
        file_alias = getUtility(ILibraryFileAliasSet).create(
            '*', len(message_string), StringIO(message_string), '*')
        return message, file_alias, source_branch, target_branch
