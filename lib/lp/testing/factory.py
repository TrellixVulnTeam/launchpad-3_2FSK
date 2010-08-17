# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=F0401

from __future__ import with_statement

"""Testing infrastructure for the Launchpad application.

This module should not contain tests (but it should be tested).
"""

__metaclass__ = type
__all__ = [
    'GPGSigningContext',
    'is_security_proxied_or_harmless',
    'LaunchpadObjectFactory',
    'ObjectFactory',
    'remove_security_proxy_and_shout_at_engineer',
    ]

from contextlib import nested
from datetime import datetime, timedelta
from email.encoders import encode_base64
from email.utils import make_msgid, formatdate
from email.message import Message as EmailMessage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from itertools import count
from operator import isSequenceType
import os.path
from random import randint
from StringIO import StringIO
from textwrap import dedent
from threading import local
from types import InstanceType
import warnings

from bzrlib.plugins.builder.recipe import BaseRecipeBranch
import pytz

from twisted.python.util import mergeFunctionMetadata

from zope.component import ComponentLookupError, getUtility
from zope.security.proxy import (
    builtin_isinstance, Proxy, ProxyFactory, removeSecurityProxy)

from bzrlib.merge_directive import MergeDirective2

from canonical.autodecorate import AutoDecorate
from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import flush_database_updates

from canonical.launchpad.database.account import Account
from canonical.launchpad.database.message import Message, MessageChunk
from canonical.launchpad.interfaces import IMasterStore, IStore
from canonical.launchpad.interfaces.account import (
    AccountCreationRationale, AccountStatus, IAccountSet)
from canonical.launchpad.interfaces.emailaddress import (
    EmailAddressStatus, IEmailAddressSet)
from canonical.launchpad.interfaces.gpghandler import IGPGHandler
from lp.hardwaredb.interfaces.hwdb import (
    HWSubmissionFormat, IHWDeviceDriverLinkSet, IHWSubmissionDeviceSet,
    IHWSubmissionSet)
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.interfaces.temporaryblobstorage import (
    ITemporaryStorageManager)
from canonical.launchpad.ftests._sqlobject import syncUpdate
from canonical.launchpad.scripts.logger import QuietFakeLogger
from canonical.launchpad.webapp.dbpolicy import MasterDatabasePolicy
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)

from lp.archiveuploader.dscfile import DSCFile
from lp.archiveuploader.uploadpolicy import BuildDaemonUploadPolicy
from lp.blueprints.interfaces.specification import (
    ISpecificationSet, SpecificationDefinitionStatus)
from lp.blueprints.interfaces.sprint import ISprintSet

from lp.bugs.interfaces.bug import CreateBugParams, IBugSet
from lp.bugs.interfaces.bugtask import BugTaskStatus
from lp.bugs.interfaces.bugtracker import BugTrackerType, IBugTrackerSet
from lp.bugs.interfaces.bugwatch import IBugWatchSet
from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.buildmaster.interfaces.buildbase import BuildStatus
from lp.buildmaster.interfaces.buildfarmjob import BuildFarmJobType
from lp.buildmaster.model.buildqueue import BuildQueue

from lp.code.enums import (
    BranchMergeProposalStatus, BranchSubscriptionNotificationLevel,
    BranchType, CodeImportMachineState, CodeImportReviewStatus,
    CodeImportResultStatus, CodeReviewNotificationLevel,
    RevisionControlSystems)
from lp.code.errors import UnknownBranchTypeError
from lp.code.interfaces.branchmergequeue import IBranchMergeQueueSet
from lp.code.interfaces.branchnamespace import get_branch_namespace
from lp.code.interfaces.branchtarget import IBranchTarget
from lp.code.interfaces.codeimport import ICodeImportSet
from lp.code.interfaces.codeimportevent import ICodeImportEventSet
from lp.code.interfaces.codeimportmachine import ICodeImportMachineSet
from lp.code.interfaces.codeimportresult import ICodeImportResultSet
from lp.code.interfaces.revision import IRevisionSet
from lp.code.interfaces.sourcepackagerecipe import (
    ISourcePackageRecipeSource, MINIMAL_RECIPE_TEXT)
from lp.code.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuildSource,
    )
from lp.code.model.diff import Diff, PreviewDiff, StaticDiff
from lp.codehosting.codeimport.worker import CodeImportSourceDetails

from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.gpg import GPGKeyAlgorithm, IGPGKeySet
from lp.registry.interfaces.mailinglist import (
    IMailingListSet, MailingListStatus)
from lp.registry.interfaces.mailinglistsubscription import (
    MailingListAutoSubscribePolicy)
from lp.registry.interfaces.person import (
    IPerson, IPersonSet, PersonCreationRationale, TeamSubscriptionPolicy)
from lp.registry.interfaces.poll import IPollSet, PollAlgorithm, PollSecrecy
from lp.registry.interfaces.product import IProductSet, License
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.projectgroup import IProjectGroupSet
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.sourcepackage import (
    ISourcePackage, SourcePackageFileType, SourcePackageUrgency)
from lp.registry.interfaces.sourcepackagename import (
    ISourcePackageNameSet)
from lp.registry.interfaces.ssh import ISSHKeySet
from lp.registry.interfaces.distributionmirror import (
    MirrorContent, MirrorSpeed)
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.model.milestone import Milestone
from lp.registry.model.suitesourcepackage import SuiteSourcePackage

from lp.services.mail.signedmessage import SignedMessage
from lp.services.worlddata.interfaces.country import ICountrySet
from lp.services.worlddata.interfaces.language import ILanguageSet

from lp.soyuz.adapters.packagelocation import PackageLocation
from lp.soyuz.interfaces.archive import (
    default_name_by_purpose, IArchiveSet, ArchivePurpose)
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.soyuz.interfaces.binarypackagerelease import (
    BinaryPackageFileType, BinaryPackageFormat)
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.packageset import IPackagesetSet
from lp.soyuz.interfaces.processor import IProcessorFamilySet
from lp.soyuz.interfaces.publishing import (
    IPublishingSet, PackagePublishingPriority, PackagePublishingStatus)
from lp.soyuz.interfaces.section import ISectionSet
from lp.soyuz.model.binarypackagename import BinaryPackageName
from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
from lp.soyuz.model.files import BinaryPackageFile, SourcePackageReleaseFile
from lp.soyuz.model.processor import ProcessorFamilySet
from lp.testing import (
    ANONYMOUS,
    login,
    login_as,
    person_logged_in,
    run_with_login,
    temp_dir,
    time_counter,
    )
from lp.translations.interfaces.potemplate import IPOTemplateSet
from lp.translations.interfaces.translationimportqueue import (
    RosettaImportStatus)
from lp.translations.interfaces.translationfileformat import (
    TranslationFileFormat)
from lp.translations.interfaces.translationgroup import ITranslationGroupSet
from lp.translations.interfaces.translationsperson import ITranslationsPerson
from lp.translations.interfaces.translationtemplatesbuildjob import (
    ITranslationTemplatesBuildJobSource)
from lp.translations.interfaces.translator import ITranslatorSet
from lp.translations.model.translationimportqueue import (
    TranslationImportQueueEntry)


SPACE = ' '

DIFF = """\
=== zbqvsvrq svyr 'yvo/yc/pbqr/vagresnprf/qvss.cl'
--- yvo/yc/pbqr/vagresnprf/qvss.cl      2009-10-01 13:25:12 +0000
+++ yvo/yc/pbqr/vagresnprf/qvss.cl      2010-02-02 15:48:56 +0000
@@ -121,6 +121,10 @@
                 'Gur pbasyvpgf grkg qrfpevovat nal cngu be grkg pbasyvpgf.'),
              ernqbayl=Gehr))

+    unf_pbasyvpgf = Obby(
+        gvgyr=_('Unf pbasyvpgf'), ernqbayl=Gehr,
+        qrfpevcgvba=_('Gur cerivrjrq zretr cebqhprf pbasyvpgf.'))
+
     # Gur fpurzn sbe gur Ersrerapr trgf cngpurq va _fpurzn_pvephyne_vzcbegf.
     oenapu_zretr_cebcbfny = rkcbegrq(
         Ersrerapr(
"""


def default_master_store(func):
    """Decorator to temporarily set the default Store to the master.

    In some cases, such as in the middle of a page test story,
    we might be calling factory methods with the default Store set
    to the slave which breaks stuff. For instance, if we set an account's
    password that needs to happen on the master store and this is forced.
    However, if we then read it back the default Store has to be used.
    """

    def with_default_master_store(*args, **kw):
        try:
            store_selector = getUtility(IStoreSelector)
        except ComponentLookupError:
            # Utilities not registered. No policies.
            return func(*args, **kw)
        store_selector.push(MasterDatabasePolicy())
        try:
            return func(*args, **kw)
        finally:
            store_selector.pop()
    return mergeFunctionMetadata(func, with_default_master_store)


# We use this for default parameters where None has a specific meaning. For
# example, makeBranch(product=None) means "make a junk branch". None, because
# None means "junk branch".
_DEFAULT = object()


class GPGSigningContext:
    """A helper object to hold the fingerprint, password and mode."""

    def __init__(self, fingerprint, password='', mode=None):
        self.fingerprint = fingerprint
        self.password = password
        self.mode = mode


class ObjectFactory:
    """Factory methods for creating basic Python objects."""

    __metaclass__ = AutoDecorate(default_master_store)

    def __init__(self):
        # Initialise the unique identifier.
        self._local = local()

    def getUniqueEmailAddress(self):
        return "%s@example.com" % self.getUniqueString('email')

    def getUniqueInteger(self):
        """Return an integer unique to this factory instance.

        For each thread, this will be a series of increasing numbers, but the
        starting point will be unique per thread.
        """
        counter = getattr(self._local, 'integer', None)
        if counter is None:
            counter = count(randint(0, 1000000))
            self._local.integer = counter
        return counter.next()

    def getUniqueHexString(self, digits=None):
        """Return a unique hexadecimal string.

        :param digits: The number of digits in the string. 'None' means you
            don't care.
        :return: A hexadecimal string, with 'a'-'f' in lower case.
        """
        hex_number = '%x' % self.getUniqueInteger()
        if digits is not None:
            hex_number = hex_number.zfill(digits)
        return hex_number

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

    def getUniqueUnicode(self):
        return self.getUniqueString().decode('latin-1')

    def getUniqueURL(self, scheme=None, host=None):
        """Return a URL unique to this run of the test case."""
        if scheme is None:
            scheme = 'http'
        if host is None:
            host = "%s.domain.com" % self.getUniqueString('domain')
        return '%s://%s/%s' % (scheme, host, self.getUniqueString('path'))

    def getUniqueDate(self):
        """Return a unique date since January 1 2009.

        Each date returned by this function will more recent (or further into
        the future) than the previous one.
        """
        epoch = datetime(2009, 1, 1, tzinfo=pytz.UTC)
        return epoch + timedelta(minutes=self.getUniqueInteger())

    def makeCodeImportSourceDetails(self, branch_id=None, rcstype=None,
                                    url=None, cvs_root=None, cvs_module=None):
        if branch_id is None:
            branch_id = self.getUniqueInteger()
        if rcstype is None:
            rcstype = 'svn'
        if rcstype in ['svn', 'bzr-svn', 'hg']:
            assert cvs_root is cvs_module is None
            if url is None:
                url = self.getUniqueURL()
        elif rcstype == 'cvs':
            assert url is None
            if cvs_root is None:
                cvs_root = self.getUniqueString()
            if cvs_module is None:
                cvs_module = self.getUniqueString()
        elif rcstype == 'git':
            assert cvs_root is cvs_module is None
            if url is None:
                url = self.getUniqueURL(scheme='git')
        else:
            raise AssertionError("Unknown rcstype %r." % rcstype)
        return CodeImportSourceDetails(
            branch_id, rcstype, url, cvs_root, cvs_module)


class BareLaunchpadObjectFactory(ObjectFactory):
    """Factory methods for creating Launchpad objects.

    All the factory methods should be callable with no parameters.
    When this is done, the returned object should have unique references
    for any other required objects.
    """

    def loginAsAnyone(self):
        """Log in as an arbitrary person.

        If you want to log in as a celebrity, including admins, see
        `lp.testing.login_celebrity`.
        """
        login(ANONYMOUS)
        person = self.makePerson()
        login_as(person)
        return person

    def makeCopyArchiveLocation(self, distribution=None, owner=None,
        name=None, enabled=True):
        """Create and return a new arbitrary location for copy packages."""
        copy_archive = self.makeArchive(distribution, owner, name,
                                        ArchivePurpose.COPY, enabled)

        distribution = copy_archive.distribution
        distroseries = distribution.currentseries
        pocket = PackagePublishingPocket.RELEASE

        location = PackageLocation(copy_archive, distribution, distroseries,
            pocket)
        return ProxyFactory(location)

    def makeAccount(self, displayname, email=None, password=None,
                    status=AccountStatus.ACTIVE,
                    rationale=AccountCreationRationale.UNKNOWN):
        """Create and return a new Account."""
        account = getUtility(IAccountSet).new(
            rationale, displayname, password=password)
        removeSecurityProxy(account).status = status
        if email is None:
            email = self.getUniqueEmailAddress()
        email_status = EmailAddressStatus.PREFERRED
        if status != AccountStatus.ACTIVE:
            email_status = EmailAddressStatus.NEW
        email = self.makeEmail(
            email, person=None, account=account, email_status=email_status)
        return account

    def makeGPGKey(self, owner):
        """Give 'owner' a crappy GPG key for the purposes of testing."""
        key_id = self.getUniqueHexString(digits=8).upper()
        fingerprint = key_id + 'A' * 32
        return getUtility(IGPGKeySet).new(
            owner.id,
            keyid=key_id,
            fingerprint=fingerprint,
            keysize=self.getUniqueInteger(),
            algorithm=GPGKeyAlgorithm.R,
            active=True,
            can_encrypt=False)

    def makePerson(
        self, email=None, name=None, password=None,
        email_address_status=None, hide_email_addresses=False,
        displayname=None, time_zone=None, latitude=None, longitude=None):
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
        naked_person = removeSecurityProxy(person)
        naked_person._password_cleartext_cached = password

        assert person.password is not None, (
            'Password not set. Wrong default auth Store?')

        if (time_zone is not None or latitude is not None or
            longitude is not None):
            naked_person.setLocation(latitude, longitude, time_zone, person)

        # Make sure the non-security-proxied object is not returned.
        del naked_person

        # To make the person someone valid in Launchpad, validate the
        # email.
        if email_address_status == EmailAddressStatus.PREFERRED:
            account = IMasterStore(Account).get(
                Account, person.accountID)
            account.status = AccountStatus.ACTIVE
            person.validateAndEnsurePreferredEmail(email)

        removeSecurityProxy(email).status = email_address_status

        # Ensure updated ValidPersonCache
        flush_database_updates()
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
            # setPreferredEmail no longer activates the account
            # automatically.
            account = IMasterStore(Account).get(Account, person.accountID)
            account.activate(
                "Activated by factory.makePersonByName",
                password='foo',
                preferred_email=email)
            person.setPreferredEmail(email)

        if not use_default_autosubscribe_policy:
            # Shut off list auto-subscription so that we have direct control
            # over subscriptions in the doctests.
            person.mailing_list_auto_subscribe_policy = \
                MailingListAutoSubscribePolicy.NEVER
        account = IMasterStore(Account).get(Account, person.accountID)
        getUtility(IEmailAddressSet).new(
            alternative_address, person, EmailAddressStatus.VALIDATED,
            account)
        return person

    def makeEmail(self, address, person, account=None, email_status=None):
        """Create a new email address for a person.

        :param address: The email address to create.
        :type address: string
        :param person: The person to assign the email address to.
        :type person: `IPerson`
        :param account: The account to assign the email address to.  Will use
            the given person's account if None is provided.
        :type person: `IAccount`
        :param email_status: The default status of the email address,
            if given.  If not given, `EmailAddressStatus.VALIDATED`
            will be used.
        :type email_status: `EmailAddressStatus`
        :return: The newly created email address.
        :rtype: `IEmailAddress`
        """
        if email_status is None:
            email_status = EmailAddressStatus.VALIDATED
        if account is None:
            account = person.account
        return getUtility(IEmailAddressSet).new(
            address, person, email_status, account)

    def makeTeam(self, owner=None, displayname=None, email=None, name=None,
                 subscription_policy=TeamSubscriptionPolicy.OPEN,
                 visibility=None, members=None):
        """Create and return a new, arbitrary Team.

        :param owner: The person or person name to use as the team's owner.
            If not given, a person will be auto-generated.
        :type owner: `IPerson` or string
        :param displayname: The team's display name.  If not given we'll use
            the auto-generated name.
        :type string:
        :param email: The email address to use as the team's contact address.
        :type email: string
        :param subscription_policy: The subscription policy of the team.
        :type subscription_policy: `TeamSubscriptionPolicy`
        :param visibility: The team's visibility. If it's None, the default
            (public) will be used.
        :type visibility: `PersonVisibility`
        :param members: People or teams to be added to the new team
        :type members: An iterable of objects implementing IPerson
        :return: The new team
        :rtype: `ITeam`
        """
        if owner is None:
            owner = self.makePerson()
        elif isinstance(owner, basestring):
            owner = getUtility(IPersonSet).getByName(owner)
        else:
            pass
        if name is None:
            name = self.getUniqueString('team-name')
        if displayname is None:
            displayname = SPACE.join(
                word.capitalize() for word in name.split('-'))
        team = getUtility(IPersonSet).newTeam(
            owner, name, displayname, subscriptionpolicy=subscription_policy)
        if visibility is not None:
            # Visibility is normally restricted to launchpad.Commercial, so
            # removing the security proxy as we don't care here.
            removeSecurityProxy(team).visibility = visibility
        if email is not None:
            team.setContactAddress(
                getUtility(IEmailAddressSet).new(email, team))
        if members is not None:
            naked_team = removeSecurityProxy(team)
            for member in members:
                naked_team.addMember(member, owner)
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
        self, owner=None, name=None, title=None, summary=None, url=None):
        """Create a new, arbitrary `TranslationGroup`."""
        if owner is None:
            owner = self.makePerson()
        if name is None:
            name = self.getUniqueString("translationgroup")
        if title is None:
            title = self.getUniqueString("title")
        if summary is None:
            summary = self.getUniqueString("summary")
        return getUtility(ITranslationGroupSet).new(
            name, title, summary, url, owner)

    def makeTranslator(
        self, language_code, group=None, person=None, license=True):
        """Create a new, arbitrary `Translator`."""
        language = getUtility(ILanguageSet).getLanguageByCode(language_code)
        if group is None:
            group = self.makeTranslationGroup()
        if person is None:
            person = self.makePerson()
        tx_person = ITranslationsPerson(person)
        tx_person.translations_relicensing_agreement = license
        return getUtility(ITranslatorSet).new(group, language, person)

    def makeMilestone(
        self, product=None, distribution=None, productseries=None, name=None):
        if product is None and distribution is None and productseries is None:
            product = self.makeProduct()
        if distribution is None:
            if productseries is not None:
                product = productseries.product
            else:
                productseries = self.makeProductSeries(product=product)
            distroseries = None
        else:
            distroseries = self.makeDistroRelease(distribution=distribution)
        if name is None:
            name = self.getUniqueString()
        return ProxyFactory(
            Milestone(product=product, distribution=distribution,
                      productseries=productseries, distroseries=distroseries,
                      name=name))

    def makeProcessor(self, family=None, name=None, title=None,
                      description=None):
        """Create a new processor.

        :param family: Family of the processor
        :param name: Name of the processor
        :param title: Optional title
        :param description: Optional description
        :return: A `IProcessor`
        """
        if name is None:
            name = self.getUniqueString()
        if family is None:
            family = self.makeProcessorFamily()
        if title is None:
            title = "The %s processor" % name
        if description is None:
            description = "The %s and processor and compatible processors"
        return family.addProcessor(name, title, description)

    def makeProcessorFamily(self, name=None, title=None, description=None,
                            restricted=False):
        """Create a new processor family.

        :param name: Name of the family (e.g. x86)
        :param title: Optional title of the family
        :param description: Optional extended description
        :param restricted: Whether the processor family is restricted
        :return: A `IProcessorFamily`
        """
        if name is None:
            name = self.getUniqueString()
        if description is None:
            description = "Description of the %s processor family" % name
        if title is None:
            title = "%s and compatible processors." % name
        return getUtility(IProcessorFamilySet).new(name, title, description,
            restricted=restricted)

    def makeProductRelease(self, milestone=None, product=None,
                           productseries=None):
        if milestone is None:
            milestone = self.makeMilestone(product=product,
                                           productseries=productseries)
        with person_logged_in(milestone.productseries.product.owner):
            release = milestone.createProductRelease(
                milestone.product.owner, datetime.now(pytz.UTC))
        return release

    def makeProductReleaseFile(self, signed=True,
                               product=None, productseries=None,
                               milestone=None,
                               release=None,
                               description="test file"):
        signature_filename = None
        signature_content = None
        if signed:
            signature_filename = 'test.txt.asc'
            signature_content = '123'
        if release is None:
            release = self.makeProductRelease(product=product,
                                              productseries=productseries,
                                              milestone=milestone)
        with person_logged_in(release.milestone.product.owner):
            release_file = release.addReleaseFile(
                'test.txt', 'test', 'text/plain',
                uploader=release.milestone.product.owner,
                signature_filename=signature_filename,
                signature_content=signature_content,
                description=description)
        return release_file

    def makeProduct(
        self, name=None, project=None, displayname=None,
        licenses=None, owner=None, registrant=None,
        title=None, summary=None, official_malone=None,
        official_rosetta=None, bug_supervisor=None):
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
        product = getUtility(IProductSet).createProduct(
            owner,
            name,
            displayname,
            title,
            summary,
            self.getUniqueString('description'),
            licenses=licenses,
            project=project,
            registrant=registrant)
        if official_malone is not None:
            product.official_malone = official_malone
        if official_rosetta is not None:
            removeSecurityProxy(product).official_rosetta = official_rosetta
        if bug_supervisor is not None:
            naked_product = removeSecurityProxy(product)
            naked_product.bug_supervisor = bug_supervisor
        return product

    def makeProductSeries(self, product=None, name=None, owner=None,
                          summary=None, date_created=None):
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
        series = naked_product.newSeries(
            owner=owner, name=name, summary=summary)
        if date_created is not None:
            series.datecreated = date_created
        return ProxyFactory(series)

    def makeProject(self, name=None, displayname=None, title=None,
                    homepageurl=None, summary=None, owner=None,
                    description=None):
        """Create and return a new, arbitrary ProjectGroup."""
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
        return getUtility(IProjectGroupSet).new(
            name=name,
            displayname=displayname,
            title=title,
            homepageurl=homepageurl,
            summary=summary,
            description=description,
            owner=owner)

    def makeSprint(self, title=None, name=None):
        """Make a sprint."""
        if title is None:
            title = self.getUniqueString('title')
        owner = self.makePerson()
        if name is None:
            name = self.getUniqueString('name')
        time_starts = datetime(2009, 1, 1, tzinfo=pytz.UTC)
        time_ends = datetime(2009, 1, 2, tzinfo=pytz.UTC)
        time_zone = 'UTC'
        summary = self.getUniqueString('summary')
        return getUtility(ISprintSet).new(
            owner=owner, name=name, title=title, time_zone=time_zone,
            time_starts=time_starts, time_ends=time_ends, summary=summary)

    def makeBranch(self, branch_type=None, owner=None,
                   name=None, product=_DEFAULT, url=_DEFAULT, registrant=None,
                   private=False, stacked_on=None, sourcepackage=None,
                   reviewer=None, **optional_branch_args):
        """Create and return a new, arbitrary Branch of the given type.

        Any parameters for `IBranchNamespace.createBranch` can be specified to
        override the default ones.
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
            if owner.is_team:
                registrant = owner.teamowner
            else:
                registrant = owner

        if branch_type in (BranchType.HOSTED, BranchType.IMPORTED):
            url = None
        elif branch_type in (BranchType.MIRRORED, BranchType.REMOTE):
            if url is _DEFAULT:
                url = self.getUniqueURL()
        else:
            raise UnknownBranchTypeError(
                'Unrecognized branch type: %r' % (branch_type, ))

        namespace = get_branch_namespace(
            owner, product=product, distroseries=distroseries,
            sourcepackagename=sourcepackagename)
        branch = namespace.createBranch(
            branch_type=branch_type, name=name, registrant=registrant,
            url=url, **optional_branch_args)
        if private:
            removeSecurityProxy(branch).private = True
        if stacked_on is not None:
            removeSecurityProxy(branch).stacked_on = stacked_on
        if reviewer is not None:
            removeSecurityProxy(branch).reviewer = reviewer
        return branch

    def makePackageBranch(self, sourcepackage=None, distroseries=None,
                          sourcepackagename=None, **kwargs):
        """Make a package branch on an arbitrary package.

        See `makeBranch` for more information on arguments.

        You can pass in either `sourcepackage` or one or both of
        `distroseries` and `sourcepackagename`, but not combinations or all of
        them.
        """
        assert not(sourcepackage is not None and distroseries is not None), (
            "Don't pass in both sourcepackage and distroseries")
        assert not(sourcepackage is not None
                   and sourcepackagename is not None), (
            "Don't pass in both sourcepackage and sourcepackagename")
        if sourcepackage is None:
            sourcepackage = self.makeSourcePackage(
                sourcepackagename=sourcepackagename,
                distroseries=distroseries)
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

    def makeBranchTargetBranch(self, target, branch_type=BranchType.HOSTED,
                               name=None, owner=None, creator=None):
        """Create a branch in a BranchTarget."""
        if name is None:
            name = self.getUniqueString('branch')
        if owner is None:
            owner = self.makePerson()
        if creator is None:
            creator = owner
        namespace = target.getNamespace(owner)
        return namespace.createBranch(branch_type, name, creator)

    def enableDefaultStackingForProduct(self, product, branch=None):
        """Give 'product' a default stacked-on branch.

        :param product: The product to give a default stacked-on branch to.
        :param branch: The branch that should be the default stacked-on
            branch.  If not supplied, a fresh branch will be created.
        """
        if branch is None:
            branch = self.makeBranch(product=product)
        # We just remove the security proxies to be able to change the objects
        # here.
        removeSecurityProxy(branch).branchChanged(
            '', 'rev1', None, None, None)
        naked_series = removeSecurityProxy(product.development_focus)
        naked_series.branch = branch
        return branch

    def enableDefaultStackingForPackage(self, package, branch):
        """Give 'package' a default stacked-on branch.

        :param package: The package to give a default stacked-on branch to.
        :param branch: The branch that should be the default stacked-on
            branch.
        """
        # We just remove the security proxies to be able to change the branch
        # here.
        removeSecurityProxy(branch).branchChanged(
            '', 'rev1', None, None, None)
        ubuntu_branches = getUtility(ILaunchpadCelebrities).ubuntu_branches
        run_with_login(
            ubuntu_branches.teamowner,
            package.development_version.setBranch,
            PackagePublishingPocket.RELEASE,
            branch,
            ubuntu_branches.teamowner)
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
                                set_state=None, prerequisite_branch=None,
                                product=None, review_diff=None,
                                initial_comment=None, source_branch=None,
                                preview_diff=None, date_created=None,
                                description=None):
        """Create a proposal to merge based on anonymous branches."""
        if target_branch is not None:
            target = target_branch.target
        elif source_branch is not None:
            target = source_branch.target
        elif prerequisite_branch is not None:
            target = prerequisite_branch.target
        else:
            # Create a target product branch, and use that target.  This is
            # needed to make sure we get a branch target that has the needed
            # security proxy.
            target_branch = self.makeProductBranch(product)
            target = target_branch.target

        # Fall back to initial_comment for description.
        if description is None:
            description = initial_comment

        if target_branch is None:
            target_branch = self.makeBranchTargetBranch(target)
        if source_branch is None:
            source_branch = self.makeBranchTargetBranch(target)
        if registrant is None:
            registrant = self.makePerson()
        proposal = source_branch.addLandingTarget(
            registrant, target_branch,
            prerequisite_branch=prerequisite_branch, review_diff=review_diff,
            description=description, date_created=date_created)

        unsafe_proposal = removeSecurityProxy(proposal)
        if preview_diff is not None:
            unsafe_proposal.preview_diff = preview_diff
        if (set_state is None or
            set_state == BranchMergeProposalStatus.WORK_IN_PROGRESS):
            # The initial state is work in progress, so do nothing.
            pass
        elif set_state == BranchMergeProposalStatus.NEEDS_REVIEW:
            unsafe_proposal.requestReview()
        elif set_state == BranchMergeProposalStatus.CODE_APPROVED:
            unsafe_proposal.approveBranch(
                proposal.target_branch.owner, 'some_revision')
        elif set_state == BranchMergeProposalStatus.REJECTED:
            unsafe_proposal.rejectBranch(
                proposal.target_branch.owner, 'some_revision')
        elif set_state == BranchMergeProposalStatus.MERGED:
            unsafe_proposal.markAsMerged()
        elif set_state == BranchMergeProposalStatus.MERGE_FAILED:
            unsafe_proposal.setStatus(set_state, proposal.target_branch.owner)
        elif set_state == BranchMergeProposalStatus.QUEUED:
            unsafe_proposal.commit_message = self.getUniqueString(
                'commit message')
            unsafe_proposal.enqueue(
                proposal.target_branch.owner, 'some_revision')
        elif set_state == BranchMergeProposalStatus.SUPERSEDED:
            unsafe_proposal.resubmit(proposal.registrant)
        else:
            raise AssertionError('Unknown status: %s' % set_state)

        return proposal

    def makeBranchSubscription(self, branch=None, person=None,
                               subscribed_by=None):
        """Create a BranchSubscription.

        :param branch_title: The title to use for the created Branch
        :param person_displayname: The displayname for the created Person
        """
        if branch is None:
            branch = self.makeBranch()
        if person is None:
            person = self.makePerson()
        if subscribed_by is None:
            subscribed_by = person
        return branch.subscribe(person,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.NOEMAIL, subscribed_by)

    def makeDiff(self, diff_text=DIFF):
        return ProxyFactory(
            Diff.fromFile(StringIO(diff_text), len(diff_text)))

    def makePreviewDiff(self, conflicts=u''):
        diff = self.makeDiff()
        bmp = self.makeBranchMergeProposal()
        preview_diff = PreviewDiff()
        preview_diff.branch_merge_proposal = bmp
        preview_diff.conflicts = conflicts
        preview_diff.diff = diff
        preview_diff.source_revision_id = self.getUniqueUnicode()
        preview_diff.target_revision_id = self.getUniqueUnicode()
        return preview_diff

    def makeStaticDiff(self):
        return StaticDiff.acquireFromText(
            self.getUniqueUnicode(), self.getUniqueUnicode(),
            self.getUniqueString())

    def makeRevision(self, author=None, revision_date=None, parent_ids=None,
                     rev_id=None, log_body=None, date_created=None):
        """Create a single `Revision`."""
        if author is None:
            author = self.getUniqueString('author')
        elif IPerson.providedBy(author):
            author = author.preferredemail.email
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
            parent_ids=parent_ids, properties={},
            _date_created=date_created)

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
                revision_id=self.getUniqueString('revision-id'),
                log_body=self.getUniqueString('log-body'),
                revision_date=date_generator.next(),
                revision_author=author,
                parent_ids=parent_ids,
                properties={})
            sequence += 1
            branch.createBranchRevision(sequence, revision)
            parent = revision
            parent_ids = [parent.revision_id]
        if branch.branch_type not in (BranchType.REMOTE, BranchType.HOSTED):
            branch.startMirroring()
        removeSecurityProxy(branch).branchChanged(
            '', parent.revision_id, None, None, None)
        branch.updateScannedDetails(parent, sequence)

    def makeBranchRevision(self, branch, revision_id, sequence=None):
        revision = self.makeRevision(rev_id=revision_id)
        return branch.createBranchRevision(sequence, revision)

    def makeBug(self, product=None, owner=None, bug_watch_url=None,
                private=False, date_closed=None, title=None,
                date_created=None, description=None, comment=None,
                status=None):
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
        if comment is None:
            comment = self.getUniqueString()
        create_bug_params = CreateBugParams(
            owner, title, comment=comment, private=private,
            datecreated=date_created, description=description,
            status=status)
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

    def makeBugTask(self, bug=None, target=None, owner=None):
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

        if owner is None:
            owner = self.makePerson()

        if IProductSeries.providedBy(target):
            # We can't have a series task without a distribution task.
            self.makeBugTask(bug, target.product)
        if IDistroSeries.providedBy(target):
            # We can't have a series task without a distribution task.
            self.makeBugTask(bug, target.distribution)
        if ISourcePackage.providedBy(target):
            distribution_package = target.distribution.getSourcePackage(
                target.sourcepackagename)
            # We can't have a series task without a distribution task.
            self.makeBugTask(bug, distribution_package)

        return removeSecurityProxy(bug).addTask(owner, target)

    def makeBugTracker(self, base_url=None, bugtrackertype=None):
        """Make a new bug tracker."""
        owner = self.makePerson()

        if base_url is None:
            base_url = 'http://%s.example.com/' % self.getUniqueString()
        if bugtrackertype is None:
            bugtrackertype = BugTrackerType.BUGZILLA

        return getUtility(IBugTrackerSet).ensureBugTracker(
            base_url, owner, bugtrackertype)

    def makeBugWatch(self, remote_bug=None, bugtracker=None, bug=None,
                     owner=None, bug_task=None):
        """Make a new bug watch."""
        if remote_bug is None:
            remote_bug = self.getUniqueInteger()

        if bugtracker is None:
            bugtracker = self.makeBugTracker()

        if bug_task is not None:
            # If someone passes a value for bug *and* a value for
            # bug_task then the bug value will get clobbered, but that
            # doesn't matter since the bug should be the one that the
            # bug task belongs to anyway (unless they're having a crazy
            # moment, in which case we're saving them from themselves).
            bug = bug_task.bug
        elif bug is None:
            bug = self.makeBug()

        if owner is None:
            owner = self.makePerson()

        bug_watch = getUtility(IBugWatchSet).createBugWatch(
            bug, owner, bugtracker, str(remote_bug))
        if bug_task is not None:
            bug_task.bugwatch = bug_watch

        # You need to be an admin to set next_check on a BugWatch.
        def set_next_check(bug_watch):
            bug_watch.next_check = datetime.now(pytz.timezone('UTC'))

        person = getUtility(IPersonSet).getByName('name16')
        run_with_login(person, set_next_check, bug_watch)
        return bug_watch

    def makeBugComment(self, bug=None, owner=None, subject=None, body=None,
                       bug_watch=None):
        """Create and return a new bug comment.

        :param bug: An `IBug` or a bug ID or name, or None, in which
            case a new bug is created.
        :param owner: An `IPerson`, or None, in which case a new
            person is created.
        :param subject: An `IMessage` or a string, or None, in which
            case a new message will be generated.
        :param body: An `IMessage` or a string, or None, in which
            case a new message will be generated.
        :param bug_watch: An `IBugWatch`, which will be used to set the
            new comment's bugwatch attribute.
        :return: An `IBugMessage`.
        """
        if bug is None:
            bug = self.makeBug()
        elif isinstance(bug, (int, long, basestring)):
            bug = getUtility(IBugSet).getByNameOrID(str(bug))
        if owner is None:
            owner = self.makePerson()
        if subject is None:
            subject = self.getUniqueString()
        if body is None:
            body = self.getUniqueString()
        return bug.newMessage(owner=owner, subject=subject,
                              content=body, parent=None, bugwatch=bug_watch,
                              remote_comment_id=None)

    def makeBugAttachment(self, bug=None, owner=None, data=None,
                          comment=None, filename=None, content_type=None,
                          description=None, is_patch=_DEFAULT):
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
        :param description: The description of the attachment.
        :param is_patch: If true, this attachment is a patch.
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
        if description is None:
            description = self.getUniqueString()
        if comment is None:
            comment = self.getUniqueString()
        if filename is None:
            filename = self.getUniqueString()
        # If the default value of is_patch when creating a new
        # BugAttachment should ever change, we don't want to interfere
        # with that.  So, we only override it if our caller explicitly
        # passed it.
        other_params = {}
        if is_patch is not _DEFAULT:
            other_params['is_patch'] = is_patch
        return bug.addAttachment(
            owner, data, comment, filename, content_type=content_type,
            description=description, **other_params)

    def makeSignedMessage(self, msgid=None, body=None, subject=None,
            attachment_contents=None, force_transfer_encoding=False,
            email_address=None, signing_context=None):
        """Return an ISignedMessage.

        :param msgid: An rfc2822 message-id.
        :param body: The body of the message.
        :param attachment_contents: The contents of an attachment.
        :param force_transfer_encoding: If True, ensure a transfer encoding is
            used.
        :param email_address: The address the mail is from.
        :param signing_context: A GPGSigningContext instance containing the
            gpg key to sign with.  If None, the message is unsigned.  The
            context also contains the password and gpg signing mode.
        """
        mail = SignedMessage()
        if email_address is None:
            person = self.makePerson()
            email_address = person.preferredemail.email
        mail['From'] = email_address
        mail['To'] = self.makePerson().preferredemail.email
        if subject is None:
            subject = self.getUniqueString('subject')
        mail['Subject'] = subject
        if msgid is None:
            msgid = self.makeUniqueRFC822MsgId()
        if body is None:
            body = self.getUniqueString('body')
        charset = 'ascii'
        try:
            body = body.encode(charset)
        except UnicodeEncodeError:
            charset = 'utf-8'
            body = body.encode(charset)
        mail['Message-Id'] = msgid
        mail['Date'] = formatdate()
        if signing_context is not None:
            gpghandler = getUtility(IGPGHandler)
            body = gpghandler.signContent(
                body, signing_context.fingerprint,
                signing_context.password, signing_context.mode)
            assert body is not None
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
        body_part.set_charset(charset)
        mail.parsed_string = mail.as_string()
        return mail

    def makeSpecification(self, product=None, title=None, distribution=None):
        """Create and return a new, arbitrary Blueprint.

        :param product: The product to make the blueprint on.  If one is
            not specified, an arbitrary product is created.
        """
        if distribution is None and product is None:
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
            product=product,
            distribution=distribution)

    def makeQuestion(self, target=None, title=None):
        """Create and return a new, arbitrary Question.

        :param target: The IQuestionTarget to make the question on. If one is
            not specified, an arbitrary product is created.
        :param title: The question title. If one is not provided, an
            arbitrary title is created.
        """
        if target is None:
            target = self.makeProduct()
        if title is None:
            title = self.getUniqueString('title')
        return target.newQuestion(
            owner=target.owner, title=title, description='description')

    def makeFAQ(self, target=None, title=None):
        """Create and return a new, arbitrary FAQ.

        :param target: The IFAQTarget to make the FAQ on. If one is
            not specified, an arbitrary product is created.
        :param title: The FAQ title. If one is not provided, an
            arbitrary title is created.
        """
        if target is None:
            target = self.makeProduct()
        if title is None:
            title = self.getUniqueString('title')
        return target.newFAQ(
            owner=target.owner, title=title, content='content')

    def makePackageCodeImport(self, sourcepackage=None, **kwargs):
        """Make a code import targetting a sourcepackage."""
        if sourcepackage is None:
            sourcepackage = self.makeSourcePackage()
        target = IBranchTarget(sourcepackage)
        return self.makeCodeImport(target=target, **kwargs)

    def makeProductCodeImport(self, product=None, **kwargs):
        """Make a code import targetting a product."""
        if product is None:
            product = self.makeProduct()
        target = IBranchTarget(product)
        return self.makeCodeImport(target=target, **kwargs)

    def makeCodeImport(self, svn_branch_url=None, cvs_root=None,
                       cvs_module=None, target=None, branch_name=None,
                       git_repo_url=None, hg_repo_url=None, registrant=None,
                       rcs_type=None, review_status=None):
        """Create and return a new, arbitrary code import.

        The type of code import will be inferred from the source details
        passed in, but defaults to a Subversion import from an arbitrary
        unique URL.
        """
        if (svn_branch_url is cvs_root is cvs_module is git_repo_url is
            hg_repo_url is None):
            svn_branch_url = self.getUniqueURL()

        if target is None:
            target = IBranchTarget(self.makeProduct())
        if branch_name is None:
            branch_name = self.getUniqueString('name')
        if registrant is None:
            registrant = self.makePerson()

        code_import_set = getUtility(ICodeImportSet)
        if svn_branch_url is not None:
            if rcs_type is None:
                rcs_type = RevisionControlSystems.SVN
            else:
                assert rcs_type in (RevisionControlSystems.SVN,
                                    RevisionControlSystems.BZR_SVN)
            code_import = code_import_set.new(
                registrant, target, branch_name, rcs_type=rcs_type,
                url=svn_branch_url)
        elif git_repo_url is not None:
            assert rcs_type in (None, RevisionControlSystems.GIT)
            code_import = code_import_set.new(
                registrant, target, branch_name,
                rcs_type=RevisionControlSystems.GIT,
                url=git_repo_url)
        elif hg_repo_url is not None:
            code_import = code_import_set.new(
                registrant, target, branch_name,
                rcs_type=RevisionControlSystems.HG,
                url=hg_repo_url)
        else:
            assert rcs_type in (None, RevisionControlSystems.CVS)
            code_import = code_import_set.new(
                registrant, target, branch_name,
                rcs_type=RevisionControlSystems.CVS,
                cvs_root=cvs_root, cvs_module=cvs_module)
        if review_status:
            removeSecurityProxy(code_import).review_status = review_status
        return code_import

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

    def makeCodeReviewVoteReference(self):
        bmp = removeSecurityProxy(self.makeBranchMergeProposal())
        candidate = self.makePerson()
        return bmp.nominateReviewer(candidate, bmp.registrant)

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

    def makeSeries(self, branch=None, name=None, product=None):
        """Create a new, arbitrary ProductSeries.

        :param branch: If supplied, the branch to set as
            ProductSeries.branch.
        :param name: If supplied, the name of the series.
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
            product.owner, name, self.getUniqueString(), branch)
        if branch is not None:
            series.branch = branch
        syncUpdate(series)
        return series

    def makeLanguage(self, language_code=None, name=None):
        """Makes a language given the language_code and name."""
        if language_code is None:
            language_code = self.getUniqueString('lang')
        if name is None:
            name = "Language %s" % language_code

        language_set = getUtility(ILanguageSet)
        return language_set.createLanguage(language_code, name)

    def makeLibraryFileAlias(self, filename=None, content=None,
                             content_type='text/plain', restricted=False,
                             expires=None):
        """Make a library file, and return the alias."""
        if filename is None:
            filename = self.getUniqueString('filename')
        if content is None:
            content = self.getUniqueString()
        library_file_alias_set = getUtility(ILibraryFileAliasSet)
        library_file_alias = library_file_alias_set.create(
            filename, len(content), StringIO(content), content_type,
            expires=expires, restricted=restricted)
        return library_file_alias

    def makeDistribution(self, name=None, displayname=None, owner=None,
                         members=None, title=None, aliases=None):
        """Make a new distribution."""
        if name is None:
            name = self.getUniqueString()
        if displayname is None:
            displayname = self.getUniqueString()
        if title is None:
            title = self.getUniqueString()
        description = self.getUniqueString()
        summary = self.getUniqueString()
        domainname = self.getUniqueString()
        if owner is None:
            owner = self.makePerson()
        if members is None:
            members = self.makeTeam(owner)
        distro = getUtility(IDistributionSet).new(
            name, displayname, title, description, summary, domainname,
            members, owner)
        if aliases is not None:
            removeSecurityProxy(distro).setAliases(aliases)
        return distro

    def makeDistroRelease(self, distribution=None, version=None,
                          status=SeriesStatus.DEVELOPMENT,
                          parent_series=None, name=None, displayname=None):
        """Make a new distro release."""
        if distribution is None:
            distribution = self.makeDistribution()
        if name is None:
            name = self.getUniqueString()
        if displayname is None:
            displayname = name.capitalize()
        if version is None:
            version = "%s.0" % self.getUniqueInteger()

        # We don't want to login() as the person used to create the product,
        # so we remove the security proxy before creating the series.
        naked_distribution = removeSecurityProxy(distribution)
        series = naked_distribution.newSeries(
            version=version,
            name=name,
            displayname=displayname,
            title=self.getUniqueString(), summary=self.getUniqueString(),
            description=self.getUniqueString(),
            parent_series=parent_series, owner=distribution.owner)
        series.status = status
        return ProxyFactory(series)

    # Most people think of distro releases as distro series.
    makeDistroSeries = makeDistroRelease

    def makeDistroArchSeries(self, distroseries=None,
                             architecturetag=None, processorfamily=None,
                             official=True, owner=None,
                             supports_virtualized=False):
        """Create a new distroarchseries"""

        if distroseries is None:
            distroseries = self.makeDistroRelease()
        if processorfamily is None:
            processorfamily = ProcessorFamilySet().getByName('powerpc')
        if owner is None:
            owner = self.makePerson()
        if architecturetag is None:
            architecturetag = self.getUniqueString('arch')
        return distroseries.newArch(
            architecturetag, processorfamily, official, owner,
            supports_virtualized)

    def makeComponent(self, name=None):
        """Make a new `IComponent`."""
        if name is None:
            name = self.getUniqueString()
        return getUtility(IComponentSet).ensure(name)

    def makeArchive(self, distribution=None, owner=None, name=None,
                    purpose=None, enabled=True, private=False,
                    virtualized=True, description=None, displayname=None):
        """Create and return a new arbitrary archive.

        :param distribution: Supply IDistribution, defaults to a new one
            made with makeDistribution() for non-PPAs and ubuntu for PPAs.
        :param owner: Supper IPerson, defaults to a new one made with
            makePerson().
        :param name: Name of the archive, defaults to a random string.
        :param purpose: Supply ArchivePurpose, defaults to PPA.
        :param enabled: Whether the archive is enabled.
        :param private: Whether the archive is created private.
        :param virtualized: Whether the archive is virtualized.
        :param description: A description of the archive.
        """
        if purpose is None:
            purpose = ArchivePurpose.PPA
        if distribution is None:
            # See bug #568769
            if purpose == ArchivePurpose.PPA:
                distribution = getUtility(ILaunchpadCelebrities).ubuntu
            else:
                distribution = self.makeDistribution()
        if owner is None:
            owner = self.makePerson()
        if name is None:
            if purpose != ArchivePurpose.PPA:
                name = default_name_by_purpose.get(purpose)
            if name is None:
                name = self.getUniqueString()

        # Making a distribution makes an archive, and there can be only one
        # per distribution.
        if purpose == ArchivePurpose.PRIMARY:
            return distribution.main_archive

        archive = getUtility(IArchiveSet).new(
            owner=owner, purpose=purpose,
            distribution=distribution, name=name, displayname=displayname,
            enabled=enabled, require_virtualized=virtualized,
            description=description)

        if private:
            naked_archive = removeSecurityProxy(archive)
            naked_archive.private = True
            naked_archive.buildd_secret = "sekrit"

        return archive

    def makeBuilder(self, processor=None, url=None, name=None, title=None,
                    description=None, owner=None, active=True,
                    virtualized=True, vm_host=None, manual=False):
        """Make a new builder for i386 virtualized builds by default.

        Note: the builder returned will not be able to actually build -
        we currently have a build slave setup for 'bob' only in the
        test environment.
        See lib/canonical/buildd/tests/buildd-slave-test.conf
        """
        if processor is None:
            processor_fam = ProcessorFamilySet().getByName('x86')
            processor = processor_fam.processors[0]
        if url is None:
            url = 'http://%s:8221/' % self.getUniqueString()
        if name is None:
            name = self.getUniqueString()
        if title is None:
            title = self.getUniqueString()
        if description is None:
            description = self.getUniqueString()
        if owner is None:
            owner = self.makePerson()

        return getUtility(IBuilderSet).new(
            processor, url, name, title, description, owner, active,
            virtualized, vm_host, manual=manual)

    def makeRecipeText(self, *branches):
        if len(branches) == 0:
            branches = (self.makeAnyBranch(), )
        base_branch = branches[0]
        other_branches = branches[1:]
        text = MINIMAL_RECIPE_TEXT % base_branch.bzr_identity
        for i, branch in enumerate(other_branches):
            text += 'merge dummy-%s %s\n' % (i, branch.bzr_identity)
        return text

    def makeRecipe(self, *branches):
        """Make a builder recipe that references `branches`.

        If no branches are passed, return a recipe text that references an
        arbitrary branch.
        """
        from bzrlib.plugins.builder.recipe import RecipeParser
        parser = RecipeParser(self.makeRecipeText(*branches))
        return parser.parse()

    def makeSourcePackageRecipeDistroseries(self, name="warty"):
        """Return a supported Distroseries to use with Source Package Recipes.

        Ew.  This uses sampledata currently, which is the ONLY reason this
        method exists: it gives us a migration path away from sampledata.
        """
        ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        return ubuntu.getSeries(name)

    def makeSourcePackageRecipe(self, registrant=None, owner=None,
                                distroseries=None, name=None,
                                description=None, branches=(),
                                build_daily=False, daily_build_archive=None,
                                is_stale=None):
        """Make a `SourcePackageRecipe`."""
        if registrant is None:
            registrant = self.makePerson()
        if owner is None:
            owner = self.makePerson()
        if distroseries is None:
            distroseries = self.makeSourcePackageRecipeDistroseries()

        if name is None:
            name = self.getUniqueString().decode('utf8')
        if description is None:
            description = self.getUniqueString().decode('utf8')
        if daily_build_archive is None:
            daily_build_archive = self.makeArchive(
                distribution=distroseries.distribution, owner=owner)
        recipe = self.makeRecipe(*branches)
        source_package_recipe = getUtility(ISourcePackageRecipeSource).new(
            registrant, owner, name, recipe, description, [distroseries],
            daily_build_archive, build_daily)
        if is_stale is not None:
            removeSecurityProxy(source_package_recipe).is_stale = is_stale
        IStore(source_package_recipe).flush()
        return source_package_recipe

    def makeSourcePackageRecipeBuild(self, sourcepackage=None, recipe=None,
                                     requester=None, archive=None,
                                     sourcename=None, distroseries=None,
                                     pocket=None, date_created=None,
                                     status=BuildStatus.NEEDSBUILD,
                                     duration=None):
        """Make a new SourcePackageRecipeBuild."""
        if recipe is None:
            recipe = self.makeSourcePackageRecipe(name=sourcename)
        if archive is None:
            archive = self.makeArchive()
        if distroseries is None:
            distroseries = self.makeDistroSeries(
                distribution=archive.distribution)
        if requester is None:
            requester = self.makePerson()
        spr_build = getUtility(ISourcePackageRecipeBuildSource).new(
            distroseries=distroseries,
            recipe=recipe,
            archive=archive,
            requester=requester,
            pocket=pocket,
            date_created=date_created)
        removeSecurityProxy(spr_build).status = status
        if duration is not None:
            naked_sprb = removeSecurityProxy(spr_build)
            if naked_sprb.date_started is None:
                naked_sprb.date_started = spr_build.date_created
            naked_sprb.date_finished = naked_sprb.date_started + duration
        return spr_build

    def makeSourcePackageRecipeBuildJob(
        self, score=9876, virtualized=True, estimated_duration=64,
        sourcename=None, recipe_build=None):
        """Create a `SourcePackageRecipeBuildJob` and a `BuildQueue` for
        testing."""
        if recipe_build is None:
            recipe_build = self.makeSourcePackageRecipeBuild(
                sourcename=sourcename)
        recipe_build_job = recipe_build.makeJob()

        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        bq = BuildQueue(
            job=recipe_build_job.job, lastscore=score,
            job_type=BuildFarmJobType.RECIPEBRANCHBUILD,
            estimated_duration = timedelta(seconds=estimated_duration),
            virtualized=virtualized)
        store.add(bq)
        return bq

    def makeDscFile(self, tempdir_path=None):
        """Make a DscFile.

        :param tempdir_path: Path to a temporary directory to use.  If not
            supplied, a temp directory will be created.
        """
        filename = 'ed_0.2-20.dsc'
        contexts = []
        if tempdir_path is None:
            contexts.append(temp_dir())
        # Use nested so temp_dir is an optional context.
        with nested(*contexts) as result:
            if tempdir_path is None:
                tempdir_path = result[0]
            fullpath = os.path.join(tempdir_path, filename)
            with open(fullpath, 'w') as dsc_file:
                dsc_file.write(dedent("""\
                Format: 1.0
                Source: ed
                Version: 0.2-20
                Binary: ed
                Maintainer: James Troup <james@nocrew.org>
                Architecture: any
                Standards-Version: 3.5.8.0
                Build-Depends: dpatch
                Files:
                 ddd57463774cae9b50e70cd51221281b 185913 ed_0.2.orig.tar.gz
                 f9e1e5f13725f581919e9bfd62272a05 8506 ed_0.2-20.diff.gz
                """))

            class Changes:
                architectures = ['source']
            logger = QuietFakeLogger()
            policy = BuildDaemonUploadPolicy()
            policy.distroseries = self.makeDistroSeries()
            policy.archive = self.makeArchive()
            policy.distro = policy.distroseries.distribution
            dsc_file = DSCFile(fullpath, 'digest', 0, 'main/editors',
                'priority', 'package', 'version', Changes, policy, logger)
            list(dsc_file.verify())
        return dsc_file

    def makeTranslationTemplatesBuildJob(self, branch=None):
        """Make a new `TranslationTemplatesBuildJob`.

        :param branch: The branch that the job should be for.  If none
            is given, one will be created.
        """
        if branch is None:
            branch = self.makeBranch()

        jobset = getUtility(ITranslationTemplatesBuildJobSource)
        return jobset.create(branch)

    def makePOTemplate(self, productseries=None, distroseries=None,
                       sourcepackagename=None, owner=None, name=None,
                       translation_domain=None, path=None):
        """Make a new translation template."""
        if productseries is None and distroseries is None:
            # No context for this template; set up a productseries.
            productseries = self.makeProductSeries(owner=owner)
            # Make it use Translations, otherwise there's little point
            # to us creating a template for it.
            removeSecurityProxy(productseries).product.official_rosetta = True
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

        if path is None:
            path = 'messages.pot'

        return subset.new(name, translation_domain, path, owner)

    def makePOTemplateAndPOFiles(self, language_codes, **kwargs):
        """Create a POTemplate and associated POFiles.

        Create a POTemplate for the given distroseries/sourcepackagename or
        productseries and create a POFile for each language. Returns the
        template.
        """
        template = self.makePOTemplate(**kwargs)
        for language_code in language_codes:
            self.makePOFile(language_code, template, template.owner)
        return template

    def makePOFile(self, language_code, potemplate=None, owner=None,
                   create_sharing=False, variant=None):
        """Make a new translation file."""
        if potemplate is None:
            potemplate = self.makePOTemplate(owner=owner)
        pofile = potemplate.newPOFile(language_code,
                                      create_sharing=create_sharing)
        if variant is not None:
            removeSecurityProxy(pofile).variant = variant
        return pofile

    def makePOTMsgSet(self, potemplate, singular=None, plural=None,
                      context=None, sequence=0):
        """Make a new `POTMsgSet` in the given template."""
        if singular is None and plural is None:
            singular = self.getUniqueString()
        potmsgset = potemplate.createMessageSetFromText(
            singular, plural, context, sequence)
        removeSecurityProxy(potmsgset).sync()
        return potmsgset

    def makeTranslationMessage(self, pofile=None, potmsgset=None,
                               translator=None, suggestion=False,
                               reviewer=None, translations=None,
                               lock_timestamp=None, date_updated=None,
                               is_imported=False, force_shared=False,
                               force_diverged=False):
        """Make a new `TranslationMessage` in the given PO file."""
        if pofile is None:
            pofile = self.makePOFile('sr')
        if potmsgset is None:
            potmsgset = self.makePOTMsgSet(pofile.potemplate)
            potmsgset.setSequence(pofile.potemplate, 1)
        if translator is None:
            translator = self.makePerson()
        if translations is None:
            translations = [self.getUniqueString()]
        translation_message = potmsgset.updateTranslation(
            pofile, translator, translations, is_imported=is_imported,
            lock_timestamp=lock_timestamp, force_suggestion=suggestion,
            force_shared=force_shared, force_diverged=force_diverged)
        if date_updated is not None:
            naked_translation_message = removeSecurityProxy(
                translation_message)
            naked_translation_message.date_created = date_updated
            if translation_message.reviewer is not None:
                naked_translation_message.date_reviewed = date_updated
            naked_translation_message.sync()
        return translation_message

    def makeSharedTranslationMessage(self, pofile=None, potmsgset=None,
                                     translator=None, suggestion=False,
                                     reviewer=None, translations=None,
                                     date_updated=None, is_imported=False):
        translation_message = self.makeTranslationMessage(
            pofile=pofile, potmsgset=potmsgset, translator=translator,
            suggestion=suggestion, reviewer=reviewer, is_imported=is_imported,
            translations=translations, date_updated=date_updated,
            force_shared=True)
        return translation_message

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

    def makeTranslationImportQueueEntry(self, path=None, productseries=None,
                                        distroseries=None,
                                        sourcepackagename=None,
                                        potemplate=None, content=None,
                                        uploader=None, pofile=None,
                                        format=None, status=None):
        """Create a `TranslationImportQueueEntry`."""
        if path is None:
            path = self.getUniqueString() + '.pot'

        for_distro = not (distroseries is None and sourcepackagename is None)
        for_project = productseries is not None
        has_template = (potemplate is not None)
        if has_template and not for_distro and not for_project:
            # Copy target from template.
            distroseries = potemplate.distroseries
            sourcepackagename = potemplate.sourcepackagename
            productseries = potemplate.productseries

        if sourcepackagename is None and distroseries is None:
            if productseries is None:
                productseries = self.makeProductSeries()
        else:
            if sourcepackagename is None:
                sourcepackagename = self.makeSourcePackageName()
            if distroseries is None:
                distroseries = self.makeDistroSeries()

        if uploader is None:
            uploader = self.makePerson()

        if content is None:
            content = self.getUniqueString()
        content_reference = getUtility(ILibraryFileAliasSet).create(
            name=os.path.basename(path), size=len(content),
            file=StringIO(content), contentType='text/plain')

        if format is None:
            format = TranslationFileFormat.PO

        if status is None:
            status = RosettaImportStatus.NEEDS_REVIEW

        return TranslationImportQueueEntry(
            path=path, productseries=productseries, distroseries=distroseries,
            sourcepackagename=sourcepackagename, importer=uploader,
            content=content_reference, status=status, format=format,
            is_published=False)

    def makeMailingList(self, team, owner):
        """Create a mailing list for the team."""
        team_list = getUtility(IMailingListSet).new(team, owner)
        team_list.startConstructing()
        team_list.transitionToStatus(MailingListStatus.ACTIVE)
        return team_list

    def makeTeamAndMailingList(
        self, team_name, owner_name,
        visibility=None,
        subscription_policy=TeamSubscriptionPolicy.OPEN):
        """Make a new active mailing list for the named team.

        :param team_name: The new team's name.
        :type team_name: string
        :param owner_name: The name of the team's owner.
        :type owner: string
        :param visibility: The team's visibility. If it's None, the default
            (public) will be used.
        :type visibility: `PersonVisibility`
        :param subscription_policy: The subscription policy of the team.
        :type subscription_policy: `TeamSubscriptionPolicy`
        :return: The new team and mailing list.
        :rtype: (`ITeam`, `IMailingList`)
        """
        owner = getUtility(IPersonSet).getByName(owner_name)
        display_name = SPACE.join(
            word.capitalize() for word in team_name.split('-'))
        team = getUtility(IPersonSet).getByName(team_name)
        if team is None:
            team = self.makeTeam(
                owner, displayname=display_name, name=team_name,
                visibility=visibility,
                subscription_policy=subscription_policy)
        team_list = self.makeMailingList(team, owner)
        return team, team_list

    def makeMirrorProbeRecord(self, mirror):
        """Create a probe record for a mirror of a distribution."""
        log_file = StringIO()
        log_file.write("Fake probe, nothing useful here.")
        log_file.seek(0)

        library_alias = getUtility(ILibraryFileAliasSet).create(
            name='foo', size=len(log_file.getvalue()),
            file=log_file, contentType='text/plain')

        proberecord = mirror.newProbeRecord(library_alias)
        return proberecord

    def makeMirror(self, distribution, displayname, country=None,
                   http_url=None, ftp_url=None, rsync_url=None,
                   official_candidate=False):
        """Create a mirror for the distribution."""
        # If no URL is specified create an HTTP URL.
        if http_url is None and ftp_url is None and rsync_url is None:
            http_url = self.getUniqueURL()
        # If no country is given use Argentina.
        if country is None:
            country = getUtility(ICountrySet)['AR']

        mirror = distribution.newMirror(
            owner=distribution.owner,
            speed=MirrorSpeed.S256K,
            country=country,
            content=MirrorContent.ARCHIVE,
            displayname=displayname,
            description=None,
            http_base_url=http_url,
            ftp_base_url=ftp_url,
            rsync_base_url=rsync_url,
            official_candidate=official_candidate)
        return mirror

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

    def getOrMakeSourcePackageName(self, name=None):
        """Get an existing`ISourcePackageName` or make a new one.

        This method encapsulates getOrCreateByName so that tests can be kept
        free of the getUtility(ISourcePackageNameSet) noise.
        """
        if name is None:
            return self.makeSourcePackageName()
        return getUtility(ISourcePackageNameSet).getOrCreateByName(name)

    def makeSourcePackage(self, sourcepackagename=None, distroseries=None):
        """Make an `ISourcePackage`."""
        # Make sure we have a real sourcepackagename object.
        if (sourcepackagename is None or
            isinstance(sourcepackagename, basestring)):
            sourcepackagename = self.getOrMakeSourcePackageName(
                sourcepackagename)
        if distroseries is None:
            distroseries = self.makeDistroRelease()
        return distroseries.getSourcePackage(sourcepackagename)

    def getAnySourcePackageUrgency(self):
        return SourcePackageUrgency.MEDIUM

    def makeSourcePackageRelease(self, archive=None, sourcepackagename=None,
                                 distroseries=None, maintainer=None,
                                 creator=None, component=None,
                                 section_name=None, urgency=None,
                                 version=None, builddepends=None,
                                 builddependsindep=None,
                                 build_conflicts=None,
                                 build_conflicts_indep=None,
                                 architecturehintlist='all',
                                 dsc_maintainer_rfc822=None,
                                 dsc_standards_version='3.6.2',
                                 dsc_format='1.0', dsc_binaries='foo-bin',
                                 date_uploaded=UTC_NOW,
                                 source_package_recipe_build=None,
                                 dscsigningkey=None):
        """Make a `SourcePackageRelease`."""
        if distroseries is None:
            if source_package_recipe_build is not None:
                distroseries = source_package_recipe_build.distroseries
            else:
                if archive is None:
                    distribution = None
                else:
                    distribution = archive.distribution
                distroseries = self.makeDistroRelease(
                    distribution=distribution)

        if archive is None:
            archive = self.makeArchive(
                distribution=distroseries.distribution,
                purpose=ArchivePurpose.PRIMARY)

        if sourcepackagename is None:
            sourcepackagename = self.makeSourcePackageName()

        if component is None:
            component = self.makeComponent()

        if urgency is None:
            urgency = self.getAnySourcePackageUrgency()

        section = self.makeSection(name=section_name)

        if maintainer is None:
            maintainer = self.makePerson()

        maintainer_email = '%s <%s>' % (
            maintainer.displayname,
            maintainer.preferredemail.email)

        if creator is None:
            creator = self.makePerson()

        if version is None:
            version = self.getUniqueString('version')

        return distroseries.createUploadedSourcePackageRelease(
            sourcepackagename=sourcepackagename,
            maintainer=maintainer,
            creator=creator,
            component=component,
            section=section,
            urgency=urgency,
            version=version,
            builddepends=builddepends,
            builddependsindep=builddependsindep,
            build_conflicts=build_conflicts,
            build_conflicts_indep=build_conflicts_indep,
            architecturehintlist=architecturehintlist,
            changelog=None,
            changelog_entry=None,
            dsc=None,
            copyright=self.getUniqueString(),
            dscsigningkey=dscsigningkey,
            dsc_maintainer_rfc822=maintainer_email,
            dsc_standards_version=dsc_standards_version,
            dsc_format=dsc_format,
            dsc_binaries=dsc_binaries,
            archive=archive,
            dateuploaded=date_uploaded,
            source_package_recipe_build=source_package_recipe_build)

    def makeSourcePackageReleaseFile(self, sourcepackagerelease=None,
                                     library_file=None, filetype=None):
        if sourcepackagerelease is None:
            sourcepackagerelease = self.makeSourcePackageRelease()
        if library_file is None:
            library_file = self.makeLibraryFileAlias()
        if filetype is None:
            filetype = SourcePackageFileType.DSC
        return ProxyFactory(
            SourcePackageReleaseFile(
                sourcepackagerelease=sourcepackagerelease,
                libraryfile=library_file, filetype=filetype))

    def makeBinaryPackageBuild(self, source_package_release=None,
            distroarchseries=None, archive=None, builder=None,
            status=None):
        """Create a BinaryPackageBuild.

        If archive is not supplied, the source_package_release is used
        to determine archive.
        :param source_package_release: The SourcePackageRelease this binary
            build uses as its source.
        :param distroarchseries: The DistroArchSeries to use.
        :param archive: The Archive to use.
        :param builder: An optional builder to assign.
        :param status: The BuildStatus for the build.
        """
        if archive is None:
            if source_package_release is None:
                archive = self.makeArchive()
            else:
                archive = source_package_release.upload_archive
        if source_package_release is None:
            multiverse = self.makeComponent(name='multiverse')
            source_package_release = self.makeSourcePackageRelease(
                archive, component=multiverse)
            self.makeSourcePackagePublishingHistory(
                distroseries=source_package_release.upload_distroseries,
                archive=archive, sourcepackagerelease=source_package_release)
        processor = self.makeProcessor()
        if distroarchseries is None:
            distroarchseries = self.makeDistroArchSeries(
                distroseries=source_package_release.upload_distroseries,
                processorfamily=processor.family)
        if status is None:
            status = BuildStatus.NEEDSBUILD
        binary_package_build = getUtility(IBinaryPackageBuildSet).new(
            source_package_release=source_package_release,
            processor=processor,
            distro_arch_series=distroarchseries,
            status=status,
            archive=archive,
            pocket=PackagePublishingPocket.RELEASE,
            date_created=self.getUniqueDate())
        naked_build = removeSecurityProxy(binary_package_build)
        naked_build.builder = builder
        binary_package_build_job = naked_build.makeJob()
        BuildQueue(
            job=binary_package_build_job.job,
            job_type=BuildFarmJobType.PACKAGEBUILD)
        return binary_package_build

    def makeSourcePackagePublishingHistory(self, sourcepackagename=None,
                                           distroseries=None, maintainer=None,
                                           creator=None, component=None,
                                           section_name=None,
                                           urgency=None, version=None,
                                           archive=None,
                                           builddepends=None,
                                           builddependsindep=None,
                                           build_conflicts=None,
                                           build_conflicts_indep=None,
                                           architecturehintlist='all',
                                           dateremoved=None,
                                           date_uploaded=UTC_NOW,
                                           pocket=None,
                                           status=None,
                                           scheduleddeletiondate=None,
                                           dsc_standards_version='3.6.2',
                                           dsc_format='1.0',
                                           dsc_binaries='foo-bin',
                                           sourcepackagerelease=None,
                                           ):
        """Make a `SourcePackagePublishingHistory`."""
        if distroseries is None:
            if archive is None:
                distribution = None
            else:
                distribution = archive.distribution
            distroseries = self.makeDistroRelease(distribution=distribution)

        if archive is None:
            archive = self.makeArchive(
                distribution=distroseries.distribution,
                purpose=ArchivePurpose.PRIMARY)

        if pocket is None:
            pocket = self.getAnyPocket()

        if status is None:
            status = PackagePublishingStatus.PENDING

        if sourcepackagerelease is None:
            sourcepackagerelease = self.makeSourcePackageRelease(
                archive=archive,
                sourcepackagename=sourcepackagename,
                distroseries=distroseries,
                maintainer=maintainer,
                creator=creator, component=component,
                section_name=section_name,
                urgency=urgency,
                version=version,
                builddepends=builddepends,
                builddependsindep=builddependsindep,
                build_conflicts=build_conflicts,
                build_conflicts_indep=build_conflicts_indep,
                architecturehintlist=architecturehintlist,
                dsc_standards_version=dsc_standards_version,
                dsc_format=dsc_format,
                dsc_binaries=dsc_binaries,
                date_uploaded=date_uploaded)

        spph = getUtility(IPublishingSet).newSourcePublication(
            archive, sourcepackagerelease, distroseries,
            sourcepackagerelease.component, sourcepackagerelease.section,
            pocket)

        naked_spph = removeSecurityProxy(spph)
        naked_spph.status = status
        naked_spph.datecreated = date_uploaded
        naked_spph.dateremoved = dateremoved
        naked_spph.scheduleddeletiondate = scheduleddeletiondate
        return spph

    def makeBinaryPackagePublishingHistory(self, binarypackagerelease=None,
                                           distroarchseries=None,
                                           component=None, section_name=None,
                                           priority=None, status=None,
                                           scheduleddeletiondate=None,
                                           dateremoved=None,
                                           pocket=None, archive=None):
        """Make a `BinaryPackagePublishingHistory`."""
        if distroarchseries is None:
            if archive is None:
                distribution = None
            else:
                distribution = archive.distribution
            distroseries = self.makeDistroSeries(distribution=distribution)
            distroarchseries = self.makeDistroArchSeries(
                distroseries=distroseries)

        if archive is None:
            archive = self.makeArchive(
                distribution=distroarchseries.distroseries.distribution,
                purpose=ArchivePurpose.PRIMARY)

        if pocket is None:
            pocket = self.getAnyPocket()

        if status is None:
            status = PackagePublishingStatus.PENDING

        if priority is None:
            priority = PackagePublishingPriority.OPTIONAL

        if binarypackagerelease is None:
            binarypackagerelease = self.makeBinaryPackageRelease(
                component=component,
                section_name=section_name,
                priority=priority)

        bpph = getUtility(IPublishingSet).newBinaryPublication(
            archive, binarypackagerelease, distroarchseries,
            binarypackagerelease.component, binarypackagerelease.section,
            priority, pocket)
        naked_bpph = removeSecurityProxy(bpph)
        naked_bpph.status = status
        naked_bpph.dateremoved = dateremoved
        naked_bpph.scheduleddeletiondate = scheduleddeletiondate
        naked_bpph.priority = priority
        return bpph

    def makeBinaryPackageName(self, name=None):
        if name is None:
            name = self.getUniqueString("binarypackage")
        return BinaryPackageName(name=name)

    def makeBinaryPackageFile(self, binarypackagerelease=None,
                              library_file=None, filetype=None):
        if binarypackagerelease is None:
            binarypackagerelease = self.makeBinaryPackageRelease()
        if library_file is None:
            library_file = self.makeLibraryFileAlias()
        if filetype is None:
            filetype = BinaryPackageFileType.DEB
        return ProxyFactory(BinaryPackageFile(
            binarypackagerelease=binarypackagerelease,
            libraryfile=library_file, filetype=filetype))

    def makeBinaryPackageRelease(self, binarypackagename=None,
                                 version=None, build=None,
                                 binpackageformat=None, component=None,
                                 section_name=None, priority=None,
                                 architecturespecific=False,
                                 summary=None, description=None):
        """Make a `BinaryPackageRelease`."""
        if binarypackagename is None:
            binarypackagename = self.makeBinaryPackageName()
        if version is None:
            version = self.getUniqueString("version")
        if build is None:
            build = self.makeBinaryPackageBuild()
        if binpackageformat is None:
            binpackageformat = BinaryPackageFormat.DEB
        if component is None:
            component = self.makeComponent()
        section = self.makeSection(name=section_name)
        if priority is None:
            priority = PackagePublishingPriority.OPTIONAL
        if summary is None:
            summary = self.getUniqueString("summary")
        if description is None:
            description = self.getUniqueString("description")
        return ProxyFactory(
            BinaryPackageRelease(
                binarypackagename=binarypackagename, version=version,
                build=build, binpackageformat=binpackageformat,
                component=component, section=section, priority=priority,
                summary=summary, description=description,
                architecturespecific=architecturespecific))

    def makeSection(self, name=None):
        """Make a `Section`."""
        if name is None:
            name = self.getUniqueString('section')
        return getUtility(ISectionSet).ensure(name)

    def makePackageset(self, name=None, description=None, owner=None,
                       packages=(), distroseries=None):
        """Make an `IPackageset`."""
        if name is None:
            name = self.getUniqueString(u'package-set-name')
        if description is None:
            description = self.getUniqueString(u'package-set-description')
        if owner is None:
            person = self.getUniqueString(u'package-set-owner')
            owner = self.makePerson(name=person)
        techboard = getUtility(ILaunchpadCelebrities).ubuntu_techboard
        ps_set = getUtility(IPackagesetSet)
        package_set = run_with_login(
            techboard.teamowner,
            lambda: ps_set.new(name, description, owner, distroseries))
        run_with_login(owner, lambda: package_set.add(packages))
        return package_set

    def getAnyPocket(self):
        return PackagePublishingPocket.BACKPORTS

    def makeSuiteSourcePackage(self, distroseries=None,
                               sourcepackagename=None, pocket=None):
        if distroseries is None:
            distroseries = self.makeDistroRelease()
        if pocket is None:
            pocket = self.getAnyPocket()
        # Make sure we have a real sourcepackagename object.
        if (sourcepackagename is None or
            isinstance(sourcepackagename, basestring)):
            sourcepackagename = self.getOrMakeSourcePackageName(
                sourcepackagename)
        return ProxyFactory(
            SuiteSourcePackage(distroseries, pocket, sourcepackagename))

    def makeDistributionSourcePackage(self, sourcepackagename=None,
                                      distribution=None, with_db=False):
        # Make sure we have a real sourcepackagename object.
        if (sourcepackagename is None or
            isinstance(sourcepackagename, basestring)):
            sourcepackagename = self.getOrMakeSourcePackageName(
                sourcepackagename)
        if distribution is None:
            distribution = self.makeDistribution()
        package = distribution.getSourcePackage(sourcepackagename)
        if with_db:
            # Create an instance with a database record, that is normally
            # done by secondary process.
            removeSecurityProxy(package)._new(
                distribution, sourcepackagename, False)
        return package

    def makeEmailMessage(self, body=None, sender=None, to=None,
                         attachments=None, encode_attachments=False):
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
                if encode_attachments:
                    encode_base64(attachment)
                msg.attach(attachment)
        return msg

    def makeBundleMergeDirectiveEmail(self, source_branch, target_branch,
                                      signing_context=None, sender=None):
        """Create a merge directive email from two bzr branches.

        :param source_branch: The source branch for the merge directive.
        :param target_branch: The target branch for the merge directive.
        :param signing_context: A GPGSigningContext instance containing the
            gpg key to sign with.  If None, the message is unsigned.  The
            context also contains the password and gpg signing mode.
        :param sender: The `Person` that is sending the email.
        """
        md = MergeDirective2.from_objects(
            source_branch.repository, source_branch.last_revision(),
            public_branch=source_branch.get_public_branch(),
            target_branch=target_branch.getInternalBzrUrl(),
            local_target_branch=target_branch.getInternalBzrUrl(), time=0,
            timezone=0)
        email = None
        if sender is not None:
            email = sender.preferredemail.email
        return self.makeSignedMessage(
            body='My body', subject='My subject',
            attachment_contents=''.join(md.to_lines()),
            signing_context=signing_context, email_address=email)

    def makeMergeDirective(self, source_branch=None, target_branch=None,
        source_branch_url=None, target_branch_url=None):
        """Return a bzr merge directive object.

        :param source_branch: The source database branch in the merge
            directive.
        :param target_branch: The target database branch in the merge
            directive.
        :param source_branch_url: The URL of the source for the merge
            directive.  Overrides source_branch.
        :param target_branch_url: The URL of the target for the merge
            directive.  Overrides target_branch.
        """
        from bzrlib.merge_directive import MergeDirective2
        if source_branch_url is not None:
            assert source_branch is None
        else:
            if source_branch is None:
                source_branch = self.makeAnyBranch()
            source_branch_url = (
                config.codehosting.supermirror_root +
                source_branch.unique_name)
        if target_branch_url is not None:
            assert target_branch is None
        else:
            if target_branch is None:
                target_branch = self.makeAnyBranch()
            target_branch_url = (
                config.codehosting.supermirror_root +
                target_branch.unique_name)
        return MergeDirective2(
            'revid', 'sha', 0, 0, target_branch_url,
            source_branch=source_branch_url, base_revision_id='base-revid',
            patch='')

    def makeMergeDirectiveEmail(self, body='Hi!\n', signing_context=None):
        """Create an email with a merge directive attached.

        :param body: The message body to use for the email.
        :param signing_context: A GPGSigningContext instance containing the
            gpg key to sign with.  If None, the message is unsigned.  The
            context also contains the password and gpg signing mode.
        :return: message, file_alias, source_branch, target_branch
        """
        target_branch = self.makeProductBranch()
        source_branch = self.makeProductBranch(
            product=target_branch.product)
        md = self.makeMergeDirective(source_branch, target_branch)
        message = self.makeSignedMessage(body=body,
            subject='My subject', attachment_contents=''.join(md.to_lines()),
            signing_context=signing_context)
        message_string = message.as_string()
        file_alias = getUtility(ILibraryFileAliasSet).create(
            '*', len(message_string), StringIO(message_string), '*')
        return message, file_alias, source_branch, target_branch

    def makeHWSubmission(self, date_created=None, submission_key=None,
                         emailaddress=u'test@canonical.com',
                         distroarchseries=None, private=False,
                         contactable=False, system=None,
                         submission_data=None):
        """Create a new HWSubmission."""
        if date_created is None:
            date_created = datetime.now(pytz.UTC)
        if submission_key is None:
            submission_key = self.getUniqueString('submission-key')
        if distroarchseries is None:
            distroarchseries = self.makeDistroArchSeries()
        if system is None:
            system = self.getUniqueString('system-fingerprint')
        if submission_data is None:
            sample_data_path = os.path.join(
                config.root, 'lib', 'canonical', 'launchpad', 'scripts',
                'tests', 'simple_valid_hwdb_submission.xml')
            submission_data = open(sample_data_path).read()
        filename = self.getUniqueString('submission-file')
        filesize = len(submission_data)
        raw_submission = StringIO(submission_data)
        format = HWSubmissionFormat.VERSION_1
        submission_set = getUtility(IHWSubmissionSet)

        return submission_set.createSubmission(
            date_created, format, private, contactable,
            submission_key, emailaddress, distroarchseries,
            raw_submission, filename, filesize, system)

    def makeHWSubmissionDevice(self, submission, device, driver, parent,
                               hal_device_id):
        """Create a new HWSubmissionDevice."""
        device_driver_link_set = getUtility(IHWDeviceDriverLinkSet)
        device_driver_link = device_driver_link_set.getOrCreate(
            device, driver)
        return getUtility(IHWSubmissionDeviceSet).create(
            device_driver_link, submission, parent, hal_device_id)

    def makeSSHKey(self, person=None):
        """Create a new SSHKey."""
        if person is None:
            person = self.makePerson()
        public_key = "ssh-rsa %s %s" % (
            self.getUniqueString(), self.getUniqueString())
        return getUtility(ISSHKeySet).new(person, public_key)

    def makeBlob(self, blob=None, expires=None):
        """Create a new TemporaryFileStorage BLOB."""
        if blob is None:
            blob = self.getUniqueString()
        new_uuid = getUtility(ITemporaryStorageManager).new(blob, expires)

        return getUtility(ITemporaryStorageManager).fetch(new_uuid)


# Some factory methods return simple Python types. We don't add
# security wrappers for them, as well as for objects created by
# other Python libraries.
unwrapped_types = (
    BaseRecipeBranch, DSCFile, InstanceType, MergeDirective2, Message,
    datetime, int, str, unicode)


def is_security_proxied_or_harmless(obj):
    """Check that the object is security wrapped or a harmless object."""
    if obj is None:
        return True
    if builtin_isinstance(obj, Proxy):
        return True
    if type(obj) in unwrapped_types:
        return True
    if isSequenceType(obj):
        for element in obj:
            if not is_security_proxied_or_harmless(element):
                return False
        return True
    return False


class UnproxiedFactoryMethodWarning(UserWarning):
    """Raised when someone calls an unproxied factory method."""

    def __init__(self, method_name):
        super(UnproxiedFactoryMethodWarning, self).__init__(
            "PLEASE FIX: LaunchpadObjectFactory.%s returns an "
            "unproxied object." % (method_name, ))


class ShouldThisBeUsingRemoveSecurityProxy(UserWarning):
    """Raised when there is a potentially bad call to removeSecurityProxy."""

    def __init__(self, obj):
        message = (
            "removeSecurityProxy(%r) called. Is this correct? "
            "Either call it directly or fix the test." % obj)
        super(ShouldThisBeUsingRemoveSecurityProxy, self).__init__(message)


class LaunchpadObjectFactory:
    """A wrapper around `BareLaunchpadObjectFactory`.

    Ensure that each object created by a `BareLaunchpadObjectFactory` method
    is either of a simple Python type or is security proxied.

    A warning message is printed to stderr if a factory method creates
    an object without a security proxy.

    Whereever you see such a warning: fix it!
    """

    def __init__(self):
        self._factory = BareLaunchpadObjectFactory()

    def __getattr__(self, name):
        attr = getattr(self._factory, name)
        if os.environ.get('LP_PROXY_WARNINGS') == '1' and callable(attr):

            def guarded_method(*args, **kw):
                result = attr(*args, **kw)
                if not is_security_proxied_or_harmless(result):
                    warnings.warn(
                        UnproxiedFactoryMethodWarning(name), stacklevel=1)
                return result
            return guarded_method
        else:
            return attr


def remove_security_proxy_and_shout_at_engineer(obj):
    """Remove an object's security proxy and print a warning.

    A number of LaunchpadObjectFactory methods returned objects without
    a security proxy. This is now no longer possible, but a number of
    tests rely on unrestricted access to object attributes.

    This function should only be used in legacy tests which fail because
    they expect unproxied objects.
    """
    if os.environ.get('LP_PROXY_WARNINGS') == '1':
        warnings.warn(ShouldThisBeUsingRemoveSecurityProxy(obj), stacklevel=2)
    return removeSecurityProxy(obj)
