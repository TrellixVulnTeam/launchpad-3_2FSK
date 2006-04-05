# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""Interfaces specific to mail handling."""

__metaclass__ = type
__all__ = ['IWeaklyAuthenticatedPrincipal',
           'ISignedMessage',
           'IMailHandler',
           'EmailProcessingError',
           'IEmailCommand',
           'IBugEmailCommand',
           'IBugTaskEmailCommand',
           'IBugEditEmailCommand',
           'IBugTaskEditEmailCommand']

from zope.i18nmessageid import MessageIDFactory
_ = MessageIDFactory('launchpad')
from zope.interface import Interface, Attribute
from zope.schema import ASCII, Bool


class IWeaklyAuthenticatedPrincipal(Interface):
    """The principal has been weakly authenticated.

    At the moment it means that the user was authenticated simply by
    looking at the From address in an email.
    """


class ISignedMessage(Interface):
    """A message that's possibly signed with an OpenPGP key.

    If the message wasn't signed, all attributes will be None.
    """

    def __getitem__(name):
        """Returns the message header with the given name."""

    signedMessage = Attribute("The part that was signed, represented "
                              "as an email.Message.")

    signedContent = ASCII(title=_("Signed Content"),
                          description=_("The text that was signed."))

    signature = ASCII(title=_("Signature"),
                      description=_("The OpenPGP signature used to sign "
                                    "the message."))

    parsed_string = Attribute(
        "The string that was parsed to create the SignedMessage.")


class IMailHandler(Interface):
    """Handles incoming mail sent to a specific email domain.

    For example, in email address '1@bugs.launchpad.ubuntu.com',
    'bugs.launchpad.ubuntu.com' is the email domain.

    The handler should be registered as a named utility, with the domain
    it handles as the name.
    """

    allow_anonymous = Bool(
        title=u"Allow anonymous interactions",
        description=u"The handler can handle emails from persons not"
                    " registered in Launchpad (which will result in an"
                    " anonymous interaction being set up.")

    def process(signed_msg, to_address, filealias, log=None):
        """Processes a ISignedMessage

        The 'to_address' is the address the mail was sent to.
        The 'filealias' is an ILibraryFileAlias.
        The 'log' is the logger to be used.

        Return True if the mesage was processed, otherwise False.
        """


class EmailProcessingError(Exception):
    """Something went wrong while processing an email command."""


class IEmailCommand(Interface):
    """An email command.

    Email commands can be embedded in mails sent to Launchpad. For
    example in comments to bugs sent via email, you can include:

      private yes

    in order to make the bug private.
    """

    def execute(context):
        """Execute the command in a context."""

    def __str__():
        """Return a textual representation of the command and its arguments."""


class IBugEmailCommand(IEmailCommand):
    """An email command specific to getting or creating a bug."""

    def execute(parsed_msg, filealias):
        """Either create or get an exiting bug.

        If a bug is created, parsed_msg and filealias will be used to
        create the initial comment of the bug.

        The bug and an event is returned as a two-tuple.
        """


class IBugTaskEmailCommand(IEmailCommand):
    """An email command specific to getting or creating a bug task."""

    def execute(bug):
        """Either create or get an exiting bug task.

        The bug task and an event is returned as a two-tuple.
        """


class IBugEditEmailCommand(IEmailCommand):
    """An email command specific to editing a bug."""

    def execute(bug, current_event):
        """Execute the command in the context of the bug.

        The modified bug and an event is returned.
        """


class IBugTaskEditEmailCommand(IEmailCommand):
    """An email command specific to editing a bug task."""

    def execute(bugtask, current_event):
        """Execute the command in the context of the bug task.

        The modified bug task and an event is returned.
        """
