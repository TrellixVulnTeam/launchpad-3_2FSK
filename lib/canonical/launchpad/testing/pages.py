# Copyright 2004-2008 Canonical Ltd.  All rights reserved.
"""Testing infrastructure for page tests."""
# Stop lint warning about not initializing TestCase parent on
# PageStoryTestCase, see the comment bellow.
# pylint: disable-msg=W0231

__metaclass__ = type

import os
import pdb
import re
import simplejson
import transaction
import sys
import unittest
import urllib

# pprint25 is a copy of pprint.py from Python 2.5, which is almost
# identical to that in 2.4 except that it resolves an ordering issue
# which makes the 2.4 version unsuitable for use in a doctest.
import pprint25

from BeautifulSoup import (
    BeautifulSoup, Comment, Declaration, NavigableString, PageElement,
    ProcessingInstruction, SoupStrainer, Tag)
from contrib.oauth import OAuthRequest, OAuthSignatureMethod_PLAINTEXT
from urlparse import urljoin

from zope.app.testing.functional import HTTPCaller, SimpleCookie
from zope.component import getUtility
from zope.proxy import ProxyBase
from zope.testbrowser.testing import Browser
from zope.testing import doctest

from canonical.launchpad.ftests import ANONYMOUS, login, login_person, logout
from canonical.launchpad.interfaces import IOAuthConsumerSet, OAUTH_REALM
from canonical.launchpad.testing import (
    LaunchpadObjectFactory, with_anonymous_login)
from canonical.launchpad.testing.systemdocs import (
    LayeredDocFileSuite, SpecialOutputChecker, strip_prefix)
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.interfaces import OAuthPermission
from canonical.launchpad.webapp.url import urlsplit
from canonical.testing import PageTestLayer


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
        super(UnstickyCookieHTTPCaller, self).__init__(*args, **kw)

    def __call__(self, *args, **kw):
        if self._debug:
            pdb.set_trace()
        try:
            return super(UnstickyCookieHTTPCaller, self).__call__(*args, **kw)
        finally:
            self.resetCookies()

    def chooseRequestClass(self, method, path, environment):
        """See `HTTPCaller`.

        This version adds the 'PATH_INFO' variable to the environment,
        because some of our factories expects it.
        """
        if 'PATH_INFO' not in environment:
            environment = dict(environment)
            environment['PATH_INFO'] = path
        return super(UnstickyCookieHTTPCaller, self).chooseRequestClass(
            method, path, environment)

    def resetCookies(self):
        self.cookies = SimpleCookie()


class WebServiceCaller:
    """A class for making calls to Launchpad web services."""

    DEV_SERVER_URL = 'http://api.launchpad.dev'
    DEFAULT_API_VERSION = 'beta'

    def __init__(self, oauth_consumer_key=None, oauth_access_key=None,
                 handle_errors=True, *args, **kwargs):
        """Create a WebServiceCaller.
        :param oauth_consumer_key: The OAuth consumer key to use.
        :param oauth_access_key: The OAuth access key to use for the request.
        :param handle_errors: Should errors raise exception or be handled by
            the publisher. Default is to let the publisher handle them.

        Other parameters are passed to the HTTPCaller used to make the calls.
        """
        if oauth_consumer_key is not None and oauth_access_key is not None:
            login(ANONYMOUS)
            self.consumer = getUtility(IOAuthConsumerSet).getByKey(
                oauth_consumer_key)
            self.access_token = self.consumer.getAccessToken(
                oauth_access_key)
            logout()
        else:
            self.consumer = None
            self.access_token = None

        self.handle_errors = handle_errors

        # Set up a delegate to make the actual HTTP calls.
        self.http_caller = UnstickyCookieHTTPCaller(*args, **kwargs)

    def getAbsoluteUrl(self, resource_path, api_version=DEFAULT_API_VERSION):
        """Convenience method for creating a url in tests.

        :param resource_path: This is the url section to be joined to hostname
                              and api version.
        :param api_version: This is the first part of the absolute
                            url after the hostname.
        """
        if resource_path.startswith('/'):
            # Prevent os.path.join() from interpreting resource_path as an
            # absolute url. This allows paths that appear consistent with urls
            # from other *.launchpad.dev virtual hosts.
            # For example:
            #   /firefox = http://launchpad.dev/firefox
            #   /firefox = http://api.launchpad.dev/beta/firefox
            resource_path = resource_path[1:]
        url_with_version = os.path.join(api_version, resource_path)
        return urljoin(self.DEV_SERVER_URL, url_with_version)

    def __call__(self, path_or_url, method='GET', data=None, headers=None,
                 api_version=DEFAULT_API_VERSION):
        path_or_url = str(path_or_url)
        if path_or_url.startswith('http:'):
            full_url = path_or_url
        else:
            full_url = self.getAbsoluteUrl(path_or_url,
                                           api_version=api_version)
        scheme, netloc, path, query, fragment = urlsplit(full_url)
        # Make an HTTP request.
        full_headers = {'Host' : netloc}
        if self.consumer is not None and self.access_token is not None:
            request = OAuthRequest.from_consumer_and_token(
                self.consumer, self.access_token, http_url = full_url,
                )
            request.sign_request(OAuthSignatureMethod_PLAINTEXT(),
                                 self.consumer, self.access_token)
            full_headers.update(request.to_header(OAUTH_REALM))
        if headers is not None:
            full_headers.update(headers)
        header_strings = ["%s: %s" % (header, str(value))
                          for header, value in full_headers.items()]
        path_and_query = path
        if len(query) != 0:
            path_and_query += '?%s' % query
        request_string = "%s %s HTTP/1.1\n%s\n" % (method, path_and_query,
                                                   "\n".join(header_strings))
        if data:
            request_string += "\n" + data

        response = self.http_caller(
            request_string, handle_errors=self.handle_errors)
        return WebServiceResponseWrapper(response)

    def get(self, path, media_type='application/json', headers=None,
            api_version=DEFAULT_API_VERSION):
        """Make a GET request."""
        full_headers = {'Accept': media_type}
        if headers is not None:
            full_headers.update(headers)
        return self(path, 'GET', headers=full_headers,
                    api_version=api_version)

    def head(self, path, headers=None,
             api_version=DEFAULT_API_VERSION):
        """Make a HEAD request."""
        return self(path, 'HEAD', headers=headers, api_version=api_version)

    def delete(self, path, headers=None,
               api_version=DEFAULT_API_VERSION):
        """Make a DELETE request."""
        return self(path, 'DELETE', headers=headers, api_version=api_version)

    def put(self, path, media_type, data, headers=None,
            api_version=DEFAULT_API_VERSION):
        """Make a PUT request."""
        return self._make_request_with_entity_body(
            path, 'PUT', media_type, data, headers, api_version=api_version)

    def post(self, path, media_type, data, headers=None,
             api_version=DEFAULT_API_VERSION):
        """Make a POST request."""
        return self._make_request_with_entity_body(
            path, 'POST', media_type, data, headers, api_version=api_version)

    def _convertArgs(self, operation_name, args):
        """Encode and convert keyword arguments."""
        args['ws.op'] = operation_name
        # To be properly marshalled all values must be strings or converted to
        # JSON.
        for key, value in args.items():
            if not isinstance(value, basestring):
                args[key] = simplejson.dumps(value)
        return urllib.urlencode(args)

    def named_get(self, path_or_url, operation_name, headers=None,
                  api_version=DEFAULT_API_VERSION, **kwargs):
        kwargs['ws.op'] = operation_name
        data = '&'.join(['%s=%s' % (key, self._quote_value(value))
                         for key, value in kwargs.items()])
        return self.get("%s?%s" % (path_or_url, data), data, headers,
                        api_version=api_version)

    def named_post(self, path, operation_name, headers=None,
                   api_version=DEFAULT_API_VERSION, **kwargs):
        data = self._convertArgs(operation_name, kwargs)
        return self.post(path, 'application/x-www-form-urlencoded', data,
                         headers, api_version=api_version)

    def patch(self, path, media_type, data, headers=None,
              api_version=DEFAULT_API_VERSION):
        """Make a PATCH request."""
        return self._make_request_with_entity_body(
            path, 'PATCH', media_type, data, headers, api_version=api_version)

    def _quote_value(self, value):
        """Quote a value for inclusion in a named GET.

        This may mean turning the value into a JSON string.
        """
        if not isinstance(value, basestring):
            value = simplejson.dumps(value)
        return urllib.quote(value)

    def _make_request_with_entity_body(self, path, method, media_type, data,
                                       headers, api_version):
        """A helper method for requests that include an entity-body.

        This means PUT, PATCH, and POST requests.
        """
        real_headers = {'Content-type' : media_type }
        if headers is not None:
            real_headers.update(headers)
        return self(path, method, data, real_headers, api_version=api_version)


class WebServiceResponseWrapper(ProxyBase):
    """A response from the web service with easy access to the JSON body."""

    def jsonBody(self):
        """Return the body of the web service request as a JSON document."""
        try:
            json = simplejson.loads(self.getBody())
            if isinstance(json, list):
                json = sorted(json)
            return json
        except ValueError:
            # Return a useful ValueError that displays the problematic
            # string, instead of one that just says the string wasn't
            # JSON.
            raise ValueError(self.getOutput())


def extract_url_parameter(url, parameter):
    """Extract parameter and its value from a URL.

    Use this if your test needs to inspect a parameter value embedded in
    a URL, but doesn't really care what the rest of the URL looks like
    or how the parameters are ordered.
    """
    scheme, host, path, query, fragment = urlsplit(url)
    args = query.split('&')
    for arg in args:
        key, value = arg.split('=')
        if key == parameter:
            return arg
    return None


class DuplicateIdError(Exception):
    """Raised by find_tag_by_id if more than one element has the given id."""


def find_tag_by_id(content, id):
    """Find and return the tag with the given ID"""
    elements_with_id = [tag for tag in BeautifulSoup(
        content, parseOnlyThese=SoupStrainer(id=id))]
    if len(elements_with_id) == 0:
        return None
    elif len(elements_with_id) == 1:
        return elements_with_id[0]
    else:
        raise DuplicateIdError(
            'Found %d elements with id %r' % (len(elements_with_id), id))


def first_tag_by_class(content, class_):
    """Find and return the first tag matching the given class(es)"""
    return find_tags_by_class(content, class_, True)


def find_tags_by_class(content, class_, only_first=False):
    """Find and return one or more tags matching the given class(es)"""
    match_classes = set(class_.split())
    def class_matcher(value):
        if value is None:
            return False
        classes = set(value.split())
        return match_classes.issubset(classes)
    soup = BeautifulSoup(
        content, parseOnlyThese=SoupStrainer(attrs={'class': class_matcher}))
    if only_first:
        find = BeautifulSoup.find
    else:
        find = BeautifulSoup.findAll
    return find(soup, attrs={'class': class_matcher})


def find_portlet(content, name):
    """Find and return the portlet with the given title. Sequences of
    whitespace are considered equivalent to one space, and beginning and
    ending whitespace is also ignored, as are non-text elements such as
    images.
    """
    whitespace_re = re.compile('\s+')
    name = whitespace_re.sub(' ', name.strip())
    for portlet in find_tags_by_class(content, 'portlet'):
        if portlet.find('h2'):
            portlet_title = extract_text(portlet.find('h2'))
            if name == whitespace_re.sub(' ', portlet_title.strip()):
                return portlet
    return None


def find_main_content(content):
    """Return the main content of the page, excluding any portlets."""
    main_content = find_tag_by_id(content, 'maincontent')
    if main_content is None:
        # One-column pages don't use a <div id="maincontent">, so we
        # use the next best thing: <div id="container">.
        main_content = find_tag_by_id(content, 'container')
    if main_content is None:
        # Simple pages have neither of these, so as a last resort, we get
        # the page <body>.
        main_content = BeautifulSoup(content).body
    return main_content


def get_feedback_messages(content):
    """Find and return the feedback messages of the page."""
    message_classes = ['message', 'informational message', 'error message',
                       'warning message']
    soup = BeautifulSoup(
        content,
        parseOnlyThese=SoupStrainer(['div', 'p'], {'class': message_classes}))
    return [extract_text(tag) for tag in soup]


def print_radio_button_field(content, name):
    """Find the input called field.name, and print a friendly representation.

    The resulting output will look something like:
    (*) A checked option
    ( ) An unchecked option
    """
    main = BeautifulSoup(content)
    buttons =  main.findAll(
        'input', {'name': 'field.%s' % name})
    for button in buttons:
        if button.parent.name == 'label':
            label = extract_text(button.parent)
        else:
            label = extract_text(
                main.find('label', attrs={'for': button['id']}))
        if button.get('checked', None):
            radio = '(*)'
        else:
            radio = '( )'
        print radio, label


def strip_label(label):
    """Strip surrounding whitespace and non-breaking spaces."""
    return label.replace('\xC2', '').replace('\xA0', '').strip()


IGNORED_ELEMENTS = [Comment, Declaration, ProcessingInstruction]
ELEMENTS_INTRODUCING_NEWLINE = [
    'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'pre', 'dl',
    'div', 'noscript', 'blockquote', 'form', 'hr', 'table', 'fieldset',
    'address', 'li', 'dt', 'dd', 'th', 'td', 'caption', 'br']


NEWLINES_RE = re.compile(u'\n+')
LEADING_AND_TRAILING_SPACES_RE = re.compile(
    u'(^[ \t]+)|([ \t]$)', re.MULTILINE)
TABS_AND_SPACES_RE = re.compile(u'[ \t]+')
NBSP_RE = re.compile(u'&nbsp;|&#160;')


def extract_link_from_tag(tag, base=None):
    """Return a link from <a> `tag`, optionally considered relative to `base`.

    A `tag` should contain a 'href' attribute, and `base` will commonly
    be extracted from browser.url.
    """
    if not isinstance(tag, PageElement):
        link = BeautifulSoup(tag)
    else:
        link = tag

    href = dict(link.attrs).get('href')
    if base is None:
        return href
    else:
        return urljoin(base, href)


def extract_text(content, extract_image_text=False):
    """Return the text stripped of all tags.

    All runs of tabs and spaces are replaced by a single space and runs of
    newlines are replaced by a single newline. Leading and trailing white
    spaces are stripped.
    """
    if not isinstance(content, PageElement):
        soup = BeautifulSoup(content)
    else:
        soup = content

    result = []
    nodes = list(soup)
    while nodes:
        node = nodes.pop(0)
        if type(node) in IGNORED_ELEMENTS:
            continue
        elif isinstance(node, NavigableString):
            result.append(unicode(node))
        else:
            if isinstance(node, Tag):
                # If the node has the class "sortkey" then it is invisible.
                if node.get('class') == 'sortkey':
                    continue
                if node.name.lower() in ELEMENTS_INTRODUCING_NEWLINE:
                    result.append(u'\n')

                # If extract_image_text is True and the node is an
                # image, try to find its title or alt attributes.
                if extract_image_text and node.name.lower() == 'img':
                    # Title outweighs alt text for the purposes of
                    # pagetest output.
                    if node.get('title') is not None:
                        result.append(node['title'])
                    elif node.get('alt') is not None:
                        result.append(node['alt'])

            # Process this node's children next.
            nodes[0:0] = list(node)

    text = u''.join(result)
    text = NBSP_RE.sub(' ', text)
    text = TABS_AND_SPACES_RE.sub(' ', text)
    text = LEADING_AND_TRAILING_SPACES_RE.sub('', text)
    text = NEWLINES_RE.sub('\n', text)

    # Remove possible newlines at beginning and end.
    return text.strip()


# XXX cprov 2007-02-07: This function seems to be more specific to a
# particular product (soyuz) than the rest. Maybe it belongs to
# somewhere else.
def parse_relationship_section(content):
    """Parser package relationship section.

    See package-relationship-pages.txt and related.
    """
    soup = BeautifulSoup(content)
    section = soup.find('ul')
    whitespace_re = re.compile('\s+')
    if section is None:
        print 'EMPTY SECTION'
        return
    for li in section.findAll('li'):
        if li.a:
            link = li.a
            content = whitespace_re.sub(' ', link.string.strip())
            url = link['href']
            print 'LINK: "%s" -> %s' % (content, url)
        else:
            content = whitespace_re.sub(' ', li.string.strip())
            print 'TEXT: "%s"' % content


def print_action_links(content):
    """Print action menu urls."""
    actions = find_tag_by_id(content, 'actions')
    if actions is None:
        print "No actions portlet"
        return
    entries = actions.findAll('li')
    for entry in entries:
        if entry.a:
            print '%s: %s' % (entry.a.string, entry.a['href'])
        elif entry.strong:
            print entry.strong.string


def print_navigation_links(content):
    """Print navigation menu urls."""
    navigation_links  = find_tag_by_id(content, 'navigation-tabs')
    if navigation_links is None:
        print "No navigation links"
        return
    title = navigation_links.find('label')
    if title is not None:
        print '= %s =' % title.string
    entries = navigation_links.findAll(['strong', 'a'])
    for entry in entries:
        try:
            print '%s: %s' % (entry.span.string, entry['href'])
        except KeyError:
            print entry.span.string


def print_portlet_links(content, name, base=None):
    """Print portlet urls.

    This function expects the browser.content as well as the h2 name of the
    portlet. base is optional. It will locate the portlet and print out the
    links. It will report if the portlet cannot be found and will also report
    if there are no links to be found. Unlike the other functions on this
    page, this looks for "a" instead of "li". Example usage:
    --------------
    >>> print_portlet_links(admin_browser.contents,'Milestone milestone3 for
        Ubuntu details')
    Ubuntu: /ubuntu
    Warty: /ubuntu/warty
    --------------
    """

    portlet_contents = find_portlet(content, name)
    if portlet_contents is None:
        print "No portlet found with name:", name
        return
    portlet_links = portlet_contents.findAll('a')
    if len(portlet_links) == 0:
        print "No links were found in the portlet."
        return
    for portlet_link in portlet_links:
        print '%s: %s' % (portlet_link.string,
            extract_link_from_tag(portlet_link, base))


def print_submit_buttons(content):
    """Print the submit button values found in the main content.

    Use this to check that the buttons on a page match your expectations.
    """
    buttons = find_main_content(content).findAll(
        'input', attrs={'class': 'button', 'type': 'submit'})
    if buttons is None:
        print "No buttons found"
    else:
        for button in buttons:
            print button['value']


def print_comments(page):
    """Print the comments on a BugTask index page."""
    main_content = find_main_content(page)
    for comment in main_content('div', 'boardCommentBody'):
        for li_tag in comment('li'):
            print "Attachment: %s" % li_tag.a.renderContents()
        print comment.div.renderContents()
        print "-"*40


def print_batch_header(soup):
    """Print the batch navigator header."""
    navigation = soup.find('td', {'class' : 'batch-navigation-index'})
    print extract_text(navigation).encode('ASCII', 'backslashreplace')


def print_self_link_of_entries(json_body):
    """Print the self_link attribute of each entry in the given JSON body."""
    links = sorted(entry['self_link'] for entry in json_body['entries'])
    for link in links:
        print link


def print_ppa_packages(contents):
    packages = find_tags_by_class(contents, 'archive_package_row')
    for pkg in packages:
        print extract_text(pkg)
    empty_section = find_tag_by_id(contents, 'empty-result')
    if empty_section is not None:
        print extract_text(empty_section)


def print_location(contents):
    """Print the hierarchy, application tabs, and main heading of the page.

    The hierarchy shows your position in the Launchpad structure:
    for example, Launchpad > Ubuntu > 8.04.
    The application tabs represent the major facets of an object:
    for example, Overview, Bugs, and Translations.
    The main heading is the first <h1> element in the page.
    """
    doc = find_tag_by_id(contents, 'document')
    hierarchy = doc.find(attrs={'id': 'lp-hierarchy'}).findAll(
        recursive=False)
    segments = [extract_text(step).encode('us-ascii', 'replace')
                for step in hierarchy
                if step.name != 'small']
    # The first segment is spurious (used for styling), and the second
    # contains only <img alt="Launchpad"> that extract_text() doesn't
    # pick up. So we replace the first two elements with 'Launchpad':
    segments = ['Launchpad'] + segments[2:]
    print 'Hierarchy:', ' > '.join(segments)
    print 'Tabs:'
    print_location_apps(contents)
    main_heading = doc.h1
    if main_heading:
        main_heading = extract_text(main_heading).encode(
            'us-ascii', 'replace')
    else:
        main_heading = '(No main heading)'
    print "Main heading: %s" % main_heading


def print_location_apps(contents):
    """Print the application tabs' text and URL."""
    location_apps = find_tag_by_id(contents, 'lp-apps')
    for tab in location_apps.findAll('span'):
        tab_text = extract_text(tab)
        if tab['class'].find('active') != -1:
            tab_text += ' (selected)'
        if tab.a:
            link = tab.a['href']
        else:
            link = 'not linked'
        print "* %s - %s" % (tab_text, link)


def print_tag_with_id(contents, id):
    """A simple helper to print the extracted text of the tag."""
    tag = find_tag_by_id(contents, id)
    print extract_text(tag)


def print_errors(contents):
    """Print all the errors on the page."""
    errors = find_tags_by_class(contents, 'error')
    error_texts = [extract_text(error) for error in errors]
    for error in error_texts:
        print error


def setupBrowser(auth=None):
    """Create a testbrowser object for use in pagetests.

    :param auth: HTTP authentication string. None for the anonymous user, or a
        string of the form 'Basic email:password' for an authenticated user.
    :return: A `Browser` object.
    """
    browser = Browser()
    # Set up our Browser objects with handleErrors set to False, since
    # that gives a tracebacks instead of unhelpful error messages.
    browser.handleErrors = False
    if auth is not None:
        browser.addHeader("Authorization", auth)
    return browser


def safe_canonical_url(*args, **kwargs):
    """Generate a bytestring URL for an object"""
    return str(canonical_url(*args, **kwargs))


def webservice_for_person(person, consumer_key='launchpad-library',
                          permission=OAuthPermission.READ_PUBLIC,
                          context=None):
    """Return a valid WebServiceCaller for the person.

    Ues this method to create a way to test the webservice that doesn't depend
    on sample data.
    """
    login(ANONYMOUS)
    oacs = getUtility(IOAuthConsumerSet)
    consumer = oacs.getByKey(consumer_key)
    if consumer is None:
        consumer = oacs.new(consumer_key)
    request_token = consumer.newRequestToken()
    request_token.review(person, permission, context)
    access_token = request_token.createAccessToken()
    logout()
    return WebServiceCaller(consumer_key, access_token.key, port=9000)


def stop():
    # Temporarily restore the real stdout.
    old_stdout = sys.stdout
    sys.stdout = sys.__stdout__
    try:
        pdb.set_trace()
    finally:
        sys.stdout = old_stdout


class FactoryWrapper:

    def __init__(self, factory):
        self.factory = factory

    def __getattr__(self, name):
        value = getattr(self.__dict__['factory'], name)
        if callable(value):
            return with_anonymous_login(value)
        else:
            return value


def setUpGlobs(test):
    test.globs['transaction'] = transaction
    test.globs['http'] = UnstickyCookieHTTPCaller()
    test.globs['webservice'] = WebServiceCaller(
        'launchpad-library', 'salgado-change-anything')
    test.globs['public_webservice'] = WebServiceCaller(
        'foobar123451432', 'salgado-read-nonprivate')
    test.globs['user_webservice'] = WebServiceCaller(
        'launchpad-library', 'nopriv-read-nonprivate')
    test.globs['setupBrowser'] = setupBrowser
    test.globs['browser'] = setupBrowser()
    test.globs['anon_browser'] = setupBrowser()
    test.globs['user_browser'] = setupBrowser(
        auth="Basic no-priv@canonical.com:test")
    test.globs['admin_browser'] = setupBrowser(
        auth="Basic foo.bar@canonical.com:test")

    test.globs['ANONYMOUS'] = ANONYMOUS
    # If a unicode URL is opened by the test browswer, later navigation
    # raises ValueError exceptions in /usr/lib/python2.4/Cookie.py
    test.globs['canonical_url'] = safe_canonical_url
    test.globs['factory'] = LaunchpadObjectFactory()
    test.globs['find_tag_by_id'] = find_tag_by_id
    test.globs['first_tag_by_class'] = first_tag_by_class
    test.globs['find_tags_by_class'] = find_tags_by_class
    test.globs['find_portlet'] = find_portlet
    test.globs['find_main_content'] = find_main_content
    test.globs['get_feedback_messages'] = get_feedback_messages
    test.globs['extract_link_from_tag'] = extract_link_from_tag
    test.globs['extract_text'] = extract_text
    test.globs['login'] = login
    test.globs['login_person'] = login_person
    test.globs['logout'] = logout
    test.globs['parse_relationship_section'] = parse_relationship_section
    test.globs['pretty'] = pprint25.PrettyPrinter(width=1).pformat
    test.globs['print_action_links'] = print_action_links
    test.globs['print_errors'] = print_errors
    test.globs['print_location'] = print_location
    test.globs['print_location_apps'] = print_location_apps
    test.globs['print_navigation_links'] = print_navigation_links
    test.globs['print_portlet_links'] = print_portlet_links
    test.globs['print_comments'] = print_comments
    test.globs['print_submit_buttons'] = print_submit_buttons
    test.globs['print_radio_button_field'] = print_radio_button_field
    test.globs['print_batch_header'] = print_batch_header
    test.globs['print_ppa_packages'] = print_ppa_packages
    test.globs['print_self_link_of_entries'] = print_self_link_of_entries
    test.globs['print_tag_with_id'] = print_tag_with_id
    test.globs['PageTestLayer'] = PageTestLayer
    test.globs['stop'] = stop


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
            # XXX Robert Collins 2006-01-17: we can hook in pre and post
            # story actions here much more tidily (and in self.debug too)
            # - probably via self.setUp and self.tearDown
            self._suite.run(result)
        finally:
            PageTestLayer.endStory()

    def debug(self):
        self._suite.debug()


# This function name doesn't follow our standard naming conventions,
# but does follow the convention of the other doctest related *Suite()
# functions.

def PageTestSuite(storydir, package=None, setUp=setUpGlobs):
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
    stripped_storydir = strip_prefix(abs_storydir)

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
    suite = LayeredDocFileSuite(
        package=package, checker=checker, stdout_logging=False,
        layer=PageTestLayer, setUp=setUp,
        *[os.path.join(storydir, filename)
          for filename in unnumberedfilenames])

    # Add numbered tests to the suite as a single story.
    storysuite = LayeredDocFileSuite(
        package=package, checker=checker, stdout_logging=False,
        setUp=setUp,
        *[os.path.join(storydir, filename)
          for filename in numberedfilenames])
    suite.addTest(PageStoryTestCase(stripped_storydir, storysuite))

    return suite
