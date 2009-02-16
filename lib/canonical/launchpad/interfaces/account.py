# Copyright 2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213
"""Account interfaces."""

__metaclass__ = type

__all__ = [
        'AccountStatus',
        'AccountCreationRationale',
        'IAccount',
        'IAccountPrivate',
        'IAccountPublic',
        'IAccountSet',
        'INACTIVE_ACCOUNT_STATUSES',
        ]


from zope.interface import Interface
from zope.schema import Choice, Datetime, Int, Text, TextLine

from canonical.launchpad import _
from canonical.launchpad.fields import StrippedTextLine, PasswordField
from canonical.lazr import DBEnumeratedType, DBItem
from canonical.lazr.fields import Reference


class AccountStatus(DBEnumeratedType):
    """The status of an account."""

    NOACCOUNT = DBItem(10, """
        Unactivated account

        The account has not yet been activated.
        """)

    ACTIVE = DBItem(20, """
        Active account

        The account is active.
        """)

    DEACTIVATED = DBItem(30, """
        Deactivated account

        The account has been deactivated by the account's owner.
        """)

    SUSPENDED = DBItem(40, """
        Suspended Launchpad account

        The account has been suspended by a Launchpad admin.
        """)


INACTIVE_ACCOUNT_STATUSES = [
    AccountStatus.DEACTIVATED, AccountStatus.SUSPENDED]


class AccountCreationRationale(DBEnumeratedType):
    """The rationale for the creation of a given account.
    
    These statuses are seeded from PersonCreationRationale, as our
    initial accounts where split from the Person table. A number of the
    creation rationales only make sense in this historical context (eg.
    importing bugs into Launchpad no longer needs to create Account records).
    """

    UNKNOWN = DBItem(1, """
        Unknown

        The reason for the creation of this account is unknown.
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
        Created by the owner himself, coming from Launchpad.

        Somebody was navigating through Launchpad and at some point decided to
        create an account.
        """)

    OWNER_CREATED_SHIPIT = DBItem(9, """
        Created by the owner himself, coming from Shipit.

        Somebody went to one of the shipit sites to request Ubuntu CDs and was
        directed to Launchpad to create an account.
        """)

    OWNER_CREATED_UBUNTU_WIKI = DBItem(10, """
        Created by the owner himself, coming from the Ubuntu wiki.

        Somebody went to the Ubuntu wiki and was directed to Launchpad to
        create an account.
        """)

    USER_CREATED = DBItem(11, """
        Created by a user to represent a person which does not use Launchpad.

        A user wanted to reference a person which is not a Launchpad user, so
        he created this "placeholder" profile.
        """)

    OWNER_CREATED_UBUNTU_SHOP = DBItem(12, """
        Created by the owner himself, coming from the Ubuntu Shop.

        Somebody went to the Ubuntu Shop and was directed to Launchpad to
        create an account.
        """)

    OWNER_CREATED_UNKNOWN_TRUSTROOT = DBItem(13, """
        Created by the owner himself, coming from unknown OpenID consumer.

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


class IAccountPublic(Interface):
    """Public information on an `IAccount`."""
    id = Int(title=_('ID'), required=True, readonly=True)

    displayname = StrippedTextLine(
        title=_('Display Name'), required=True, readonly=False,
        description=_("Your name as you would like it displayed."))

    status = Choice(
        title=_("The status of this account"), required=True,
        readonly=False, vocabulary=AccountStatus)

    # We should use schema=IEmailAddress here, but we can't because that would
    # cause circular dependencies.
    preferredemail = Reference(
        title=_("Preferred email address"),
        description=_("The preferred email address for this person. "
                      "The one we'll use to communicate with them."),
        readonly=True, required=False, schema=Interface)


class IAccountPrivate(Interface):
    """Private information on an `IAccount`."""
    date_created = Datetime(
        title=_('Date Created'), required=True, readonly=True)

    creation_rationale = Choice(
        title=_("Rationale for this account's creation."), required=True,
        readonly=True, values=AccountCreationRationale.items)

    date_status_set = Datetime(
        title=_('Date status last modified.'),
        required=True, readonly=False)

    status_comment = Text(
        title=_("Why are you deactivating your account?"),
        required=False, readonly=False)

    openid_identifier = TextLine(
        title=_("Key used to generate opaque OpenID identities."),
        readonly=True, required=True)

    # XXX sinzui 2008-09-04 bug=264783:
    # Remove this attribute.
    new_openid_identifier = TextLine(
        title=_("Key used to generate New opaque OpenID identities."),
        readonly=True, required=True)

    password = PasswordField(
        title=_("Password."), readonly=False, required=True)


class IAccount(IAccountPublic, IAccountPrivate):
    """Interface describing an `Account`."""


class IAccountSet(Interface):
    """Creation of and access to `IAccount` providers."""

    def new(rationale, displayname, openid_mnemonic=None,
            password=None, password_is_encrypted=False):
        """Create a new `IAccount`.

        :param rationale: An `AccountStatus` value.
        :param displayname: The user's display name.
        :param openid_mnemonic: The human-readable component in the account's
            openid_identifier.
        :param password: A password.
        :param password_is_encrypted: If True, the password parameter has
            already been encrypted using the `IPasswordEncryptor` utility.
            If False, the password will be encrypted automatically.

        :return: The newly created `IAccount` provider.
        """

    def getByEmail(email):
        """Return the `IAccount` linked to the given email address.

        :param email: A string, not an `IEmailAddress` provider.

        :return: An `IAccount`, or None if the given email address
        does not exist in the database or is not linked to an `IAccount`.
        """

    def getByOpenIDIdentifier(openid_identity):
        """Return the `IAccount` with the given OpenID identifier.

         :param open_identifier: An ascii compatible string that is either
             the old or new openid_identifier that belongs to an account.
         :return: An `IAccount`, or None if the the openid_identifier does
             not belong to an account.
         """

    def createOpenIDIdentifier(mnemonic):
        """Return a unique openid_identifier for OpenID identity URIs.

        The identifier takes for form of 'nnn/mnemonic', where 'nnn' is
        a random three digit sequence.

        :param mnemonic: A string token that a user can remember.
            eg. his user name.
        :return: a unique string that no other user has, nor has ever been
            used in the past.
        """
