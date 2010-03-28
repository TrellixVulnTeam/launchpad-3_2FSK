# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Person interfaces."""

__metaclass__ = type

__all__ = [
    'IAdminPeopleMergeSchema',
    'IAdminTeamMergeSchema',
    'IHasStanding',
    'INewPerson',
    'INewPersonForm',
    'IObjectReassignment',
    'IPerson',
    'IPersonChangePassword',
    'IPersonClaim',
    'IPersonPublic', # Required for a monkey patch in interfaces/archive.py
    'IPersonSet',
    'IPersonViewRestricted',
    'IRequestPeopleMerge',
    'ITeam',
    'ITeamContactAddressForm',
    'ITeamCreation',
    'ITeamReassignment',
    'ImmutableVisibilityError',
    'InvalidName',
    'JoinNotAllowed',
    'NameAlreadyTaken',
    'NoSuchPerson',
    'PersonCreationRationale',
    'PersonVisibility',
    'PersonalStanding',
    'PrivatePersonLinkageError',
    'PRIVATE_TEAM_PREFIX',
    'TeamContactMethod',
    'TeamMembershipRenewalPolicy',
    'TeamSubscriptionPolicy',
    'validate_person_not_private_membership',
    'validate_public_person',
    ]


from zope.formlib.form import NoInputData
from zope.schema import Bool, Choice, Datetime, Int, Object, Text, TextLine
from zope.interface import Attribute, Interface
from zope.interface.exceptions import Invalid
from zope.interface.interface import invariant
from zope.component import getUtility

from lazr.enum import DBEnumeratedType, DBItem, EnumeratedType, Item
from lazr.lifecycle.snapshot import doNotSnapshot
from lazr.restful.interface import copy_field
from lazr.restful.declarations import (
    LAZR_WEBSERVICE_EXPORTED, REQUEST_USER, call_with,
    collection_default_content, export_as_webservice_collection,
    export_as_webservice_entry, export_factory_operation,
    export_read_operation, export_write_operation, exported,
    operation_parameters, operation_returns_collection_of,
    operation_returns_entry, rename_parameters_as, webservice_error)
from lazr.restful.fields import CollectionField, Reference

from canonical.database.sqlbase import block_implicit_flushes
from canonical.launchpad import _
from canonical.launchpad.fields import (
    BlacklistableContentNameField, IconImageUpload, LogoImageUpload,
    MugshotImageUpload, PasswordField, PersonChoice, PublicPersonChoice,
    StrippedTextLine, is_private_membership_person, is_public_person)
from canonical.launchpad.interfaces.account import AccountStatus, IAccount
from canonical.launchpad.interfaces.emailaddress import IEmailAddress
from canonical.launchpad.interfaces.launchpad import (
    IHasIcon, IHasLogo, IHasMugshot, IPrivacy)
from canonical.launchpad.interfaces.validation import (
    validate_new_person_email, validate_new_team_email)
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.validators.email import email_validator
from canonical.launchpad.validators.name import name_validator
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.interfaces import NameLookupFailed

from lp.app.interfaces.headings import IRootContext
from lp.blueprints.interfaces.specificationtarget import (
    IHasSpecifications)
from lp.bugs.interfaces.bugtarget import IHasBugs
from lp.code.interfaces.hasbranches import (
    IHasBranches, IHasMergeProposals, IHasRequestedReviews)
from lp.registry.interfaces.gpg import IGPGKey
from lp.registry.interfaces.irc import IIrcID
from lp.registry.interfaces.jabber import IJabberID
from lp.registry.interfaces.location import (
    IHasLocation, ILocationRecord, IObjectWithLocation, ISetLocation)
from lp.registry.interfaces.mailinglistsubscription import (
    MailingListAutoSubscribePolicy)
from lp.registry.interfaces.mentoringoffer import IHasMentoringOffers
from lp.registry.interfaces.teammembership import (
    ITeamMembership, ITeamParticipation, TeamMembershipStatus)
from lp.registry.interfaces.wikiname import IWikiName
from lp.services.worlddata.interfaces.language import ILanguage


PRIVATE_TEAM_PREFIX = 'private-'


class PrivatePersonLinkageError(ValueError):
    """An attempt was made to link a private person/team to something."""


@block_implicit_flushes
def validate_person(obj, attr, value, validate_func):
    """Validate the person using the supplied function."""
    if value is None:
        return None
    assert isinstance(value, (int, long)), (
        "Expected int for Person foreign key reference, got %r" % type(value))

    # XXX sinzui 2009-04-03 bug=354881: We do not want to import from the
    # DB. This needs cleaning up.
    from lp.registry.model.person import Person
    person = Person.get(value)
    if validate_func(person):
        raise PrivatePersonLinkageError(
            "Cannot link person (name=%s, visibility=%s) to %s (name=%s)"
            % (person.name, person.visibility.name,
               obj, getattr(obj, 'name', None)))
    return value


def validate_public_person(obj, attr, value):
    """Validate that the person identified by value is public."""

    def validate(person):
        return not is_public_person(person)

    return validate_person(obj, attr, value, validate)


def validate_person_not_private_membership(obj, attr, value):
    """Validate that the person (value) is not a private membership team."""
    return validate_person(obj, attr, value, is_private_membership_person)


class PersonalStanding(DBEnumeratedType):
    """A person's standing.

    Standing is currently (just) used to determine whether a person's posts to
    a mailing list require first-post moderation or not.  Any person with good
    or excellent standing may post directly to the mailing list without
    moderation.  Any person with unknown or poor standing must have their
    first-posts moderated.
    """

    UNKNOWN = DBItem(0, """
        Unknown standing

        Nothing about this person's standing is known.
        """)

    POOR = DBItem(100, """
        Poor standing

        This person has poor standing.
        """)

    GOOD = DBItem(200, """
        Good standing

        This person has good standing and may post to a mailing list without
        being subject to first-post moderation rules.
        """)

    EXCELLENT = DBItem(300, """
        Excellent standing

        This person has excellent standing and may post to a mailing list
        without being subject to first-post moderation rules.
        """)


class PersonCreationRationale(DBEnumeratedType):
    """The rationale for the creation of a given person.

    Launchpad automatically creates user accounts under certain
    circumstances. The owners of these accounts may discover Launchpad
    at a later date and wonder why Launchpad knows about them, so we
    need to make it clear why a certain account was automatically created.
    """

    UNKNOWN = DBItem(1, """
        Unknown

        The reason for the creation of this person is unknown.
        """)

    BUGIMPORT = DBItem(2, """
        Existing user in another bugtracker from which we imported bugs.

        A bugzilla import or sf.net import, for instance. The bugtracker from
        which we were importing should be described in
        Person.creation_comment.
        """)

    SOURCEPACKAGEIMPORT = DBItem(3, """
        This person was mentioned in a source package we imported.

        When gina imports source packages, it has to create Person entries for
        the email addresses that are listed as maintainer and/or uploader of
        the package, in case they don't exist in Launchpad.
        """)

    POFILEIMPORT = DBItem(4, """
        This person was mentioned in a POFile imported into Rosetta.

        When importing POFiles into Rosetta, we need to give credit for the
        translations on that POFile to its last translator, which may not
        exist in Launchpad, so we'd need to create it.
        """)

    KEYRINGTRUSTANALYZER = DBItem(5, """
        Created by the keyring trust analyzer.

        The keyring trust analyzer is responsible for scanning GPG keys
        belonging to the strongly connected set and assign all email addresses
        registered on those keys to the people representing their owners in
        Launchpad. If any of these people doesn't exist, it creates them.
        """)

    FROMEMAILMESSAGE = DBItem(6, """
        Created when parsing an email message.

        Sometimes we parse email messages and want to associate them with the
        sender, which may not have a Launchpad account. In that case we need
        to create a Person entry to associate with the email.
        """)

    SOURCEPACKAGEUPLOAD = DBItem(7, """
        This person was mentioned in a source package uploaded.

        Some uploaded packages may be uploaded with a maintainer that is not
        registered in Launchpad, and in these cases, soyuz may decide to
        create the new Person instead of complaining.
        """)

    OWNER_CREATED_LAUNCHPAD = DBItem(8, """
        Created by the owner, coming from Launchpad.

        Somebody was navigating through Launchpad and at some point decided to
        create an account.
        """)

    OWNER_CREATED_SHIPIT = DBItem(9, """
        Created by the owner, coming from Shipit.

        Somebody went to one of the shipit sites to request Ubuntu CDs and was
        directed to Launchpad to create an account.
        """)

    OWNER_CREATED_UBUNTU_WIKI = DBItem(10, """
        Created by the owner, coming from the Ubuntu wiki.

        Somebody went to the Ubuntu wiki and was directed to Launchpad to
        create an account.
        """)

    USER_CREATED = DBItem(11, """
        Created by a user to represent a person which does not use Launchpad.

        A user wanted to reference a person which is not a Launchpad user, so
        he created this "placeholder" profile.
        """)

    OWNER_CREATED_UBUNTU_SHOP = DBItem(12, """
        Created by the owner, coming from the Ubuntu Shop.

        Somebody went to the Ubuntu Shop and was directed to Launchpad to
        create an account.
        """)

    OWNER_CREATED_UNKNOWN_TRUSTROOT = DBItem(13, """
        Created by the owner, coming from unknown OpenID consumer.

        Somebody went to an OpenID consumer we don't know about and was
        directed to Launchpad to create an account.
        """)

    OWNER_SUBMITTED_HARDWARE_TEST = DBItem(14, """
        Created by a submission to the hardware database.

        Somebody without a Launchpad account made a submission to the
        hardware database.
        """)

    BUGWATCH = DBItem(15, """
        Created by the updating of a bug watch.

        A watch was made against a remote bug that the user submitted or
        commented on.
        """)


class TeamMembershipRenewalPolicy(DBEnumeratedType):
    """TeamMembership Renewal Policy.

    How Team Memberships can be renewed on a given team.
    """

    NONE = DBItem(10, """
        invite them to apply for renewal

        Memberships can be renewed only by team administrators or by going
        through the normal workflow for joining the team.
        """)

    ONDEMAND = DBItem(20, """
        invite them to renew their own membership

        Memberships can be renewed by the members themselves a few days before
        it expires. After it expires the member has to go through the normal
        workflow for joining the team.
        """)

    AUTOMATIC = DBItem(30, """
        renew their membership automatically, also notifying the admins

        Memberships are automatically renewed when they expire and a note is
        sent to the member and to team admins.
        """)


class TeamSubscriptionPolicy(DBEnumeratedType):
    """Team Subscription Policies

    The policies that apply to a team and specify how new subscriptions must
    be handled. More information can be found in the TeamMembershipPolicies
    spec.
    """

    MODERATED = DBItem(1, """
        Moderated Team

        All subscriptions for this team are subject to approval by one of
        the team's administrators.
        """)

    OPEN = DBItem(2, """
        Open Team

        Any user can join and no approval is required.
        """)

    RESTRICTED = DBItem(3, """
        Restricted Team

        New members can only be added by one of the team's administrators.
        """)


class PersonVisibility(DBEnumeratedType):
    """The visibility level of person or team objects.

    Currently, only teams can have their visibility set to something
    besides PUBLIC.
    """

    PUBLIC = DBItem(1, """
        Public

        Everyone can view all the attributes of this person.
        """)

    PRIVATE_MEMBERSHIP = DBItem(20, """
        Private Membership

        Only Launchpad admins and team members can view the
        membership list for this team. The team is severely restricted in the
        roles it can assume.
        """)

    PRIVATE = DBItem(30, """
        Private

        Only Launchpad admins and team members can view the membership list
        for this team or its name.  The team roles are restricted to
        subscribing to bugs, being bug supervisor, owning code branches, and
        having a PPA.
        """)


class PersonNameField(BlacklistableContentNameField):
    """A `Person` team name, which is unique and performs psuedo blacklisting.

    If the team name is not unique, and the clash is with a private team,
    return the blacklist message.  Also return the blacklist message if the
    private prefix is used but the user is not privileged to create private
    teams.
    """
    errormessage = _("%s is already in use by another person or team.")

    blacklistmessage = _("The name '%s' has been blocked by the Launchpad "
                         "administrators.")

    @property
    def _content_iface(self):
        """Return the interface this field belongs to."""
        return IPerson

    def _getByName(self, name):
        """Return a Person by looking up his name."""
        return getUtility(IPersonSet).getByName(name, ignore_merged=False)

    def _validate(self, input):
        """See `UniqueField`."""
        # If the name didn't change then we needn't worry about validating it.
        if self.unchanged(input):
            return

        if not check_permission('launchpad.Commercial', self.context):
            # Commercial admins can create private teams, with or without the
            # private prefix.

            if input.startswith(PRIVATE_TEAM_PREFIX):
                raise LaunchpadValidationError(self.blacklistmessage % input)

            # If a non-privileged user attempts to use an existing name AND
            # the existing project is private, then return the blacklist
            # message rather than the message indicating the project exists.
            existing_object = self._getByAttribute(input)
            if (existing_object is not None and
                existing_object.visibility != PersonVisibility.PUBLIC):
                raise LaunchpadValidationError(self.blacklistmessage % input)

        # Perform the normal validation, including the real blacklist checks.
        super(PersonNameField, self)._validate(input)


# XXX: salgado, 2010/03/05, bug=532688: This is currently used by c-i-p, so it
# can't be removed yet.  As soon as we stop using c-i-p, though, we'll be able
# to remove this.
class IPersonChangePassword(Interface):
    """The schema used by Person +changepassword form."""

    currentpassword = PasswordField(
        title=_('Current password'), required=True, readonly=False)

    password = PasswordField(
        title=_('New password'), required=True, readonly=False)


class IPersonClaim(Interface):
    """The schema used by IPerson's +claim form."""

    emailaddress = TextLine(title=_('Email address'), required=True)


class INewPerson(Interface):
    """The schema used by IPersonSet's +newperson form."""

    emailaddress = StrippedTextLine(
        title=_('Email address'), required=True,
        constraint=validate_new_person_email)
    displayname = StrippedTextLine(title=_('Display name'), required=True)
    creation_comment = Text(
        title=_('Creation reason'), required=True,
        description=_("The reason why you're creating this profile."))


# This has to be defined here to avoid circular import problems.
class IHasStanding(Interface):
    """An object that can have personal standing."""

    personal_standing = Choice(
        title=_('Personal standing'),
        required=True,
        vocabulary=PersonalStanding,
        description=_('The standing of a person for non-member mailing list '
                      'posting privileges.'))

    personal_standing_reason = Text(
        title=_('Reason for personal standing'),
        required=False,
        description=_("The reason the person's standing is what it is."))


class IPersonPublic(IHasBranches, IHasSpecifications, IHasMentoringOffers,
                    IHasMergeProposals, IHasLogo, IHasMugshot, IHasIcon,
                    IHasLocation, IHasRequestedReviews, IObjectWithLocation,
                    IPrivacy, IHasBugs):
    """Public attributes for a Person."""

    id = Int(title=_('ID'), required=True, readonly=True)
    account = Object(schema=IAccount)
    accountID = Int(title=_('Account ID'), required=True, readonly=True)
    password = PasswordField(
        title=_('Password'), required=True, readonly=False)
    karma = exported(
        Int(title=_('Karma'), readonly=True,
            description=_('The cached total karma for this person.')))
    homepage_content = exported(
        Text(title=_("Homepage Content"), required=False,
            description=_(
                "The content of your profile page. Use plain text, "
                "paragraphs are preserved and URLs are linked in pages.")))
    # NB at this stage we do not allow individual people to have their own
    # icon, only teams get that. People can however have a logo and mugshot
    # The icon is only used for teams; that's why we use /@@/team as the
    # default image resource.
    icon = IconImageUpload(
        title=_("Icon"), required=False,
        default_image_resource='/@@/team',
        description=_(
            "A small image of exactly 14x14 pixels and at most 5kb in size, "
            "that can be used to identify this team. The icon will be "
            "displayed whenever the team name is listed - for example "
            "in listings of bugs or on a person's membership table."))
    iconID = Int(title=_('Icon ID'), required=True, readonly=True)

    logo = exported(
        LogoImageUpload(
            title=_("Logo"), required=False,
            default_image_resource='/@@/person-logo',
            description=_(
                "An image of exactly 64x64 pixels that will be displayed in "
                "the heading of all pages related to you. Traditionally this "
                "is a logo, a small picture or a personal mascot. It should "
                "be no bigger than 50kb in size.")))
    logoID = Int(title=_('Logo ID'), required=True, readonly=True)

    mugshot = exported(MugshotImageUpload(
        title=_("Mugshot"), required=False,
        default_image_resource='/@@/person-mugshot',
        description=_(
            "A large image of exactly 192x192 pixels, that will be displayed "
            "on your home page in Launchpad. Traditionally this is a great "
            "big picture of your grinning face. Make the most of it! It "
            "should be no bigger than 100kb in size. ")))
    mugshotID = Int(title=_('Mugshot ID'), required=True, readonly=True)

    addressline1 = TextLine(
            title=_('Address'), required=True, readonly=False,
            description=_('Your address (Line 1)'))
    addressline2 = TextLine(
            title=_('Address'), required=False, readonly=False,
            description=_('Your address (Line 2)'))
    city = TextLine(
            title=_('City'), required=True, readonly=False,
            description=_('The City/Town/Village/etc to where the CDs should '
                          'be shipped.'))
    province = TextLine(
            title=_('Province'), required=True, readonly=False,
            description=_('The State/Province/etc to where the CDs should '
                          'be shipped.'))
    country = Choice(
            title=_('Country'), required=True, readonly=False,
            vocabulary='CountryName',
            description=_('The Country to where the CDs should be shipped.'))
    postcode = TextLine(
            title=_('Postcode'), required=True, readonly=False,
            description=_('The Postcode to where the CDs should be shipped.'))
    phone = TextLine(
            title=_('Phone'), required=True, readonly=False,
            description=_('[(+CountryCode) number] e.g. (+55) 16 33619445'))
    organization = TextLine(
            title=_('Organization'), required=False, readonly=False,
            description=_('The Organization requesting the CDs'))
    languages = exported(
        CollectionField(
            title=_('List of languages known by this person'),
            readonly=True, required=False,
            value_type=Reference(schema=ILanguage)))

    hide_email_addresses = exported(
        Bool(title=_("Hide my email addresses from other Launchpad users"),
             required=False, default=False))
    # This is not a date of birth, it is the date the person record was
    # created in this db
    datecreated = exported(
        Datetime(title=_('Date Created'), required=True, readonly=True),
        exported_as='date_created')
    creation_rationale = Choice(
        title=_("Rationale for this entry's creation"), required=False,
        readonly=True, values=PersonCreationRationale.items)
    creation_comment = TextLine(
        title=_("Comment for this entry's creation"),
        description=_(
            "This comment may be displayed verbatim in a web page, so it "
            "has to follow some structural constraints, that is, it must "
            "be of the form: 'when %(action_details)s' (e.g 'when the "
            "foo package was imported into Ubuntu Breezy'). The only "
            "exception to this is when we allow users to create Launchpad "
            "profiles through the /people/+newperson page."),
        required=False, readonly=True)
    # XXX Guilherme Salgado 2006-11-10:
    # We can't use a Choice field here because we don't have a vocabulary
    # which contains valid people but not teams, and we don't really need one
    # apart from here.
    registrant = Attribute('The user who created this profile.')

    oauth_access_tokens = Attribute(_("Non-expired access tokens"))

    oauth_request_tokens = Attribute(_("Non-expired request tokens"))

    sshkeys = Attribute(_('List of SSH keys'))

    account_status = Choice(
        title=_("The status of this person's account"), required=False,
        readonly=True, vocabulary=AccountStatus)

    account_status_comment = Text(
        title=_("Why are you deactivating your account?"), required=False,
        readonly=True)

    # Properties of the Person object.
    karma_category_caches = Attribute(
        'The caches of karma scores, by karma category.')
    is_team = exported(
        Bool(title=_('Is this object a team?'), readonly=True))
    is_valid_person = Bool(
        title=_("This is an active user and not a team."), readonly=True)
    is_valid_person_or_team = exported(
        Bool(title=_("This is an active user or a team."), readonly=True),
        exported_as='is_valid')
    is_probationary = exported(
        Bool(title=_("Is this a probationary user?"), readonly=True))
    is_ubuntu_coc_signer = exported(
    Bool(title=_("Signed Ubuntu Code of Conduct"),
            readonly=True))
    activesignatures = Attribute("Retrieve own Active CoC Signatures.")
    inactivesignatures = Attribute("Retrieve own Inactive CoC Signatures.")
    signedcocs = Attribute("List of Signed Code Of Conduct")
    gpg_keys = exported(
        CollectionField(
            title=_("List of valid OpenPGP keys ordered by ID"),
            readonly=False, required=False,
            value_type=Reference(schema=IGPGKey)))
    pending_gpg_keys = exported(
        CollectionField(
            title=_("Set of fingerprints pending confirmation"),
            readonly=False, required=False,
            value_type=Reference(schema=IGPGKey)))
    inactive_gpg_keys = Attribute(
        "List of inactive OpenPGP keys in LP Context, ordered by ID")
    wiki_names = exported(
        CollectionField(
            title=_("All WikiNames of this Person, sorted alphabetically by "
                    "URL."),
            readonly=True, required=False,
            value_type=Reference(schema=IWikiName)))
    ircnicknames = exported(
        CollectionField(title=_("List of IRC nicknames of this Person."),
                        readonly=True, required=False,
                        value_type=Reference(schema=IIrcID)),
        exported_as='irc_nicknames')
    jabberids = exported(
        CollectionField(title=_("List of Jabber IDs of this Person."),
                        readonly=True, required=False,
                        value_type=Reference(schema=IJabberID)),
        exported_as='jabber_ids')
    myactivememberships = exported(
        CollectionField(
            title=_("All TeamMemberships for Teams this Person is an "
                    "active member of."),
            value_type=Reference(schema=ITeamMembership),
            readonly=True, required=False),
        exported_as='memberships_details')
    open_membership_invitations = exported(
        CollectionField(
            title=_('Open membership invitations.'),
            description=_("All TeamMemberships which represent an invitation "
                          "(to join a team) sent to this person."),
            readonly=True, required=False,
            value_type=Reference(schema=ITeamMembership)))
    # XXX: salgado, 2008-08-01: Unexported because this method doesn't take
    # into account whether or not a team's memberships are private.
    # teams_participated_in = exported(
    #     CollectionField(
    #         title=_('All teams in which this person is a participant.'),
    #         readonly=True, required=False,
    #         value_type=Reference(schema=Interface)),
    #     exported_as='participations')
    teams_participated_in = CollectionField(
        title=_('All teams in which this person is a participant.'),
        readonly=True, required=False,
        value_type=Reference(schema=Interface))
    # XXX: salgado, 2008-08-01: Unexported because this method doesn't take
    # into account whether or not a team's memberships are private.
    # teams_indirectly_participated_in = exported(
    #     CollectionField(
    #         title=_(
    #             'All teams in which this person is an indirect member.'),
    #         readonly=True, required=False,
    #         value_type=Reference(schema=Interface)),
    #     exported_as='indirect_participations')
    teams_indirectly_participated_in = CollectionField(
        title=_('All teams in which this person is an indirect member.'),
        readonly=True, required=False,
        value_type=Reference(schema=Interface))
    teams_with_icons = Attribute(
        "Iterable of all Teams that this person is active in that have "
        "icons")
    guessedemails = Attribute(
        "List of emails with status NEW. These email addresses probably "
        "came from a gina or POFileImporter run.")
    validatedemails = exported(
        CollectionField(
            title=_("Confirmed e-mails of this person."),
            description=_(
                "Confirmed e-mails are the ones in the VALIDATED state"),
            readonly=True, required=False,
            value_type=Reference(schema=IEmailAddress)),
        exported_as='confirmed_email_addresses')
    unvalidatedemails = Attribute(
        "Emails this person added in Launchpad but are not yet validated.")
    specifications = Attribute(
        "Any specifications related to this person, either because the are "
        "a subscriber, or an assignee, or a drafter, or the creator. "
        "Sorted newest-first.")
    assigned_specs = Attribute(
        "Specifications assigned to this person, sorted newest first.")
    assigned_specs_in_progress = Attribute(
        "Specifications assigned to this person whose implementation is "
        "started but not yet completed, sorted newest first.")
    team_mentorships = Attribute(
        "All the offers of mentoring which are relevant to this team.")
    teamowner = exported(
        PublicPersonChoice(
            title=_('Team Owner'), required=False, readonly=False,
            vocabulary='ValidTeamOwner'),
        exported_as='team_owner')
    teamownerID = Int(title=_("The Team Owner's ID or None"), required=False,
                      readonly=True)

    preferredemail = exported(
        Reference(title=_("Preferred email address"),
               description=_("The preferred email address for this person. "
                             "The one we'll use to communicate with them."),
               readonly=True, required=False, schema=IEmailAddress),
        exported_as='preferred_email_address')

    safe_email_or_blank = TextLine(
        title=_("Safe email for display"),
        description=_("The person's preferred email if they have"
                      "one and do not choose to hide it. Otherwise"
                      "the empty string."),
        readonly=True)

    verbose_bugnotifications = Bool(
        title=_("Include bug descriptions when sending me bug notifications"),
        required=False, default=True)

    mailing_list_auto_subscribe_policy = exported(
        Choice(title=_('Mailing List Auto-subscription Policy'),
               required=True,
               vocabulary=MailingListAutoSubscribePolicy,
               default=MailingListAutoSubscribePolicy.ON_REGISTRATION,
               description=_(
                   "This attribute determines whether a person is "
                   "automatically subscribed to a team's mailing list when "
                   "the person joins said team.")))

    merged = Int(
        title=_('Merged Into'), required=False, readonly=True,
        description=_(
            "When a Person is merged into another Person, this attribute "
            "is set on the Person referencing the destination Person. If "
            "this is set to None, then this Person has not been merged "
            "into another and is still valid"))

    # title is required for the Launchpad Page Layout main template
    title = Attribute('Person Page Title')

    archive = exported(
        Reference(
            title=_("Default PPA"),
            description=_("The PPA named 'ppa' owned by this person."),
            readonly=True, required=False,
            # Really IArchive, see archive.py
            schema=Interface))

    ppas = exported(
        CollectionField(
            title=_("PPAs for this person."),
            description=_(
                "PPAs owned by the context person ordered by name."),
            readonly=True, required=False,
            # Really IArchive, see archive.py
            value_type=Reference(schema=Interface)))

    entitlements = Attribute("List of Entitlements for this person or team.")

    structural_subscriptions = Attribute(
        "The structural subscriptions for this person.")

    visibilityConsistencyWarning = Attribute(
        "Warning that a private team may leak membership info.")

    sub_teams = exported(
        CollectionField(
            title=_("All subteams of this team."),
            description=_("""
                A subteam is any team that is a member (either directly or
                indirectly) of this team. As an example, let's say we have
                this hierarchy of teams:

                Rosetta Translators
                    Rosetta pt Translators
                        Rosetta pt_BR Translators

                In this case, both 'Rosetta pt Translators' and 'Rosetta pt_BR
                Translators' are subteams of the 'Rosetta Translators' team,
                and all members of both subteams are considered members of
                "Rosetta Translators".
                """),
            readonly=True, required=False,
            value_type=Reference(schema=Interface)))

    super_teams = exported(
        CollectionField(
            title=_("All superteams of this team."),
            description=_("""
                A superteam is any team that this team is a member of. For
                example, let's say we have this hierarchy of teams, and we are
                the "Rosetta pt_BR Translators":

                Rosetta Translators
                    Rosetta pt Translators
                        Rosetta pt_BR Translators

                In this case, we will return both 'Rosetta pt Translators' and
                'Rosetta Translators', because we are member of both of them.
                """),
            readonly=True, required=False,
            value_type=Reference(schema=Interface)))

    hardware_submissions = exported(CollectionField(
            title=_("Hardware submissions"),
            readonly=True, required=False,
            value_type=Reference(schema=Interface))) # HWSubmission

    # This is redefined from IPrivacy.private because the attribute is
    # read-only. It is a summary of the team's visibility.
    private = exported(Bool(
            title=_("This team is private"),
            readonly=True, required=False,
            description=_("Private teams are visible only to "
                          "their members.")))

    @invariant
    def personCannotHaveIcon(person):
        """Only Persons can have icons."""
        # XXX Guilherme Salgado 2007-05-28:
        # This invariant is busted! The person parameter provided to this
        # method will always be an instance of zope.formlib.form.FormData
        # containing only the values of the fields included in the POSTed
        # form. IOW, person.inTeam() will raise a NoInputData just like
        # person.teamowner would as it's not present in most of the
        # person-related forms.
        if person.icon is not None and not person.isTeam():
            raise Invalid('Only teams can have an icon.')

    def convertToTeam(team_owner):
        """Convert this person into a team owned by the given team_owner.

        Also adds the given team owner as an administrator of the team.

        Only Person entries whose account_status is NOACCOUNT and which are
        not teams can be converted into teams.
        """

    def getInvitedMemberships():
        """Return all TeamMemberships of this team with the INVITED status.

        The results are ordered using Person.sortingColumns.
        """

    def getInactiveMemberships():
        """Return all inactive TeamMemberships of this team.

        Inactive memberships are the ones with status EXPIRED or DEACTIVATED.

        The results are ordered using Person.sortingColumns.
        """

    def getProposedMemberships():
        """Return all TeamMemberships of this team with the PROPOSED status.

        The results are ordered using Person.sortingColumns.
        """

    def getBugSubscriberPackages():
        """Return the packages for which this person is a bug subscriber.

        Returns a list of IDistributionSourcePackage's, ordered alphabetically
        (A to Z) by name.
        """

    def setContactAddress(email):
        """Set the given email address as this team's contact address.

        This method must be used only for teams, unless the disable argument
        is True.

        If the team has a contact address its status will be changed to
        VALIDATED.

        If the given email is None the team is left without a contact address.
        """

    def setPreferredEmail(email):
        """Set the given email address as this person's preferred one.

        If ``email`` is None, the preferred email address is unset, which
        will make the person invalid.

        This method must be used only for people, not teams.
        """

    # XXX: salgado, 2008-08-01: Unexported because this method doesn't take
    # into account whether or not a team's memberships are private.
    # @operation_parameters(team=copy_field(ITeamMembership['team']))
    # @operation_returns_collection_of(Interface) # Really IPerson
    # @export_read_operation()
    def findPathToTeam(team):
        """Return the teams that cause this person to be a participant of the
        given team.

        If there is more than one path leading this person to the given team,
        only the one with the oldest teams is returned.

        This method must not be called if this person is not an indirect
        member of the given team.
        """

    def isTeam():
        """Deprecated.  Use IPerson.is_team instead.

        True if this Person is actually a Team, otherwise False.
        """

    # XXX BarryWarsaw 2007-11-29: I'd prefer for this to be an Object() with a
    # schema of IMailingList, but setting that up correctly causes a circular
    # import error with interfaces.mailinglists that is too difficult to
    # unfunge for this one attribute.
    mailing_list = Attribute(
        _("The team's mailing list, if it has one, otherwise None."))

    def getProjectsAndCategoriesContributedTo(limit=10):
        """Return a list of dicts with projects and the contributions made
        by this person on that project.

        The list is limited to the :limit: projects this person is most
        active.

        The dictionaries containing the following keys:
            - project:    The project, which is either an IProduct or an
                          IDistribution.
            - categories: A dictionary mapping KarmaCategory titles to
                          the icons which represent that category.
        """

    def getOwnedOrDrivenPillars():
        """Return Distribution, Project Groups and Projects that this person
        owns or drives.
        """

    def getOwnedProjects(match_name=None):
        """Projects owned by this person or teams to which she belongs.

        :param match_name: string optional project name to screen the results.
        """

    def getCommercialSubscriptionVouchers():
        """Return all commercial subscription vouchers.

        The vouchers are separated into two lists, unredeemed vouchers and
        redeemed vouchers.
        :return: tuple (unredeemed_vouchers, redeemed_vouchers)
        """

    def assignKarma(action_name, product=None, distribution=None,
                    sourcepackagename=None, datecreated=None):
        """Assign karma for the action named <action_name> to this person.

        This karma will be associated with the given product or distribution.
        If a distribution is given, then product must be None and an optional
        sourcepackagename may also be given. If a product is given, then
        distribution and sourcepackagename must be None.

        If a datecreated is specified, the karma will be created with that
        date.  This is how historic karma events can be created.
        """

    def latestKarma(quantity=25):
        """Return the latest karma actions for this person.

        Return no more than the number given as quantity.
        """

    def iterTopProjectsContributedTo(limit=10):
        """Iterate over the top projects contributed to.

        Iterate no more than the given limit.
        """

    # XXX: salgado, 2008-08-01: Unexported because this method doesn't take
    # into account whether or not a team's memberships are private.
    # @operation_parameters(team=copy_field(ITeamMembership['team']))
    # @export_read_operation()
    def inTeam(team):
        """Is this person is a member or the owner of `team`?

        Returns `True` when you ask if an `IPerson` (or an `ITeam`,
        since it inherits from `IPerson`) is a member of himself
        (i.e. `person1.inTeam(person1)`).

        :param team: An object providing `IPerson`, the name of a
            team, or `None` (in which case `False` is returned).
        """

    def clearInTeamCache():
        """Clears the person's inTeam cache.

        To be used when membership changes are enacted. Only meant to be
        used between TeamMembership and Person objects.
        """

    def getLatestMaintainedPackages():
        """Return `SourcePackageRelease`s maintained by this person.

        This method will only include the latest source package release
        for each source package name, distribution series combination.
        """

    def getLatestUploadedButNotMaintainedPackages():
        """Return `SourcePackageRelease`s created by this person but
        not maintained by him.

        This method will only include the latest source package release
        for each source package name, distribution series combination.
        """

    def getLatestUploadedPPAPackages():
        """Return `SourcePackageRelease`s uploaded by this person to any PPA.

        This method will only include the latest source package release
        for each source package name, distribution series combination.
        """

    def isUploader(distribution):
        """Return whether this person is an uploader for distribution.

        Returns True if this person is an uploader for distribution, or
        False otherwise.
        """

    def validateAndEnsurePreferredEmail(email):
        """Ensure this person has a preferred email.

        If this person doesn't have a preferred email, <email> will be set as
        this person's preferred one. Otherwise it'll be set as VALIDATED and
        this person will keep their old preferred email.

        This method is meant to be the only one to change the status of an
        email address, but as we all know the real world is far from ideal
        and we have to deal with this in one more place, which is the case
        when people explicitly want to change their preferred email address.
        On that case, though, all we have to do is use
        person.setPreferredEmail().
        """

    def hasParticipationEntryFor(team):
        """Return True when this person is a member of the given team.

        The person's membership may be direct or indirect.
        """

    def getAdministratedTeams():
        """Return the teams that this person/team is an administrator of.

        This includes teams for which the person is the owner, a direct
        member with admin privilege, or member of a team with such
        privileges.  It excludes teams which have been merged.
        """

    def getTeamAdminsEmailAddresses():
        """Return a set containing the email addresses of all administrators
        of this team.
        """

    def getLatestApprovedMembershipsForPerson(limit=5):
        """Return the <limit> latest approved membrships for this person."""

    def addLanguage(language):
        """Add a language to this person's preferences.

        :param language: An object providing ILanguage.

        If the given language is one of the user's preferred languages
        already, nothing will happen.
        """

    def removeLanguage(language):
        """Remove a language from this person's preferences.

        :param language: An object providing ILanguage.

        If the given language is not present, nothing  will happen.
        """

    def isBugContributor(user):
        """Is the person a contributer to bugs in Launchpad?

        Return True if the user has any bugs assigned to him, either
        directly or by team participation.

        :user: The user doing the search. Private bugs that this
        user doesn't have access to won't be included in the
        count.
        """

    def isBugContributorInTarget(user, target):
        """Is the person a contributor to bugs in `target`?

        Return True if the user has any bugs assigned to him in the
        context of a specific target, either directly or by team
        participation.

        :user: The user doing the search. Private bugs that this
        user doesn't have access to won't be included in the
        count.

        :target: An object providing `IBugTarget` to search within.
        """

    def autoSubscribeToMailingList(mailinglist, requester=None):
        """Subscribe this person to a mailing list.

        This method takes the user's mailing list auto-subscription
        setting into account, and it may or may not result in a list
        subscription.  It will only subscribe the user to the mailing
        list if all of the following conditions are met:

          * The mailing list is not None.
          * The mailing list is in an unusable state.
          * The user is not already subscribed.
          * The user has a preferred address set.
          * The user's auto-subscribe preference is ALWAYS, or
          * The user's auto-subscribe preference is ON_REGISTRATION,
            and the requester is either themself or None.

        This method will not raise exceptions if any of the above are
        not true.  If you want these problems to raise exceptions
        consider using `IMailinglist.subscribe()` directly.

        :param mailinglist: The list to subscribe to.  No action is
                taken if the list is None, or in an unusable state.

        :param requester: The person requesting the list subscription,
                if not the user himself.  The default assumes the user
                themself is making the request.

        :return: True if the user was subscribed, false if they weren't.
        """

    @operation_parameters(
        name=TextLine(required=True, constraint=name_validator))
    @operation_returns_entry(Interface) # Really IArchive.
    @export_read_operation()
    def getPPAByName(name):
        """Return a PPA with the given name if it exists.

        :param name: A string with the exact name of the ppa being looked up.
        :raises: `NoSuchPPA` if a suitable PPA could not be found.

        :return: a PPA `IArchive` record corresponding to the name.
        """


class IPersonViewRestricted(Interface):
    """IPerson attributes that require launchpad.View permission."""

    name = exported(
        PersonNameField(
            title=_('Name'), required=True, readonly=False,
            constraint=name_validator,
            description=_(
                "A short unique name, beginning with a lower-case "
                "letter or number, and containing only letters, "
                "numbers, dots, hyphens, or plus signs.")))
    displayname = exported(
        StrippedTextLine(
            title=_('Display Name'), required=True, readonly=False,
            description=_(
                "Your name as you would like it displayed throughout "
                "Launchpad. Most people use their full name here.")),
        exported_as='display_name')
    unique_displayname = TextLine(
        title=_('Return a string of the form $displayname ($name).'))
    active_member_count = Attribute(
        "The number of real people who are members of this team.")
    # activemembers.value_type.schema will be set to IPerson once
    # IPerson is defined.
    activemembers = exported(
        doNotSnapshot(
            CollectionField(
                title=_("List of members with ADMIN or APPROVED status"),
                value_type=Reference(schema=Interface))),
        exported_as='members')
    adminmembers = exported(
        doNotSnapshot(
            CollectionField(
                title=_("List of this team's admins."),
                value_type=Reference(schema=Interface))),
        exported_as='admins')
    all_member_count = Attribute(
        "The total number of real people who are members of this team, "
        "including subteams.")
    allmembers = exported(
        doNotSnapshot(
            CollectionField(
                title=_("All participants of this team."),
                description=_(
                    "List of all direct and indirect people and teams who, "
                    "one way or another, are a part of this team. If you "
                    "want a method to check if a given person is a member "
                    "of a team, you should probably look at "
                    "IPerson.inTeam()."),
                value_type=Reference(schema=Interface))),
        exported_as='participants')
    approvedmembers = doNotSnapshot(
        Attribute("List of members with APPROVED status"))
    deactivated_member_count = Attribute("Number of deactivated members")
    deactivatedmembers = exported(
        doNotSnapshot(
            CollectionField(
                title=_(
                    "All members whose membership is in the "
                    "DEACTIVATED state"),
                value_type=Reference(schema=Interface))),
        exported_as='deactivated_members')
    expired_member_count = Attribute("Number of EXPIRED members.")
    expiredmembers = exported(
        doNotSnapshot(
            CollectionField(
                title=_("All members whose membership is in the "
                        "EXPIRED state"),
                value_type=Reference(schema=Interface))),
        exported_as='expired_members')
    inactivemembers = doNotSnapshot(
        Attribute(
            "List of members with EXPIRED or DEACTIVATED status"))
    inactive_member_count = Attribute("Number of inactive members")
    invited_members = exported(
        doNotSnapshot(
            CollectionField(
                title=_("All members whose membership is "
                        "in the INVITED state"),
                value_type=Reference(schema=Interface))))

    invited_member_count = Attribute("Number of members with INVITED status")
    member_memberships = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Active TeamMemberships for this object's members."),
                description=_(
                    "Active TeamMemberships are the ones with the ADMIN or "
                    "APPROVED status.  The results are ordered using "
                    "Person.sortingColumns."),
                readonly=True, required=False,
                value_type=Reference(schema=ITeamMembership))),
        exported_as='members_details')
    pendingmembers = doNotSnapshot(
        Attribute(
            "List of members with INVITED or PROPOSED status"))
    proposedmembers = exported(
        doNotSnapshot(
            CollectionField(
                title=_("All members whose membership is in the "
                        "PROPOSED state"),
                value_type=Reference(schema=Interface))),
        exported_as='proposed_members')
    proposed_member_count = Attribute("Number of PROPOSED members")

    mapped_participants_count = Attribute(
        "The number of mapped participants")
    unmapped_participants = doNotSnapshot(
        CollectionField(
            title=_("List of participants with no coordinates recorded."),
            value_type=Reference(schema=Interface)))
    unmapped_participants_count = Attribute(
        "The number of unmapped participants")

    def getMappedParticipants(limit=None):
        """List of participants with coordinates.

        :param limit: The optional maximum number of items to return.
        :return: A list of `IPerson` objects
        """

    def getMappedParticipantsBounds():
        """Return a dict of the bounding longitudes latitudes, and centers.

        This method cannot be called if there are no mapped participants.

        :return: a dict containing: min_lat, min_lng, max_lat, max_lng,
            center_lat, and center_lng
        """

    def getMembersWithPreferredEmails(include_teams=False):
        """Returns a result set of persons with precached addresses.

        Persons or teams without preferred email addresses are not included.
        """

    def getMembersWithPreferredEmailsCount(include_teams=False):
        """Returns the count of persons/teams with preferred emails."""

    def getDirectAdministrators():
        """Return this team's administrators.

        This includes all direct members with admin rights and also
        the team owner. Note that some other persons/teams might have admin
        privilege by virtue of being a member of a team with admin rights.
        """

    @operation_parameters(status=copy_field(ITeamMembership['status']))
    @operation_returns_collection_of(Interface) # Really IPerson
    @export_read_operation()
    def getMembersByStatus(status, orderby=None):
        """Return the people whose membership on this team match :status:.

        If no orderby is provided, Person.sortingColumns is used.
        """


class IPersonEditRestricted(Interface):
    """IPerson attributes that require launchpad.Edit permission."""

    @call_with(requester=REQUEST_USER)
    @operation_parameters(team=copy_field(ITeamMembership['team']))
    @export_write_operation()
    def join(team, requester=None, may_subscribe_to_list=True):
        """Join the given team if its subscriptionpolicy is not RESTRICTED.

        Join the given team according to the policies and defaults of that
        team:

        - If the team subscriptionpolicy is OPEN, the user is added as
          an APPROVED member with a NULL TeamMembership.reviewer.
        - If the team subscriptionpolicy is MODERATED, the user is added as
          a PROPOSED member and one of the team's administrators have to
          approve the membership.

        If may_subscribe_to_list is True, then also attempt to
        subscribe to the team's mailing list, depending on the list
        status and the person's auto-subscribe settings.

        :param requester: The person who requested the membership on
            behalf of a team or None when a person requests the
            membership for himself.

        :param may_subscribe_to_list: If True, also try subscribing to
            the team mailing list.
        """

    @operation_parameters(team=copy_field(ITeamMembership['team']))
    @export_write_operation()
    def leave(team):
        """Leave the given team.

        If there's a membership entry for this person on the given team and
        its status is either APPROVED or ADMIN, we change the status to
        DEACTIVATED and remove the relevant entries in teamparticipation.

        Teams cannot call this method because they're not allowed to
        login and thus can't 'leave' another team. Instead, they have their
        subscription deactivated (using the setMembershipData() method) by
        a team administrator.
        """

    @operation_parameters(
        visible=copy_field(ILocationRecord['visible'], required=True))
    @export_write_operation()
    def setLocationVisibility(visible):
        """Specify the visibility of a person's location and time zone."""

    def setMembershipData(person, status, reviewer, expires=None,
                          comment=None):
        """Set the attributes of the person's membership on this team.

        Set the status, dateexpires, reviewer and comment, where reviewer is
        the user responsible for this status change and comment is the comment
        left by the reviewer for the change.

        This method will ensure that we only allow the status transitions
        specified in the TeamMembership spec. It's also responsible for
        filling/cleaning the TeamParticipation table when the transition
        requires it.
        """

    @call_with(reviewer=REQUEST_USER)
    @operation_parameters(
        person=copy_field(ITeamMembership['person']),
        status=copy_field(ITeamMembership['status']),
        comment=Text(required=False))
    @export_write_operation()
    def addMember(person, reviewer, status=TeamMembershipStatus.APPROVED,
                  comment=None, force_team_add=False,
                  may_subscribe_to_list=True):
        """Add the given person as a member of this team.

        :param person: If the given person is already a member of this
            team we'll simply change its membership status. Otherwise a new
            TeamMembership is created with the given status.

        :param reviewer: The user who made the given person a member of this
            team.

        :param comment: String that will be assigned to the
            proponent_comment, reviwer_comment, or acknowledger comment.

        :param status: `TeamMembershipStatus` value must be either
            Approved, Proposed or Admin.
            If the new member is a team, the status will be changed to
            Invited unless the user is also an admin of that team.

        :param force_team_add: If the person is actually a team and
            force_team_add is False, the team will actually be invited to
            join this one. Otherwise the team is added as if it were a
            person.

        :param may_subscribe_to_list: If the person is not a team, and
            may_subscribe_to_list is True, then the person may be subscribed
            to the team's mailing list, depending on the list status and the
            person's auto-subscribe settings.

        :return: A tuple containing a boolean indicating when the
            membership status changed and the current `TeamMembershipStatus`.
            This depends on the desired status passed as an argument, the
            subscription policy and the user's priveleges.
        """

    @operation_parameters(
        team=copy_field(ITeamMembership['team']),
        comment=Text())
    @export_write_operation()
    def acceptInvitationToBeMemberOf(team, comment):
        """Accept an invitation to become a member of the given team.

        There must be a TeamMembership for this person and the given team with
        the INVITED status. The status of this TeamMembership will be changed
        to APPROVED.
        """

    @operation_parameters(
        team=copy_field(ITeamMembership['team']),
        comment=Text())
    @export_write_operation()
    def declineInvitationToBeMemberOf(team, comment):
        """Decline an invitation to become a member of the given team.

        There must be a TeamMembership for this person and the given team with
        the INVITED status. The status of this TeamMembership will be changed
        to INVITATION_DECLINED.
        """

    def renewTeamMembership(team):
        """Renew the TeamMembership for this person on the given team.

        The given team's renewal policy must be ONDEMAND and the membership
        must be active (APPROVED or ADMIN) and set to expire in less than
        DAYS_BEFORE_EXPIRATION_WARNING_IS_SENT days.
        """


class IPersonModerate(Interface):
    """IPerson attributes that require launchpad.Moderate."""

    def deactivateAllMembers(comment, reviewer):
        """Deactivate all the members of this team."""


class IPersonCommAdminWriteRestricted(Interface):
    """IPerson attributes that require launchpad.Admin permission to set."""

    visibility = exported(
        Choice(title=_("Visibility"),
               description=_(
                   "Public visibility is standard.  Private Membership "
                   "means that a team's members are hidden.  "
                   "Private means the team is completely "
                   "hidden [experimental]."),
               required=True, vocabulary=PersonVisibility,
               default=PersonVisibility.PUBLIC))


class IPersonSpecialRestricted(Interface):
    """IPerson methods that require launchpad.Special permission to use."""

    def deactivateAccount(comment):
        """Deactivate this person's Launchpad account.

        Deactivating an account means:
            - Setting its password to NULL;
            - Removing the user from all teams he's a member of;
            - Changing all his email addresses' status to NEW;
            - Revoking Code of Conduct signatures of that user;
            - Reassigning bugs/specs assigned to him;
            - Changing the ownership of products/projects/teams owned by him.

        :param comment: An explanation of why the account status changed.
        """

    def reactivate(comment, password, preferred_email):
        """Reactivate this person and its account.

        Set the account status to ACTIVE, the account's password to the given
        one and its preferred email address.

        If the person's name contains a -deactivatedaccount suffix (usually
        added by `IPerson`.deactivateAccount(), it is removed.

        :param comment: An explanation of why the account status changed.
        :param password: The user's password.
        :param preferred_email: The `EmailAddress` to set as the account's
            preferred email address. It cannot be None.
        """


class IPerson(IPersonPublic, IPersonViewRestricted, IPersonEditRestricted,
              IPersonCommAdminWriteRestricted, IPersonSpecialRestricted,
              IPersonModerate, IHasStanding, ISetLocation, IRootContext):
    """A Person."""
    export_as_webservice_entry(plural_name='people')


# Set the schemas to the newly defined interface for classes that deferred
# doing so when defined.
PersonChoice.schema = IPerson


class INewPersonForm(IPerson):
    """Interface used to create new Launchpad accounts.

    The only change with `IPerson` is a customised Password field.
    """

    password = PasswordField(
        title=_('Create password'), required=True, readonly=False)


class ITeamPublic(Interface):
    """Public attributes of a Team."""

    @invariant
    def defaultRenewalPeriodIsRequiredForSomeTeams(person):
        """Teams may specify a default renewal period.

        The team renewal period cannot be less than 1 day, and when the
        renewal policy is is 'On Demand' or 'Automatic', it cannot be None.
        """
        # The person arg is a zope.formlib.form.FormData instance.
        # Instead of checking 'not person.isTeam()' or 'person.teamowner',
        # we check for a field in the schema to identify this as a team.
        try:
            renewal_policy = person.renewal_policy
        except NoInputData:
            # This is not a team.
            return

        renewal_period = person.defaultrenewalperiod
        automatic, ondemand = [TeamMembershipRenewalPolicy.AUTOMATIC,
                               TeamMembershipRenewalPolicy.ONDEMAND]
        cannot_be_none = renewal_policy in [automatic, ondemand]
        if ((renewal_period is None and cannot_be_none)
            or (renewal_period is not None and renewal_period <= 0)):
            raise Invalid(
                'You must specify a default renewal period greater than 0.')

    teamdescription = exported(
        Text(title=_('Team Description'), required=False, readonly=False,
             description=_(
                "Details about the team's work, highlights, goals, "
                "and how to contribute. Use plain text, paragraphs are "
                "preserved and URLs are linked in pages.")),
        exported_as='team_description')

    subscriptionpolicy = exported(
        Choice(title=_('Subscription policy'),
               vocabulary=TeamSubscriptionPolicy,
               default=TeamSubscriptionPolicy.MODERATED, required=True,
               description=_(
                   "'Moderated' means all subscriptions must be approved. "
                   "'Open' means any user can join without approval. "
                   "'Restricted' means new members can be added only by a "
                   "team administrator.")),
        exported_as='subscription_policy')

    renewal_policy = exported(
        Choice(title=_("When someone's membership is about to expire, "
                       "notify them and"),
               required=True, vocabulary=TeamMembershipRenewalPolicy,
               default=TeamMembershipRenewalPolicy.NONE))

    defaultmembershipperiod = exported(
        Int(title=_('Subscription period'), required=False,
            description=_(
                "Number of days a new subscription lasts before expiring. "
                "You can customize the length of an individual subscription "
                "when approving it. Leave this empty or set to 0 for "
                "subscriptions to never expire.")),
        exported_as='default_membership_period')

    defaultrenewalperiod = exported(
        Int(title=_('Renewal period'), required=False,
            description=_(
                "Number of days a subscription lasts after being renewed. "
                "You can customize the lengths of individual renewals, but "
                "this is what's used for auto-renewed and user-renewed "
                "memberships.")),
        exported_as='default_renewal_period')

    defaultexpirationdate = Attribute(
        "The date, according to team's default values, in which a newly "
        "approved membership will expire.")

    defaultrenewedexpirationdate = Attribute(
        "The date, according to team's default values, in "
        "which a just-renewed membership will expire.")


class ITeam(IPerson, ITeamPublic):
    """ITeam extends IPerson.

    The teamowner should never be None.
    """
    export_as_webservice_entry('team')

    # Logo, Mugshot and displayname are here so that they can have a
    # description on a Team which is different to the description they have on
    # a Person.
    logo = copy_field(
        IPerson['logo'], default_image_resource='/@@/team-logo',
        description=_(
            "An image of exactly 64x64 pixels that will be displayed in "
            "the heading of all pages related to the team. Traditionally "
            "this is a logo, a small picture or a personal mascot. It "
            "should be no bigger than 50kb in size."))

    mugshot = copy_field(
        IPerson['mugshot'], default_image_resource='/@@/team-mugshot',
        description=_(
            "A large image of exactly 192x192 pixels, that will be displayed "
            "on the team page in Launchpad. It "
            "should be no bigger than 100kb in size. "))

    displayname = copy_field(
        IPerson['displayname'],
        description=_(
            "This team's name as you would like it displayed throughout "
            "Launchpad."))


class IPersonSet(Interface):
    """The set of Persons."""
    export_as_webservice_collection(IPerson)

    title = Attribute('Title')

    @collection_default_content()
    def getTopContributors(limit=50):
        """Return the top contributors in Launchpad, up to the given limit."""

    def isNameBlacklisted(name):
        """Is the given name blacklisted by Launchpad Administrators?"""

    def createPersonAndEmail(
            email, rationale, comment=None, name=None, displayname=None,
            password=None, passwordEncrypted=False,
            hide_email_addresses=False, registrant=None):
        """Create and return an `IPerson` and `IEmailAddress`.

        The newly created EmailAddress will have a status of NEW and will be
        linked to the newly created Person.

        An Account is also created, but this will change in the future!

        If the given name is None, we generate a unique nickname from the
        email address given.

        :param email: The email address, as text.
        :param rationale: An item of `PersonCreationRationale` to be used as
            the person's creation_rationale.
        :param comment: A comment explaining why the person record was
            created (usually used by scripts which create them automatically).
            Must be of the following form: "when %(action_details)s"
            (e.g. "when the foo package was imported into Ubuntu Breezy").
        :param name: The person's name.
        :param displayname: The person's displayname.
        :param password: The person's password.
        :param passwordEncrypted: Whether or not the given password is
            encrypted.
        :param registrant: The user who created this person, if any.
        :param hide_email_addresses: Whether or not Launchpad should hide the
            person's email addresses from other users.
        :raises InvalidName: When the given name is not valid.
        :raises InvalidEmailAddress: When the given email is not valid.
        :raises NameAlreadyTaken: When the given name is already in use.
        :raises EmailAddressAlreadyTaken: When the given email is already in
            use.
        :raises NicknameGenerationError: When no name is provided and we can't
            generate a nickname from the given email address.
        """

    def createPersonWithoutEmail(
        name, rationale, comment=None, displayname=None, registrant=None):
        """Create and return an `IPerson` without using an email address.

        :param name: The person's name.
        :param comment: A comment explaining why the person record was
            created (usually used by scripts which create them automatically).
            Must be of the following form: "when %(action_details)s"
            (e.g. "when the foo package was imported into Ubuntu Breezy").
        :param displayname: The person's displayname.
        :param registrant: The user who created this person, if any.
        :raises InvalidName: When the passed name isn't valid.
        :raises NameAlreadyTaken: When the passed name has already been
            used.
        """

    def ensurePerson(email, displayname, rationale, comment=None,
                     registrant=None):
        """Make sure that there is a person in the database with the given
        email address. If necessary, create the person, using the
        displayname given.

        The comment must be of the following form: "when %(action_details)s"
        (e.g. "when the foo package was imported into Ubuntu Breezy").

        If the email address is already registered and bound to an
        `IAccount`, the created `IPerson` will have 'hide_email_addresses'
        flag set to True.

        XXX sabdfl 2005-06-14: this should be extended to be similar or
        identical to the other person creation argument lists, so we can
        call it and create a full person if needed. Email would remain the
        deciding factor, we would not try and guess if someone existed based
        on the displayname or other arguments.
        """

    @call_with(teamowner=REQUEST_USER)
    @rename_parameters_as(
        displayname='display_name', teamdescription='team_description',
        subscriptionpolicy='subscription_policy',
        defaultmembershipperiod='default_membership_period',
        defaultrenewalperiod='default_renewal_period')
    @operation_parameters(
        subscriptionpolicy=Choice(
            title=_('Subscription policy'), vocabulary=TeamSubscriptionPolicy,
            required=False, default=TeamSubscriptionPolicy.MODERATED))
    @export_factory_operation(
        ITeam, ['name', 'displayname', 'teamdescription',
                'defaultmembershipperiod', 'defaultrenewalperiod'])
    def newTeam(teamowner, name, displayname, teamdescription=None,
                subscriptionpolicy=TeamSubscriptionPolicy.MODERATED,
                defaultmembershipperiod=None, defaultrenewalperiod=None):
        """Create and return a new Team with given arguments."""

    def get(personid):
        """Return the person with the given id or None if it's not found."""

    @operation_parameters(
        email=TextLine(required=True, constraint=email_validator))
    @operation_returns_entry(IPerson)
    @export_read_operation()
    def getByEmail(email):
        """Return the person with the given email address.

        Return None if there is no person with the given email address.
        """

    def getByName(name, ignore_merged=True):
        """Return the person with the given name, ignoring merged persons if
        ignore_merged is True.

        Return None if there is no person with the given name.
        """

    def getByAccount(account):
        """Return the `IPerson` with the given account, or None."""

    def updateStatistics(ztm):
        """Update statistics caches and commit."""

    def peopleCount():
        """Return the number of non-merged persons in the database as
           of the last statistics update.
        """

    def teamsCount():
        """Return the number of teams in the database as of the last
           statistics update.
        """

    @operation_parameters(
        text=TextLine(title=_("Search text"), default=u""))
    @operation_returns_collection_of(IPerson)
    @export_read_operation()
    def find(text=""):
        """Return all non-merged Persons and Teams whose name, displayname or
        email address match <text>.

        The results will be ordered using the default ordering specified in
        Person._defaultOrder.

        While we don't have Full Text Indexes in the emailaddress table, we'll
        be trying to match the text only against the beginning of an email
        address.
        """

    @operation_parameters(
        text=TextLine(
            title=_("Search text"), default=u""),
        created_after=Datetime(
            title=_("Created after"), required=False),
        created_before=Datetime(
            title=_("Created before"), required=False),
        )
    @operation_returns_collection_of(IPerson)
    @export_read_operation()
    def findPerson(text="", exclude_inactive_accounts=True,
                   must_have_email=False,
                   created_after=None, created_before=None):
        """Return all non-merged Persons with at least one email address whose
        name, displayname or email address match <text>.

        If text is an empty string, all persons with at least one email
        address will be returned.

        The results will be ordered using the default ordering specified in
        Person._defaultOrder.

        If exclude_inactive_accounts is True, any accounts whose
        account_status is any of INACTIVE_ACCOUNT_STATUSES will not be in the
        returned set.

        If must_have_email is True, only people with one or more email
        addresses are returned.

        While we don't have Full Text Indexes in the emailaddress table, we'll
        be trying to match the text only against the beginning of an email
        address.

        If created_before or created_after are not None, they are used to
        restrict the search to the dates provided.
        """

    @operation_parameters(
        text=TextLine(title=_("Search text"), default=u""))
    @operation_returns_collection_of(IPerson)
    @export_read_operation()
    def findTeam(text=""):
        """Return all Teams whose name, displayname or email address
        match <text>.

        The results will be ordered using the default ordering specified in
        Person._defaultOrder.

        While we don't have Full Text Indexes in the emailaddress table, we'll
        be trying to match the text only against the beginning of an email
        address.
        """

    def latest_teams(limit=5):
        """Return the latest teams registered, up to the limit specified."""

    def merge(from_person, to_person):
        """Merge a person/team into another.

        The old person/team (from_person) will be left as an atavism.

        When merging two person entries, from_person can't have email
        addresses associated with.

        When merging teams, from_person must have no IMailingLists
        associated with and no active members. If it has active members,
        though, it's possible to have them deactivated before the merge by
        passing deactivate_members=True. In that case the user who's
        performing the merge must be provided as well.

        We are not yet game to delete the `from_person` entry from the
        database yet. We will let it roll for a while and see what cruft
        develops. -- StuartBishop 20050812
        """

    def getValidPersons(persons):
        """Get all the Persons that are valid.

        This method is more effective than looking at
        Person.is_valid_person_or_team, since it avoids issuing one DB
        query per person. It queries the ValidPersonOrTeamCache table,
        issuing one query for all the person records. This makes the
        method useful for filling the ORM cache, so that checks to
        .is_valid_person won't issue any DB queries.

        XXX: This method exists mainly to fill the ORM cache for
             ValidPersonOrTeamCache. It would be better to add a column
             to the Person table. If we do that, this method can go
             away. Bug 221901. -- Bjorn Tillenius, 2008-04-25
        """

    def getPeopleWithBranches(product=None):
        """Return the people who have branches.

        :param product: If supplied, only people who have branches in the
            specified product are returned.
        """

    def getSubscribersForTargets(targets, recipients=None):
        """Return the set of subscribers for `targets`.

        :param targets: The sequence of targets for which to get the
                        subscribers.
        :param recipients: An optional instance of
                           `BugNotificationRecipients`.
                           If present, all found subscribers will be
                           added to it.
        """

    def updatePersonalStandings():
        """Update the personal standings of some people.

        Personal standing controls whether a person can post to a mailing list
        they are not a member of without moderation.  A person starts out with
        Unknown standing.  Once they have at least one message approved for
        three different lists, this method will bump their standing to Good.
        If a person's standing is already Good, or Poor or Excellent, no
        change to standing is made.
        """

    def cacheBrandingForPeople(people):
        """Prefetch Librarian aliases and content for personal images."""


class IRequestPeopleMerge(Interface):
    """This schema is used only because we want a very specific vocabulary."""

    dupe_person = Choice(
        title=_('Duplicated Account'), required=True,
        vocabulary='PersonAccountToMerge',
        description=_(
            "The e-mail address or Launchpad ID of the account you want to "
            "merge into yours."))


class IAdminPeopleMergeSchema(Interface):
    """The schema used by the admin merge people page."""

    dupe_person = Choice(
        title=_('Duplicated Person'), required=True,
        vocabulary='AdminMergeablePerson',
        description=_("The duplicated person found in Launchpad."))

    target_person = Choice(
        title=_('Target Person'), required=True,
        vocabulary='AdminMergeablePerson',
        description=_("The person to be merged on."))


class IAdminTeamMergeSchema(Interface):
    """The schema used by the admin merge teams page."""

    dupe_person = Choice(
        title=_('Duplicated Team'), required=True, vocabulary='ValidTeam',
        description=_("The duplicated team found in Launchpad."))

    target_person = Choice(
        title=_('Target Team'), required=True, vocabulary='ValidTeam',
        description=_("The team to be merged on."))


class IObjectReassignment(Interface):
    """The schema used by the object reassignment page."""

    owner = PublicPersonChoice(title=_('New'), vocabulary='ValidOwner',
                               required=True)


class ITeamReassignment(Interface):
    """The schema used by the team reassignment page."""

    owner = PublicPersonChoice(
        title=_('New'), vocabulary='ValidTeamOwner', required=True)


class ITeamCreation(ITeam):
    """An interface to be used by the team creation form.

    We need this special interface so we can allow people to specify a contact
    email address for a team upon its creation.
    """

    contactemail = TextLine(
        title=_("Contact Email Address"), required=False, readonly=False,
        description=_(
            "This is the email address we'll send all notifications to this "
            "team. If no contact address is chosen, notifications directed "
            "to this team will be sent to all team members. After finishing "
            "the team creation, a new message will be sent to this address "
            "with instructions on how to finish its registration."),
        constraint=validate_new_team_email)


class TeamContactMethod(EnumeratedType):
    """The method used by Launchpad to contact a given team."""

    HOSTED_LIST = Item("""
        The Launchpad mailing list for this team

        Notifications directed to this team are sent to its Launchpad-hosted
        mailing list.
        """)

    NONE = Item("""
        Each member individually

        Notifications directed to this team will be sent to each of its
        members.
        """)

    EXTERNAL_ADDRESS = Item("""
        Another e-mail address

        Notifications directed to this team are sent to the contact address
        specified.
        """)


class ITeamContactAddressForm(Interface):

    contact_address = TextLine(
        title=_("Contact Email Address"), required=False, readonly=False)

    contact_method = Choice(
        title=_("How do people contact these team's members?"),
        required=True, vocabulary=TeamContactMethod)


class JoinNotAllowed(Exception):
    """User is not allowed to join a given team."""


class ImmutableVisibilityError(Exception):
    """A change in team membership visibility is not allowed."""


class InvalidName(Exception):
    """The name given for a person is not valid."""


class NameAlreadyTaken(Exception):
    """The name given for a person is already in use by other person."""
    webservice_error(409)


class NoSuchPerson(NameLookupFailed):
    """Raised when we try to look up an IPerson that doesn't exist."""

    _message_prefix = "No such person"


# Fix value_type.schema of IPersonViewRestricted attributes.
for name in ['allmembers', 'activemembers', 'adminmembers', 'proposedmembers',
             'invited_members', 'deactivatedmembers', 'expiredmembers',
             'unmapped_participants']:
    IPersonViewRestricted[name].value_type.schema = IPerson

IPersonPublic['sub_teams'].value_type.schema = ITeam
IPersonPublic['super_teams'].value_type.schema = ITeam
# XXX: salgado, 2008-08-01: Uncomment these when teams_*participated_in are
# exported again.
# IPersonPublic['teams_participated_in'].value_type.schema = ITeam
# IPersonPublic['teams_indirectly_participated_in'].value_type.schema = ITeam

# Fix schema of operation parameters. We need zope.deferredimport!
params_to_fix = [
    # XXX: salgado, 2008-08-01: Uncomment these when they are exported again.
    # (IPersonPublic['findPathToTeam'], 'team'),
    # (IPersonPublic['inTeam'], 'team'),
    (IPersonEditRestricted['join'], 'team'),
    (IPersonEditRestricted['leave'], 'team'),
    (IPersonEditRestricted['addMember'], 'person'),
    (IPersonEditRestricted['acceptInvitationToBeMemberOf'], 'team'),
    (IPersonEditRestricted['declineInvitationToBeMemberOf'], 'team'),
    ]
for method, name in params_to_fix:
    method.queryTaggedValue(
        'lazr.restful.exported')['params'][name].schema = IPerson

# Fix schema of operation return values.
# XXX: salgado, 2008-08-01: Uncomment when findPathToTeam is exported again.
# IPersonPublic['findPathToTeam'].queryTaggedValue(
#     'lazr.webservice.exported')['return_type'].value_type.schema = IPerson
IPersonViewRestricted['getMembersByStatus'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['return_type'].value_type.schema = IPerson

# Fix schema of ITeamMembership fields.  Has to be done here because of
# circular dependencies.
for name in ['team', 'person', 'last_changed_by']:
    ITeamMembership[name].schema = IPerson

# Fix schema of ITeamParticipation fields.  Has to be done here because of
# circular dependencies.
for name in ['team', 'person']:
    ITeamParticipation[name].schema = IPerson

# Thank circular dependencies once again.
IIrcID['person'].schema = IPerson
IJabberID['person'].schema = IPerson
IWikiName['person'].schema = IPerson
IEmailAddress['person'].schema = IPerson
