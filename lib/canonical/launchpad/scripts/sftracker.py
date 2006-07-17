# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Sourceforge.net Tracker import logic.

This code relies on the output of Frederik Lundh's Sourceforge tracker
screen-scraping tools:

  http://effbot.org/zone/sandbox-sourceforge.htm
"""

__metaclass__ = type

__all__ = [
    'Tracker',
    'TrackerImporter'
    ]

from cStringIO import StringIO
import datetime
import logging
import os
import re
import sys
import time

import pytz

# use cElementTree if it is available ...
try:
    import cElementTree as ET
except:
    import elementtree.ElementTree as ET

from zope.component import getUtility
from zope.app.content_types import guess_content_type

from canonical.lp.dbschema import (
    BugTaskImportance, BugTaskStatus, BugAttachmentType)
from canonical.database.constants import UTC_NOW
from canonical.launchpad.interfaces import (
    IBugSet, IBugActivitySet, IBugAttachmentSet, IEmailAddressSet,
    ILaunchpadCelebrities, ILibraryFileAliasSet, IMessageSet,
    IMilestoneSet, IPersonSet, NotFoundError)

logger = logging.getLogger('canonical.launchpad.scripts.sftracker')

# when accessed anonymously, Sourceforge returns dates in this timezone:
SOURCEFORGE_TZ = pytz.timezone('US/Pacific')
UTC = pytz.timezone('UTC')

def parse_date(datestr):
    if datestr in ['', 'No updates since submission']:
        return None
    year, month, day, hour, minute = time.strptime(datestr,
                                                   '%Y-%m-%d %H:%M')[:5]
    dt = datetime.datetime(year, month, day, hour, minute)
    return SOURCEFORGE_TZ.localize(dt).astimezone(UTC)

def gettext(elem):
    if elem is not None:
        value = elem.text.strip()
        # exported data contains escaped HTML entities.
        value = value.replace('&quot;', '"')
        value = value.replace('&apos;', '\'')
        value = value.replace('&lt;', '<')
        value = value.replace('&gt;', '>')
        value = value.replace('&amp;', '&')
        return value
    else:
        return ''


class TrackerAttachment:
    """An attachment associated with a SF tracker item"""

    def __init__(self, attachment_node):
        self.file_id = attachment_node.get('file_id')
        self._content_type = gettext(attachment_node.find('content_type'))
        self.filename = gettext(attachment_node.find('title'))
        if not self.filename:
            self.filename = 'untitled'
        self.title = gettext(attachment_node.find('description'))
        if not self.title:
            self.title = self.filename
        self.date = parse_date(gettext(attachment_node.find('date')))
        self.sender = gettext(attachment_node.find('sender'))
        self.data = gettext(attachment_node.find('data')).decode('base-64')

    @property
    def is_patch(self):
        """True if this attachment is a patch

        As the sourceforge tracker does not differentiate between
        patches and other attachments, we need to use heuristics to
        differentiate.
        """
        return (self.filename.endswith('patch') or
                self.filename.endswith('diff'))

    @property
    def content_type(self):
        # always treat patches as text/plain
        if self.is_patch:
            return 'text/plain'

        # if the content type isn't just arbitrary data, trust it.
        if (self._content_type is not None and
            self._content_type != 'application/octet-stream'):
            return self._content_type

        # otherwise, guess it from the data
        content_type, encoding = guess_content_type(
            name=self.filename, body=self.data)
        return content_type

class TrackerItem:
    """An SF tracker item"""

    def __init__(self, item_node, summary_node):
        self.item_id = item_node.get('id')
        self.datecreated = parse_date(gettext(
            item_node.find('date_submitted')))
        self.date_last_updated = parse_date(gettext(
            item_node.find('date_last_updated')))
        self.title = gettext(item_node.find('summary'))
        self.description = gettext(item_node.find('description'))
        self.category = gettext(item_node.find('category'))
        self.group = gettext(item_node.find('group'))
        self.priority = gettext(item_node.find('priority'))
        self.resolution = gettext(item_node.find('resolution'))
        self.status = gettext(item_node.find('status'))
        # We get these two from the summary file because it contains user IDs
        self.reporter = gettext(summary_node.find('submitted_by'))
        self.assignee = gettext(summary_node.find('assigned_to'))
        # initial comment:
        self.comments = [(self.datecreated, self.reporter, self.description)]
        # remaining comments ...
        for comment_node in item_node.findall('comment'):
            dt = parse_date(gettext(comment_node.find('date')))
            sender = gettext(comment_node.find('sender'))
            description = gettext(comment_node.find('description'))
            # remove recognised headers from description
            lines = description.splitlines(True)
            while lines and (lines[0].startswith('Date:') or
                             lines[0].startswith('Sender:') or
                             lines[0].startswith('Logged In:') or
                             lines[0].startswith('user_id=')
                             or lines[0].isspace()):
                del lines[0]
            description = ''.join(lines)
            self.comments.append((dt, sender, description))
        # attachments
        self.attachments = [TrackerAttachment(node)
                            for node in item_node.findall('attachment')]

    @property
    def lp_importance(self):
        """The Launchpad importance value for this item"""
        try:
            priority = int(self.priority)
        except ValueError:
            return BugTaskImportance.UNTRIAGED
        # make priority >= 9 CRITICAL
        if priority >= 9:
            return BugTaskImportance.CRITICAL
        elif priority >= 7:
            return BugTaskImportance.HIGH
        elif priority >= 4:
            return BugTaskImportance.MEDIUM
        else:
            return BugTaskImportance.LOW

    @property
    def lp_status(self):
        if self.status == 'Open':
            if self.resolution == 'Accepted':
                return BugTaskStatus.CONFIRMED
            else:
                return BugTaskStatus.UNCONFIRMED
        elif self.status == 'Closed':
            if self.resolution in ['Fixed', 'None']:
                return BugTaskStatus.FIXRELEASED
            else:
                return BugTaskStatus.REJECTED
        elif self.status == 'Deleted':
            # XXXX: 2006-07-10 jamesh
            # do we ever get exported bugs with this status?
            return BugTaskStatus.UNCONFIRMED
        elif self.status == 'Pending':
            if self.resolution in ['Fixed', 'None']:
                return BugTaskStatus.FIXCOMMITTED
            else:
                return BugTaskStatus.INPROGRESS
        raise AssertionError('Unhandled item status: (%s, %s)'
                             % (self.status, self.resolution))


class Tracker:
    """An SF tracker"""

    def __init__(self, dumpfile, dumpdir=None):
        """Create a Tracker instance.

        Dumpfile is a dump of the tracker as generated by xml-export.py
        Dumpdir contains the individual tracker item XML files.
        """
        self.data = ET.parse(dumpfile).getroot()
        if dumpdir is None:
            self.dumpdir = os.path.join(os.path.dirname(dumpfile),
                                        self.data.get('id'))
        else:
            self.dumpdir = dumpdir

    def __iter__(self):
        for item_node in self.data.findall('item'):
            # open the summary file
            summary_file = os.path.join(self.dumpdir,
                                        'item-%s.xml' % item_node.get('id'))
            summary_node = ET.parse(summary_file)
            yield TrackerItem(item_node, summary_node)


class TrackerImporter:
    """Helper class for importing SF tracker items into Launchpad"""

    def __init__(self, product, verify_users=False):
        self.product = product
        self.verify_users = verify_users
        self._person_id_cache = {}
        self.bug_importer = getUtility(ILaunchpadCelebrities).bug_importer

    def person(self, userid):
        """Get the Launchpad user corresponding to the given SF user ID"""
        if userid in [None, '', 'nobody']:
            return None
        
        email = '%s@users.sourceforge.net' % userid

        launchpad_id = self._person_id_cache.get(userid)
        if launchpad_id is not None:
            person = getUtility(IPersonSet).get(launchpad_id)
            if person is not None and person.merged is not None:
                person = None
        else:
            person = None

        if person is None:
            person = getUtility(IPersonSet).getByEmail(email)
            if person is None:
                logger.debug('creating person for %s' % email)
                person = getUtility(IPersonSet).ensurePerson(
                    email=email, displayname=None)
            self._person_id_cache[userid] = person.id

        # if we are auto-verifying new accounts, make sure the person
        # has a preferred email
        if self.verify_users and person.preferredemail is None:
            emailaddr = getUtility(IEmailAddressSet).getByEmail(email)
            assert emailaddr is not None
            person.setPreferredEmail(emailaddr)

        return person

    def getMilestone(self, name):
        if name in ['None', '', None]:
            return None

        # turn milestone into a Launchpad name
        name = re.sub(r'[^a-z0-9\+\.\-]', '-', name.lower())
        if not name[0].isalpha():
            name = 'x-' + name

        milestone = self.product.getMilestone(name)
        if milestone is not None:
            return milestone

        # pick a series to attach the milestone.  Pick 'trunk' or
        # 'main' if they exist.  Otherwise pick the first.
        for series in self.product.serieslist:
            if series.name in ['trunk', 'main']:
                break
        else:
            series = self.product.serieslist[0]

        return series.newMilestone(name)

    def createMessage(self, subject, date, userid, text):
        """Create an IMessage for a particular comment."""
        if not text.strip():
            text = '<empty comment>'
        owner = self.person(userid)
        if owner is None:
            owner = self.bug_importer
        return getUtility(IMessageSet).fromText(subject, text, owner, date)

    def importTrackerItem(self, item):
        """Import an SF tracker item into Launchpad.

        We identify SF tracker items by setting their nick name to
        'sf1234' where the SF item id was 1234.  If such a bug already
        exists, the import is skipped.
        """
        logger.info('Handling Sourceforge tracker item #%s', item.item_id)
        
        nickname = 'sf%s' % item.item_id
        try:
            bug = getUtility(IBugSet).getByNameOrID(nickname)
        except NotFoundError:
            bug = None

        if bug is not None:
            logger.info('Sourceforge bug %s has already been imported as #%d',
                        item.item_id, bug.id)
            return bug

        comments_by_date_and_user = {}
        comments = item.comments[:]
        
        date, userid, text = comments.pop(0)
        msg = self.createMessage(item.title, date, userid, text)
        comments_by_date_and_user[(date, userid)] = msg

        owner = self.person(item.reporter)
        # LP bugs can't have no reporter ...
        if owner is None:
            owner = self.bug_importer

        bug = getUtility(IBugSet).createBug(msg=msg,
                                            datecreated=item.datecreated,
                                            title=item.title,
                                            owner=owner,
                                            product=self.product)
        bug.name = nickname
        bugtask = bug.bugtasks[0]
        logger.info('Creating Launchpad bug #%d', bug.id)

        # attach comments and create CVE links.
        bug.findCvesInText(text)
        for (date, userid, text) in comments:
            msg = self.createMessage(bug.followup_subject(), date,
                                      userid, text)
            bug.linkMessage(msg)
            bug.findCvesInText(text)
            comments_by_date_and_user[(date, userid)] = msg

        # set up bug task
        bugtask.datecreated = item.datecreated
        bugtask.importance = item.lp_importance
        bugtask.transitionToStatus(item.lp_status)
        bugtask.transitionToAssignee(self.person(item.assignee))

        # XXXX: 2006-07-11 jamesh
        # Need to translate item.category to keywords

        # Convert group to a milestone
        bugtask.milestone = self.getMilestone(item.group)

        # Convert attachments
        for attachment in item.attachments:
            if attachment.is_patch:
                attach_type = BugAttachmentType.PATCH
            else:
                attach_type = BugAttachmentType.UNSPECIFIED

            # do we already have the message for this bug?
            msg = comments_by_date_and_user.get((attachment.date,
                                                 attachment.sender))
            if msg is None:
                msg = self.createMessage(
                    attachment.title,
                    attachment.date or UTC_NOW,
                    attachment.sender,
                    'Other attachments')
                bug.linkMessage(msg)
                comments_by_date_and_user[(attachment.date,
                                           attachment.sender)] = msg

            # upload the attachment and add to the bug.
            filealias = getUtility(ILibraryFileAliasSet).create(
                name=attachment.filename,
                size=len(attachment.data),
                file=StringIO(attachment.data),
                contentType=attachment.content_type)

            getUtility(IBugAttachmentSet).create(
                bug=bug,
                filealias=filealias,
                attach_type=attach_type,
                title=attachment.title,
                message=msg)

        # Make a note of the import in the activity log:
        getUtility(IBugActivitySet).new(
            bug=bug.id,
            datechanged=UTC_NOW,
            person=self.bug_importer,
            whatchanged='bug',
            message='Imported SF tracker item #%s' % item.item_id)

        return bug

    def importTracker(self, ztm, tracker):
        """Import bugs from the given tracker"""
        for item in tracker:
            ztm.begin()
            try:
                self.importTrackerItem(item)
            except (SystemExit, KeyboardInterrupt):
                raise
            except:
                logger.exception('Could not import item #%s', item.item_id)
                ztm.abort()
            else:
                ztm.commit()
