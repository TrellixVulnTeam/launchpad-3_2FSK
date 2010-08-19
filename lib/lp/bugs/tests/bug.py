# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper functions for bug-related doctests and pagetests."""

import re
import textwrap

from datetime import datetime, timedelta
from operator import attrgetter
from pytz import UTC

from BeautifulSoup import BeautifulSoup

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.launchpad.ftests import sync
from canonical.launchpad.testing.pages import (
    extract_text, find_tag_by_id, find_main_content, find_tags_by_class,
    print_table)
from lp.bugs.interfaces.bug import CreateBugParams, IBugSet
from lp.bugs.interfaces.bugtask import BugTaskStatus, IBugTaskSet
from lp.bugs.interfaces.bugwatch import IBugWatchSet
from lp.registry.interfaces.distribution import IDistributionSet
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.product import IProductSet
from lp.registry.interfaces.sourcepackagename import (
    ISourcePackageNameSet)


def print_direct_subscribers(bug_page):
    """Print the direct subscribers listed in a portlet."""
    print_subscribers(bug_page, 'subscribers-direct')


def print_also_notified(bug_page):
    """Print the structural subscribers listed in a portlet."""
    print 'Also notified:'
    print_subscribers(bug_page, 'subscribers-indirect')


def print_subscribers_from_duplicates(bug_page):
    """Print the subscribers from duplicates listed in a portlet."""
    print 'From duplicates:'
    print_subscribers(bug_page, 'subscribers-from-duplicates')


def print_subscribers(bug_page, subscriber_list_id):
    """Print the subscribers listed in the subscriber portlet."""
    subscriber_list = find_tag_by_id(bug_page, subscriber_list_id)
    if subscriber_list is None:
        # No list with this ID (as can happen if there are
        # no indirect subscribers), so just print an empty string.
        print ""
    else:
        anchors = subscriber_list.findAll('a')
        for anchor in anchors:
            sub_display = extract_text(anchor)
            if anchor.has_key('title'):
                sub_display += (' (%s)' % anchor['title'])
            print sub_display


def print_bug_affects_table(content, highlighted_only=False):
    """Print information about all the bug tasks in the 'affects' table.

        :param highlighted_only: Only print the highlighted row
    """
    main_content = find_main_content(content)
    affects_table = main_content.first('table', {'class': 'listing'})
    if highlighted_only:
        tr_attrs = {'class': 'highlight'}
    else:
        tr_attrs = {}
    tr_tags = affects_table.tbody.findAll(
        'tr', attrs=tr_attrs, recursive=False)
    for tr in tr_tags:
        if tr.td.table:
            # Don't print the bugtask edit form.
            continue
        print extract_text(tr)


def print_remote_bugtasks(content):
    """Print the remote bugtasks of this bug.

    For each remote bugtask, print the target and the bugwatch.
    """
    affects_table = find_tags_by_class(content, 'listing')[0]
    for span in affects_table.findAll('span'):
        for key, value in span.attrs:
            if 'bug-remote' in value:
                target = extract_text(span.findAllPrevious('td')[-2])
                print target, extract_text(span.findNext('a'))


def print_bugs_list(content, list_id):
    """Print the bugs list with the given ID.

    Right now this is quite simplistic, in that it just extracts the
    text from the element specified by list_id. If the bug listing
    becomes more elaborate then this function will be the place to
    cope with it.
    """
    bugs_list = find_tag_by_id(content, list_id).findAll(
        None, {'class': 'similar-bug'})
    for node in bugs_list:
        print extract_text(node)


def print_bugtasks(text, show_heat=None):
    """Print all the bugtasks in the text."""
    print '\n'.join(extract_bugtasks(text, show_heat=show_heat))


def extract_bugtasks(text, show_heat=None):
    """Extracts a list of strings for all the bugtasks in the text."""
    main_content = find_main_content(text)
    table = main_content.find('table', {'id': 'buglisting'})
    if table is None:
        return []
    rows = []
    for tr in table('tr'):
        if tr.td is not None:
            row_text = extract_text(tr)
            if show_heat:
                for img in tr.findAll('img'):
                    mo = re.search('^/@@/bug-heat-([0-4]).png$', img['src'])
                    if mo:
                        flames = int(mo.group(1))
                        heat_text = flames * '*' + (4 - flames) * '-'
                        row_text += '\n' + heat_text
            rows.append(row_text)
    return rows


def create_task_from_strings(bug, owner, product, watchurl=None):
    """Create a task, optionally linked to a watch."""
    bug = getUtility(IBugSet).get(bug)
    product = getUtility(IProductSet).getByName(product)
    owner = getUtility(IPersonSet).getByName(owner)
    task = getUtility(IBugTaskSet).createTask(bug, owner, product=product)
    if watchurl:
        [watch] = getUtility(IBugWatchSet).fromText(watchurl, bug, owner)
        task.bugwatch = watch
    return task


def create_bug_from_strings(
    distribution, sourcepackagename, owner, summary, description,
    status=None):
    """Create and return a bug."""
    distroset = getUtility(IDistributionSet)
    distribution = distroset.getByName(distribution)

    # XXX: kiko 2008-02-01: would be really great if spnset consistently
    # offered getByName.
    spnset = getUtility(ISourcePackageNameSet)
    sourcepackagename = spnset.queryByName(sourcepackagename)

    personset = getUtility(IPersonSet)
    owner = personset.getByName(owner)

    bugset = getUtility(IBugSet)
    params = CreateBugParams(owner, summary, description, status=status)
    params.setBugTarget(distribution=distribution,
                        sourcepackagename=sourcepackagename)
    return bugset.createBug(params)


def update_task_status(task_id, person, status):
    """Update a bugtask status."""
    task = getUtility(IBugTaskSet).get(task_id)
    person = getUtility(IPersonSet).getByName(person)
    task.transitionToStatus(status, person)


def create_old_bug(
    title, days_old, target, status=BugTaskStatus.INCOMPLETE,
    with_message=True, external_bugtracker=None, assignee=None,
    milestone=None, duplicateof=None):
    """Create an aged bug.

    :title: A string. The bug title for testing.
    :days_old: An int. The bug's age in days.
    :target: A BugTarkget. The bug's target.
    :status: A BugTaskStatus. The status of the bug's single bugtask.
    :with_message: A Bool. Whether to create a reply message.
    :external_bugtracker: An external bug tracker which is watched for this
        bug.
    """
    no_priv = getUtility(IPersonSet).getByEmail('no-priv@canonical.com')
    params = CreateBugParams(
        owner=no_priv, title=title, comment='Something is broken.')
    bug = target.createBug(params)
    if duplicateof is not None:
        bug.markAsDuplicate(duplicateof)
    sample_person = getUtility(IPersonSet).getByEmail('test@canonical.com')
    if with_message is True:
        bug.newMessage(
            owner=sample_person, subject='Something is broken.',
            content='Can you provide more information?')
    bugtask = bug.bugtasks[0]
    bugtask.transitionToStatus(
        status, sample_person)
    if assignee is not None:
        bugtask.transitionToAssignee(assignee)
    bugtask.milestone = milestone
    if external_bugtracker is not None:
        getUtility(IBugWatchSet).createBugWatch(bug=bug, owner=sample_person,
            bugtracker=external_bugtracker, remotebug='1234')
    date = datetime.now(UTC) - timedelta(days=days_old)
    removeSecurityProxy(bug).date_last_updated = date
    sync_bugtasks([bugtask])
    return bugtask


def summarize_bugtasks(bugtasks):
    """Summarize a sequence of bugtasks."""
    bugtaskset = getUtility(IBugTaskSet)
    expirable_bugtasks = list(bugtaskset.findExpirableBugTasks(
        config.malone.days_before_expiration, getUtility(ILaunchpadCelebrities).janitor))
    print 'ROLE  EXPIRE  AGE  STATUS  ASSIGNED  DUP  MILE  REPLIES'
    for bugtask in sorted(set(bugtasks), key=attrgetter('id')):
        if len(bugtask.bug.bugtasks) == 1:
            title = bugtask.bug.title
        else:
            title = bugtask.target.name
        print '%s  %s  %s  %s  %s  %s  %s  %s' % (
            title,
            bugtask in expirable_bugtasks,
            (datetime.now(UTC) - bugtask.bug.date_last_updated).days,
            bugtask.status.title,
            bugtask.assignee is not None,
            bugtask.bug.duplicateof is not None,
            bugtask.milestone is not None,
            bugtask.bug.messages.count() == 1)


def sync_bugtasks(bugtasks):
    """Sync the bugtask and its bug to the database."""
    if not isinstance(bugtasks, list):
        bugtasks = [bugtasks]
    for bugtask in bugtasks:
        sync(bugtask)
        sync(bugtask.bug)


def print_upstream_linking_form(browser):
    """Print the upstream linking form found via +choose-affected-product.

    The resulting output will look something like:
    (*) A checked option
        [A related text field]
    ( ) An unchecked option
    """
    soup = BeautifulSoup(browser.contents)

    link_upstream_how_radio_control = browser.getControl(
        name='field.link_upstream_how')
    link_upstream_how_buttons =  soup.findAll(
        'input', {'name': 'field.link_upstream_how'})

    wrapper = textwrap.TextWrapper(width=65, subsequent_indent='    ')
    for button in link_upstream_how_buttons:
        # Print the radio button.
        label = button.findParent('label')
        if label is None:
            label = soup.find('label', {'for': button['id']})
        if button.get('value') in link_upstream_how_radio_control.value:
            print wrapper.fill('(*) %s' % extract_text(label))
        else:
            print wrapper.fill('( ) %s' % extract_text(label))
        # Print related text field, if found. Assumes that the text
        # field is in the same table row as the radio button.
        text_field = button.findParent('tr').find('input', {'type':'text'})
        if text_field is not None:
            text_control = browser.getControl(name=text_field.get('name'))
            print '    [%s]' % text_control.value.ljust(10)


def print_bugfilters_portlet_unfilled(browser, target):
    """Print the raw, unfilled contents of the bugfilters portlet.

    This is the contents before any actual data has been fetched.
    (The portlet is normally populated with data by a separate
    javascript call, to avoid delaying the overall page load.  Use
    print_bugfilters_portlet_filled() to test the populated portlet.)

    :param browser  browser from which to extract the content.
    :param target   entity from whose bugs page to fetch the portlet
                    (e.g., http://bugs.launchpad.dev/TARGET/...)
    """
    browser.open(
        'http://bugs.launchpad.dev/%s/+portlet-bugfilters' % target)
    table = BeautifulSoup(browser.contents).find('table', 'bug-links')
    tbody_info, tbody_links = table('tbody')
    print_table(tbody_info)
    for link in tbody_links('a'):
        text = extract_text(link)
        if len(text) > 0:
            print "%s\n  --> %s" % (text, link['href'])


def print_bugfilters_portlet_filled(browser, target):
    """Print the filled-in contents of the bugfilters portlet.

    This is the contents after the actual data has been fetched.
    (The portlet is normally populated with data by a separate
    javascript call, to avoid delaying the overall page load.  Use
    print_bugfilters_portlet_unfilled() to test the unpopulated
    portlet.)

    :param browser  browser from which to extract the content.
    :param target   entity from whose bugs page to fetch the portlet
                    (e.g., http://bugs.launchpad.dev/TARGET/...)
    """
    browser.open(
        'http://bugs.launchpad.dev'
        '/%s/+bugtarget-portlet-bugfilters-stats' % target)
    table = BeautifulSoup('<table>%s</table>' % browser.contents)
    print_table(table)


def print_bug_tag_anchors(anchors):
    """The the bug tags in the iterable of anchors."""
    for anchor in anchors:
        href = anchor['href']
        if href != '+edit' and '/+help/tag-help.html' not in href:
            print anchor['class'], anchor.contents[0]
