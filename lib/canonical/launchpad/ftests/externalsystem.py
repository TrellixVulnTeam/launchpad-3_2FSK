# Copyright 2005 Canonical Ltd.  All rights reserved.

"""Helper classes for testing ExternalSystem."""

__metaclass__ = type

import os

from canonical.malone.externalsystem import Bugzilla


def read_test_file(name):
    """Return the contents of the test file named :name:

    Test files are located in lib/canonical/launchpad/ftests/testfiles
    """
    file_path = os.path.join(os.path.dirname(__file__), 'testfiles', name)

    test_file = open(file_path, 'r')
    return test_file.read()


class TestBugzilla(Bugzilla):
    """Bugzilla ExternalSystem for use in tests.

    It overrides _getPage and _postPage, so that access to a real Bugzilla
    instance isn't needed.
    """

    # A dict all bugs in the form of $bug_id: ($status, $resolution)
    bugzilla_bugs = {
        3224: ('RESOLVED', 'FIXED'),
        328430: ('UNCONFIRMED', ''),
    }

    def _getPage(self, page):
        """GET a page.

        Only handles xml.cgi?id=1 so far.
        """
        if page == 'xml.cgi?id=1':
            return read_test_file('gnome_bugzilla_version.xml')
        else:
            raise AssertionError('Unknown page: %s' % page)

    def _postPage(self, page, form):
        """POST to the specified page.

        :form: is a dict of form variables being POSTed.

        Only handles buglist.cgi so far.
        """
        if page == 'buglist.cgi':
            buglist_xml = read_test_file('gnome_buglist.xml')
            bug_ids = str(form['bug_id']).split(',')
            bug_li_items = []
            for bug_id in bug_ids:
                bug_id = int(bug_id)
                if bug_id not in self.bugzilla_bugs:
                    #Unknown bugs aren't included in the resulting xml.
                    continue
                bug_status, bug_resolution = self.bugzilla_bugs[int(bug_id)]
                bug_item = read_test_file('gnome_bug_li_item.xml') % {
                    'bug_id': bug_id, 'status': bug_status, 
                    'resolution': bug_resolution
                    }
                bug_li_items.append(bug_item)
            return buglist_xml % {
                'bug_li_items': '\n'.join(bug_li_items),
                'page': page}
        else:
            raise AssertionError('Unknown page: %s' % page)
