
# Copyright 2004 Canonical Ltd.  All rights reserved.
"""Run all of the pagetests, in priority order.

Set up the test data in the database first.
"""
__metaclass__ = type

import doctest
import os
import re
import unittest

from BeautifulSoup import BeautifulSoup, Comment, NavigableString

from zope.app.testing.functional import HTTPCaller, SimpleCookie
from zope.testbrowser.testing import Browser

from canonical.functional import PageTestDocFileSuite, SpecialOutputChecker
from canonical.testing import PageTestLayer


here = os.path.dirname(os.path.realpath(__file__))


class UnstickyCookieHTTPCaller(HTTPCaller):
    """HTTPCaller subclass that do not carry cookies across requests.

    HTTPCaller propogates cookies between subsequent requests.
    This is a nice feature, except it triggers a bug in Launchpad where
    sending both Basic Auth and cookie credentials raises an exception
    (Bug 39881).
    """
    def __init__(self, *args, **kw):
        if kw.get('debug'):
            self._debug = True
            del kw['debug']
        else:
            self._debug = False
        HTTPCaller.__init__(self, *args, **kw)
    def __call__(self, *args, **kw):
        if self._debug:
            import pdb; pdb.set_trace()
        try:
            return HTTPCaller.__call__(self, *args, **kw)
        finally:
            self.resetCookies()

    def resetCookies(self):
        self.cookies = SimpleCookie()


class DuplicateIdError(Exception):
    """Raised by find_tag_by_id if more than one element has the given id."""


def find_tag_by_id(content, id):
    """Find and return the tag with the given ID"""
    soup = BeautifulSoup(content)
    elements_with_id = soup.findAll(attrs={'id': id})
    if not elements_with_id:
        return None
    elif len(elements_with_id) == 1:
        return elements_with_id[0]
    else:
        raise DuplicateIdError(
            'Found %d elements with id %r' % (len(elements_with_id), id))


def find_tags_by_class(content, class_):
    """Find and return the tags matching the given class(s)"""
    match_classes = set(class_.split())
    def class_matcher(value):
        if value is None: return False
        classes = set(value.split())
        return match_classes.issubset(classes)
    soup = BeautifulSoup(content)
    return soup.findAll(attrs={'class': class_matcher})


def find_portlet(content, name):
    """Find and return the portlet with the given title. Sequences of
    whitespace are considered equivalent to one space, and beginning and
    ending whitespace is also ignored.
    """
    whitespace_re = re.compile('\s+')
    name = whitespace_re.sub(' ', name.strip())
    for portlet in find_tags_by_class(content, 'portlet'):
        if portlet.find('h2'):
            portlet_title = portlet.find('h2').renderContents()
            if name == whitespace_re.sub(' ', portlet_title.strip()):
                return portlet
    return None


def find_main_content(content):
    """Find and return the main content area of the page"""
    soup = BeautifulSoup(content)
    tag = soup.find(attrs={'id': 'maincontent'}) # standard page with portlets
    if tag:
        return tag
    return soup.find(attrs={'id': 'singlecolumn'}) # single-column page


def extract_text(soup):
    """Return the text stripped of all tags.

    >>> soup = BeautifulSoup(
    ...    '<html><!-- comment --><h1>Title</h1><p>foo bar</p></html>')
    >>> extract_text(soup)
    u'Titlefoo bar'
    """
    # XXX Tim Penhey 22-01-2007
    # At the moment this does not nicely give whitespace between
    # tags that would have visual separation when rendered.
    # eg. <p>foo</p><p>bar</p>
    result = u''
    for node in soup:
        if isinstance(node, Comment):
            pass
        elif isinstance(node, NavigableString):
            result = result + unicode(node)
        else:
            result = result + extract_text(node)
    return result


# XXX cprov 20070207: This function seems to be more specific to a particular
# product (soyuz) than the rest. Maybe it belongs to somewhere else.
def parse_relationship_section(content):
    """Parser package relationship section.

    See package-relationship-pages.txt and related.
    """
    soup = BeautifulSoup(content)
    section = soup.find('ul')
    whitespace_re = re.compile('\s+')
    for li in section.findAll('li'):
        if li.a:
            link = li.a
            content = whitespace_re.sub(' ', link.string.strip())
            url = link['href']
            print 'LINK: "%s" -> %s' % (content, url)
        else:
            content = whitespace_re.sub(' ', li.string.strip())
            print 'TEXT: "%s"' % content


def setUpGlobs(test):
    # Our tests report being on a different port.
    test.globs['http'] = UnstickyCookieHTTPCaller(port=9000)

    # Set up our Browser objects with handleErrors set to False, since
    # that gives a tracebacks instead of unhelpful error messages.
    def setupBrowser(auth=None):
        browser = Browser()
        browser.handleErrors = False
        if auth is not None:
            browser.addHeader("Authorization", auth)
        return browser

    test.globs['setupBrowser'] = setupBrowser
    test.globs['browser'] = setupBrowser()
    test.globs['anon_browser'] = setupBrowser()
    test.globs['user_browser'] = setupBrowser(
        auth="Basic no-priv@canonical.com:test")
    test.globs['admin_browser'] = setupBrowser(
        auth="Basic foo.bar@canonical.com:test")

    test.globs['find_tag_by_id'] = find_tag_by_id
    test.globs['find_tags_by_class'] = find_tags_by_class
    test.globs['find_portlet'] = find_portlet
    test.globs['find_main_content'] = find_main_content
    test.globs['extract_text'] = extract_text
    test.globs['parse_relationship_section'] = parse_relationship_section


class PageStoryTestCase(unittest.TestCase):
    """A test case that represents a pagetest story

    This is achieved by holding a testsuite for the story, and
    delegating responsiblity for most methods to it.
    We want this to be a TestCase instance and not a TestSuite
    instance to be compatible with various test runners that
    filter tests - they generally ignore test suites and may
    select individual tests - but stories cannot be split up.
    """

    layer = PageTestLayer

    def __init__(self, name, storysuite):
        """Create a PageTest story from the given suite.

        :param name: an identifier for the story, such as the directory
            containing the tests.
        :param storysuite: a test suite containing the tests to be run
            as a story.
        """
        # we do not run the super __init__ because we are not using any of
        # the base classes functionality, and we'd just have to give it a
        # meaningless method.
        self._description = name
        self._suite = storysuite

    def countTestCases(self):
        return self._suite.countTestCases()

    def shortDescription(self):
        return "pagetest: %s" % self._description

    def id(self):
        return self.shortDescription()

    def __str__(self):
        return self.shortDescription()

    def __repr__(self):
        return "<%s name=%s>" % (self.__class__.__name__, self._description)

    def run(self, result=None):
        if result is None:
            result = self.defaultTestResult()
        PageTestLayer.startStory()
        try:
            # TODO RBC 20060117 we can hook in pre and post story actions
            # here much more tidily (and in self.debug too)
            # - probably via self.setUp and self.tearDown
            self._suite.run(result)
        finally:
            PageTestLayer.endStory()

    def debug(self):
        self._suite.debug()


# This function name doesn't follow our standard naming conventions,
# but does follow the convention of the other doctest related *Suite()
# functions.

def PageTestSuite(storydir, package=None):
    """Create a suite of page tests for files found in storydir.

    :param storydir: the directory containing the page tests.
    :param package: the package to resolve storydir relative to.  Defaults
        to the caller's package.

    The unnumbered page tests will be added to the suite individually,
    while the numbered tests will be run together as a story.
    """
    # we need to normalise the package name here, because it
    # involves checking the parent stack frame.  Otherwise the
    # files would be looked up relative to this module.
    package = doctest._normalize_module(package)
    abs_storydir = doctest._module_relative_path(package, storydir)

    filenames = set(filename
                    for filename in os.listdir(abs_storydir)
                    if filename.lower().endswith('.txt'))
    numberedfilenames = set(filename for filename in filenames
                            if len(filename) > 4
                            and filename[:2].isdigit()
                            and filename[2] == '-')
    unnumberedfilenames = filenames - numberedfilenames

    # A predictable order is important, even if it remains officially
    # undefined for un-numbered filenames.
    numberedfilenames = sorted(numberedfilenames)
    unnumberedfilenames = sorted(unnumberedfilenames)

    # Add unnumbered tests to the suite individually.
    checker = SpecialOutputChecker()
    suite = PageTestDocFileSuite(
        package=package, checker=checker,
        layer=PageTestLayer, setUp=setUpGlobs,
        *[os.path.join(storydir, filename)
          for filename in unnumberedfilenames])

    # Add numbered tests to the suite as a single story.
    storysuite = PageTestDocFileSuite(
        package=package, checker=checker,
        layer=PageTestLayer, setUp=setUpGlobs,
        *[os.path.join(storydir, filename)
          for filename in numberedfilenames])
    suite.addTest(PageStoryTestCase(abs_storydir, storysuite))

    return suite


def test_suite():
    pagetestsdir = os.path.join('..', 'pagetests')
    abs_pagetestsdir = os.path.abspath(
        os.path.normpath(os.path.join(here, pagetestsdir)))

    stories = [
        os.path.join(pagetestsdir, d)
        for d in os.listdir(abs_pagetestsdir)
        if not d.startswith('.') and
           os.path.isdir(os.path.join(abs_pagetestsdir, d))
        ]
    stories.sort()

    suite = unittest.TestSuite()

    for storydir in stories:
        suite.addTest(PageTestSuite(storydir))
    suite.addTest(doctest.DocTestSuite())
    return suite

if __name__ == '__main__':
    r = unittest.TextTestRunner().run(test_suite())
