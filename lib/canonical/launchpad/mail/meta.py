# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

from zope.app.component.metaconfigure import handler, utility
from zope.app.mail.interfaces import IMailer
from zope.app.mail.metadirectives import IMailerDirective
from zope.interface import Interface
from zope.schema import ASCII, Bool

from canonical.launchpad.interfaces import IMailBox
from canonical.launchpad.mail.stub import StubMailer, TestMailer
from canonical.launchpad.mail.mailbox import TestMailBox, POP3MailBox



class ITestMailBoxDirective(Interface):
    """Configure a mail box which operates on test_emails."""

def testMailBoxHandler(_context):
    utility(_context, IMailBox, component=TestMailBox())


class IPOP3MailBoxDirective(Interface):
    """Configure a mail box which interfaces to a POP3 server."""
    host = ASCII(
            title=u"Host",
            description=u"Host name of the POP3 server.",
            required=True,
            )
    
    user = ASCII(
            title=u"User",
            description=u"User name to connect to the POP3 server with.",
            required=True,
            )
    
    password = ASCII(
            title=u"Password",
            description=u"Password to connect to the POP3 server with.",
            required=True,
            )

    ssl = Bool(
            title=u"SSL",
            description=u"Use SSL.",
            required=False,
            default=False)

def pop3MailBoxHandler(_context, host, user, password, ssl=False):
    utility(
        _context, IMailBox, component=POP3MailBox( host, user, password, ssl))


class IStubMailerDirective(IMailerDirective):
    from_addr = ASCII(
            title=u"From Address",
            description=u"All outgoing emails will use this email address",
            required=True,
            )
    to_addr = ASCII(
            title=u"To Address",
            description=
                u"All outgoing emails will be redirected to this email address",
            required=True,
            )
    mailer = ASCII(
            title=u"Mailer to use",
            description=u"""\
                Which registered mailer to use, such as configured with
                the smtpMailer or sendmailMailer directives""",
                required=False,
                default='sendmail',
                )
    rewrite = Bool(
            title=u"Rewrite headers",
            description=u"""\
                    If true, headers are rewritten in addition to the
                    destination address in the envelope. May me required
                    to bypass spam filters.""",
            required=False,
            default=False,
            )


def stubMailerHandler(
        _context, name, from_addr, to_addr, mailer='sendmail', rewrite=False
        ):
    _context.action(
           discriminator = ('utility', IMailer, name),
           callable = handler,
           args = (
               'provideUtility',
               IMailer, StubMailer(from_addr, [to_addr], mailer, rewrite), name,
               )
           )


class ITestMailerDirective(IMailerDirective):
    pass

def testMailerHandler(_context, name):
    _context.action(
            discriminator = ('utility', IMailer, name),
            callable = handler,
            args = (
                'Utilities', 'provideUtility', IMailer, TestMailer(), name,
                )
            )
