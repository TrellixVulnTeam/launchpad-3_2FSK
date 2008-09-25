# Copyright 2007 Canonical Ltd.  All rights reserved.

"""A global pipeline handler for determining Launchpad membership."""


import xmlrpclib

from Mailman import Errors
from Mailman import mm_cfg
from Mailman.Logging.Syslog import syslog


def process(mlist, msg, msgdata):
    """Discard the message if it doesn't come from a Launchpad member."""
    if msgdata.get('approved'):
        return
    # Ask Launchpad whether the sender is a Launchpad member.  If not, discard
    # the message with extreme prejudice, but log this.
    sender = msg.get_sender()
    # Check with Launchpad about whether the sender is a member or not.  If we
    # can't talk to Launchpad, I believe it's better to let the message get
    # posted to the list than to discard or hold it.
    is_member = True
    proxy = xmlrpclib.ServerProxy(mm_cfg.XMLRPC_URL)
    # This will fail if we can't talk to Launchpad.  That's okay though
    # because Mailman's IncomingRunner will re-queue the message and re-start
    # processing at this handler.
    is_member = proxy.isRegisteredInLaunchpad(sender)
    # Some automated processes will also send messages to the mailing list.
    # For example, if the list is a contact address for a team and that team
    # is the contact address for a project's answer tracker, an automated
    # message will be sent from Launchpad.  Check for a header that indicates
    # this was a Launchpad generated message.
    if msg['x-launchpad-shared-secret'] == mm_cfg.LAUNCHPAD_SHARED_SECRET:
        # Delete the header so it doesn't leak to end users.
        del msg['x-launchpad-shared-secret']
        # Since this message is coming from Launchpad, pre-approve it.  Yes,
        # this could be spoofed, but there's really no other way (currently)
        # to do it.
        msgdata['approved'] = True
        return
    # This handler can just return if the sender is a member of Launchpad.
    if is_member:
        return
    # IncomingRunner already posts the Message-ID to the logs/vette for
    # discarded messages, so we only need to add a little more detail here.
    syslog('vette', 'Sender is not a Launchpad member: %s', sender)
    raise Errors.DiscardMessage
