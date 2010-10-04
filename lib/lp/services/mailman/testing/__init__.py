# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
"""Test helpers for mailman integration."""

__metaclass__ = type
__all__ = []

from contextlib import contextmanager
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import shutil

from Mailman import (
    MailList,
    Message,
    mm_cfg,
    )
from Mailman.Queue import XMLRPCRunner

from canonical.testing import DatabaseFunctionalLayer

from lp.registry.tests.mailinglists_helper import MailingListXMLRPCTestProxy
from lp.testing import TestCaseWithFactory


def get_mailing_list_api_test_proxy():
    return MailingListXMLRPCTestProxy(context=None, request=None)


@contextmanager
def fake_mailinglist_api_proxy():
    original_get_proxy = XMLRPCRunner.get_mailing_list_api_proxy
    XMLRPCRunner.get_mailing_list_api_proxy = get_mailing_list_api_test_proxy
    try:
        yield
    finally:
        XMLRPCRunner.get_mailing_list_api_proxy = original_get_proxy


class MailmanTestCase(TestCaseWithFactory):
    """TestCase with factory and mailman support."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(MailmanTestCase, self).setUp()
        # Replace the xmlrpc proxy with a fast wrapper of the real view.
        self.useContext(fake_mailinglist_api_proxy())

    def tearDown(self):
        super(MailmanTestCase, self).tearDown()
        self.cleanMailmanList(self.mm_list)

    def makeMailmanList(self, lp_mailing_list):
        # This utility is based on mailman/tests/TestBase.py.
        mlist = MailList.MailList()
        team = lp_mailing_list.team
        owner_email = team.teamowner.preferredemail.email
        mlist.Create(team.name, owner_email, 'password')
        mlist.host_name = 'lists.launchpad.dev'
        mlist.web_page_url = 'http://lists.launchpad.dev/mailman/'
        mlist.Save()
        mlist.addNewMember(owner_email)
        return mlist

    def cleanMailmanList(self, mlist):
        # This utility is based on mailman/tests/TestBase.py.
        mlist.Unlock()
        listname = mlist.internal_name()
        paths = [
            'lists/%s',
            'archives/private/%s',
            'archives/private/%s.mbox',
            'archives/public/%s',
            'archives/public/%s.mbox',
            ]
        for dirtmpl in paths:
            list_dir = os.path.join(mm_cfg.VAR_PREFIX, dirtmpl % listname)
            if os.path.islink(list_dir):
                os.unlink(list_dir)
            elif os.path.isdir(list_dir):
                shutil.rmtree(list_dir)

    def makeMailmanMessage(self, mm_list, sender, subject, content,
                           mime_type='plain', attachment=None):
        # Make a Mailman Message.Message.
        if isinstance(sender, (list, tuple)):
            sender = ', '.join(sender)
        message = MIMEMultipart()
        message['from'] = sender
        message['to'] = mm_list.getListAddress()
        message['subject'] = subject
        message['message-id'] = self.getUniqueString()
        message.attach(MIMEText(content, mime_type))
        if attachment is not None:
            # Rewrap the text message in a multipart message and add the
            # attachment.
            message.attach(attachment)
        mm_message = email.message_from_string(
            message.as_string(), Message.Message)
        return mm_message
