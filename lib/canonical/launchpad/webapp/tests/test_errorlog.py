# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for error logging & OOPS reporting."""

__metaclass__ = type

import datetime
import logging
import httplib
import os
import shutil
import stat
import StringIO
import sys
import tempfile
from textwrap import dedent
import traceback
import unittest

from lazr.batchnavigator.interfaces import InvalidBatchSizeError
from lazr.restful.declarations import error_status
from oops.uniquefileallocator import UniqueFileAllocator
import pytz
import testtools
from zope.app.publication.tests.test_zopepublication import (
    UnauthenticatedPrincipal,
    )
from zope.interface import directlyProvides
from zope.publisher.browser import TestRequest
from zope.publisher.interfaces import NotFound
from zope.publisher.interfaces.xmlrpc import IXMLRPCRequest
from zope.security.interfaces import Unauthorized
from zope.testing.loggingsupport import InstalledHandler

from canonical.config import config
from lp.app import versioninfo
from canonical.launchpad.layers import WebServiceLayer
from canonical.launchpad.webapp.adapter import (
    clear_request_started,
    set_request_started,
    )
from canonical.launchpad.webapp.errorlog import (
    _is_sensitive,
    ErrorReport,
    ErrorReportingUtility,
    OopsLoggingHandler,
    ScriptRequest,
    )
from canonical.launchpad.webapp.interfaces import (
    IUnloggedException,
    NoReferrerError,
    )
from canonical.testing import reset_logging
from lp.app.errors import (
    GoneError,
    TranslationUnavailable,
    )
from lp.services.osutils import remove_tree
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.testing import TestCase
from lp_sitecustomize import customize_get_converter


UTC = pytz.utc


class ArbitraryException(Exception):
    """Used to test handling of exceptions in OOPS reports."""


class TestErrorReport(testtools.TestCase):

    def tearDown(self):
        reset_logging()
        super(TestErrorReport, self).tearDown()

    def test___init__(self):
        """Test ErrorReport.__init__()"""
        entry = ErrorReport('id', 'exc-type', 'exc-value', 'timestamp',
                            'pageid', 'traceback-text', 'username', 'url', 42,
                            [('name1', 'value1'), ('name2', 'value2'),
                             ('name1', 'value3')],
                            [(1, 5, 'store_a', 'SELECT 1'),
                             (5, 10, 'store_b', 'SELECT 2')],
                            False)
        self.assertEqual(entry.id, 'id')
        self.assertEqual(entry.type, 'exc-type')
        self.assertEqual(entry.value, 'exc-value')
        self.assertEqual(entry.time, 'timestamp')
        self.assertEqual(entry.pageid, 'pageid')
        self.assertEqual(entry.branch_nick, versioninfo.branch_nick)
        self.assertEqual(entry.revno, versioninfo.revno)
        self.assertEqual(entry.username, 'username')
        self.assertEqual(entry.url, 'url')
        self.assertEqual(entry.duration, 42)
        self.assertEqual(entry.informational, False)
        self.assertEqual(len(entry.req_vars), 3)
        self.assertEqual(entry.req_vars[0], ('name1', 'value1'))
        self.assertEqual(entry.req_vars[1], ('name2', 'value2'))
        self.assertEqual(entry.req_vars[2], ('name1', 'value3'))
        self.assertEqual(len(entry.db_statements), 2)
        self.assertEqual(
            entry.db_statements[0],
            (1, 5, 'store_a', 'SELECT 1'))
        self.assertEqual(
            entry.db_statements[1],
            (5, 10, 'store_b', 'SELECT 2'))

    def test_read(self):
        """Test ErrorReport.read()."""
        # Note: this exists to test the compatibility thunk only.
        fp = StringIO.StringIO(dedent("""\
            Oops-Id: OOPS-A0001
            Exception-Type: NotFound
            Exception-Value: error message
            Date: 2005-04-01T00:00:00+00:00
            Page-Id: IFoo:+foo-template
            User: Sample User
            URL: http://localhost:9000/foo
            Duration: 42

            HTTP_USER_AGENT=Mozilla/5.0
            HTTP_REFERER=http://localhost:9000/
            name%3Dfoo=hello%0Aworld

            00001-00005@store_a SELECT 1
            00005-00010@store_b SELECT 2

            traceback-text"""))
        entry = ErrorReport.read(fp)
        self.assertEqual(entry.id, 'OOPS-A0001')
        self.assertEqual(entry.type, 'NotFound')
        self.assertEqual(entry.value, 'error message')
        self.assertEqual(
                entry.time, datetime.datetime(2005, 4, 1, tzinfo=UTC))
        self.assertEqual(entry.pageid, 'IFoo:+foo-template')
        self.assertEqual(entry.tb_text, 'traceback-text')
        self.assertEqual(entry.username, 'Sample User')
        self.assertEqual(entry.url, 'http://localhost:9000/foo')
        self.assertEqual(entry.duration, 42)
        self.assertEqual(len(entry.req_vars), 3)
        self.assertEqual(entry.req_vars[0], ('HTTP_USER_AGENT',
                                             'Mozilla/5.0'))
        self.assertEqual(entry.req_vars[1], ('HTTP_REFERER',
                                             'http://localhost:9000/'))
        self.assertEqual(entry.req_vars[2], ('name=foo', 'hello\nworld'))
        self.assertEqual(len(entry.db_statements), 2)
        self.assertEqual(
            entry.db_statements[0],
            (1, 5, 'store_a', 'SELECT 1'))
        self.assertEqual(
            entry.db_statements[1],
            (5, 10, 'store_b', 'SELECT 2'))


class TestErrorReportingUtility(testtools.TestCase):

    def setUp(self):
        super(TestErrorReportingUtility, self).setUp()
        # ErrorReportingUtility reads the global config to get the
        # current error directory.
        test_data = dedent("""
            [error_reports]
            copy_to_zlog: true
            error_dir: %s
            """ % tempfile.mkdtemp())
        config.push('test_data', test_data)
        shutil.rmtree(config.error_reports.error_dir, ignore_errors=True)

    def tearDown(self):
        shutil.rmtree(config.error_reports.error_dir, ignore_errors=True)
        config.pop('test_data')
        reset_logging()
        super(TestErrorReportingUtility, self).tearDown()

    def test_sets_log_namer_to_a_UniqueFileAllocator(self):
        utility = ErrorReportingUtility()
        self.assertIsInstance(utility.log_namer, UniqueFileAllocator)

    def test_configure(self):
        """Test ErrorReportingUtility.setConfigSection()."""
        utility = ErrorReportingUtility()
        # The ErrorReportingUtility uses the config.error_reports section
        # by default.
        self.assertEqual(config.error_reports.oops_prefix,
            utility.oops_prefix)
        self.assertEqual(config.error_reports.error_dir,
            utility.log_namer._output_root)
        self.assertEqual(
            config.error_reports.copy_to_zlog, utility.copy_to_zlog)
        # Some external processes may use another config section to
        # provide the error log configuration.
        utility.configure(section_name='branchscanner')
        self.assertEqual(config.branchscanner.oops_prefix,
            utility.oops_prefix)
        self.assertEqual(config.branchscanner.error_dir,
            utility.log_namer._output_root)
        self.assertEqual(
            config.branchscanner.copy_to_zlog, utility.copy_to_zlog)

        # The default error section can be restored.
        utility.configure()
        self.assertEqual(config.error_reports.oops_prefix,
            utility.oops_prefix)
        self.assertEqual(config.error_reports.error_dir,
            utility.log_namer._output_root)
        self.assertEqual(
            config.error_reports.copy_to_zlog, utility.copy_to_zlog)

    def test_setOopsToken(self):
        """Test ErrorReportingUtility.setOopsToken()."""
        utility = ErrorReportingUtility()
        utility.setOopsToken('foo')
        self.assertEqual('Tfoo', utility.oops_prefix)
        # Some scripts run multiple processes and append a string number
        # to the prefix.
        utility.setOopsToken('1')
        self.assertEqual('T1', utility.oops_prefix)

    def test_raising(self):
        """Test ErrorReportingUtility.raising() with no request"""
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)

        # Set up default file creation mode to rwx------.
        umask_permission = stat.S_IRWXG | stat.S_IRWXO
        old_umask = os.umask(umask_permission)

        try:
            raise ArbitraryException('xyz')
        except ArbitraryException:
            utility.raising(sys.exc_info(), now=now)

        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertTrue(os.path.exists(errorfile))

        # Check errorfile is set with the correct permission: rw-r--r--
        st = os.stat(errorfile)
        wanted_permission = (
            stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        # Get only the permission bits for this file.
        file_permission = stat.S_IMODE(st.st_mode)
        self.assertEqual(file_permission, wanted_permission)
        # Restore the umask to the original value.
        os.umask(old_umask)

        lines = open(errorfile, 'r').readlines()

        # the header
        self.assertEqual(lines[0], 'Oops-Id: OOPS-91T1\n')
        self.assertEqual(lines[1], 'Exception-Type: ArbitraryException\n')
        self.assertEqual(lines[2], 'Exception-Value: xyz\n')
        self.assertEqual(lines[3], 'Date: 2006-04-01T00:30:00+00:00\n')
        self.assertEqual(lines[4], 'Page-Id: \n')
        self.assertEqual(lines[5], 'Branch: %s\n' % versioninfo.branch_nick)
        self.assertEqual(lines[6], 'Revision: %s\n' % versioninfo.revno)
        self.assertEqual(lines[7], 'User: None\n')
        self.assertEqual(lines[8], 'URL: None\n')
        self.assertEqual(lines[9], 'Duration: -1\n')
        self.assertEqual(lines[10], 'Informational: False\n')
        self.assertEqual(lines[11], '\n')

        # no request vars
        self.assertEqual(lines[12], '\n')

        # no database statements
        self.assertEqual(lines[13], '\n')

        # traceback
        self.assertEqual(lines[14], 'Traceback (most recent call last):\n')
        #  Module canonical.launchpad.webapp.ftests.test_errorlog, ...
        #    raise ArbitraryException(\'xyz\')
        self.assertEqual(lines[17], 'ArbitraryException: xyz\n')

    def test_raising_with_request(self):
        """Test ErrorReportingUtility.raising() with a request"""
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)

        request = TestRequestWithPrincipal(
                environ={
                    'SERVER_URL': 'http://localhost:9000/foo',
                    'HTTP_COOKIE': 'lp=cookies_hidden_for_security_reasons',
                    'name1': 'value1',
                    },
                form={
                    'name1': 'value3 \xa7',
                    'name2': 'value2',
                    u'\N{BLACK SQUARE}': u'value4',
                    })
        request.setInWSGIEnvironment('launchpad.pageid', 'IFoo:+foo-template')

        try:
            raise ArbitraryException('xyz\nabc')
        except ArbitraryException:
            utility.raising(sys.exc_info(), request, now=now)

        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertTrue(os.path.exists(errorfile))
        lines = open(errorfile, 'r').readlines()

        # the header
        self.assertEqual(lines.pop(0), 'Oops-Id: OOPS-91T1\n')
        self.assertEqual(lines.pop(0), 'Exception-Type: ArbitraryException\n')
        self.assertEqual(lines.pop(0), 'Exception-Value: xyz abc\n')
        self.assertEqual(lines.pop(0), 'Date: 2006-04-01T00:30:00+00:00\n')
        self.assertEqual(lines.pop(0), 'Page-Id: IFoo:+foo-template\n')
        self.assertEqual(
            lines.pop(0), 'Branch: %s\n' % versioninfo.branch_nick)
        self.assertEqual(lines.pop(0), 'Revision: %s\n' % versioninfo.revno)
        self.assertEqual(
            lines.pop(0), 'User: Login, 42, title, description |\\u25a0|\n')
        self.assertEqual(lines.pop(0), 'URL: http://localhost:9000/foo\n')
        self.assertEqual(lines.pop(0), 'Duration: -1\n')
        self.assertEqual(lines.pop(0), 'Informational: False\n')
        self.assertEqual(lines.pop(0), '\n')

        # request vars
        self.assertEqual(lines.pop(0), 'CONTENT_LENGTH=0\n')
        self.assertEqual(
            lines.pop(0), 'GATEWAY_INTERFACE=TestFooInterface/1.0\n')
        self.assertEqual(lines.pop(0), 'HTTP_COOKIE=%3Chidden%3E\n')
        self.assertEqual(lines.pop(0), 'HTTP_HOST=127.0.0.1\n')
        self.assertEqual(
            lines.pop(0), 'SERVER_URL=http://localhost:9000/foo\n')

        # non-ASCII request var
        self.assertEqual(lines.pop(0), '\\u25a0=value4\n')
        self.assertEqual(lines.pop(0), 'lp=%3Chidden%3E\n')
        self.assertEqual(lines.pop(0), 'name1=value3 \\xa7\n')
        self.assertEqual(lines.pop(0), 'name2=value2\n')
        self.assertEqual(lines.pop(0), '\n')

        # no database statements
        self.assertEqual(lines.pop(0), '\n')

        # traceback
        self.assertEqual(lines.pop(0), 'Traceback (most recent call last):\n')
        #  Module canonical.launchpad.webapp.ftests.test_errorlog, ...
        #    raise ArbitraryException(\'xyz\')
        lines.pop(0)
        lines.pop(0)
        self.assertEqual(lines.pop(0), 'ArbitraryException: xyz\n')

        # verify that the oopsid was set on the request
        self.assertEqual(request.oopsid, 'OOPS-91T1')
        self.assertEqual(request.oops['id'], 'OOPS-91T1')

    def test_raising_with_xmlrpc_request(self):
        # Test ErrorReportingUtility.raising() with an XML-RPC request.
        request = TestRequest()
        directlyProvides(request, IXMLRPCRequest)
        request.getPositionalArguments = lambda: (1, 2)
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)
        try:
            raise ArbitraryException('xyz\nabc')
        except ArbitraryException:
            utility.raising(sys.exc_info(), request, now=now)
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertTrue(os.path.exists(errorfile))
        lines = open(errorfile, 'r').readlines()
        self.assertEqual(lines[16], 'xmlrpc args=(1, 2)\n')

    def test_raising_with_webservice_request(self):
        # Test ErrorReportingUtility.raising() with a WebServiceRequest
        # request. Only some exceptions result in OOPSes.
        request = TestRequest()
        directlyProvides(request, WebServiceLayer)
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)

        # Exceptions that don't use error_status result in OOPSes.
        try:
            raise ArbitraryException('xyz\nabc')
        except ArbitraryException:
            utility.raising(sys.exc_info(), request, now=now)
            self.assertNotEqual(request.oopsid, None)

        # Exceptions with a error_status in the 500 range result
        # in OOPSes.
        @error_status(httplib.INTERNAL_SERVER_ERROR)
        class InternalServerError(Exception):
            pass
        try:
            raise InternalServerError("")
        except InternalServerError:
            utility.raising(sys.exc_info(), request, now=now)
            self.assertNotEqual(request.oopsid, None)

        # Exceptions with any other error_status do not result
        # in OOPSes.
        @error_status(httplib.BAD_REQUEST)
        class BadDataError(Exception):
            pass
        try:
            raise BadDataError("")
        except BadDataError:
            utility.raising(sys.exc_info(), request, now=now)
            self.assertEqual(request.oopsid, None)

    def test_raising_for_script(self):
        """Test ErrorReportingUtility.raising with a ScriptRequest."""
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)

        try:
            raise ArbitraryException('xyz\nabc')
        except ArbitraryException:
            # Do not test escaping of request vars here, it is already tested
            # in test_raising_with_request.
            request = ScriptRequest([
                ('name2', 'value2'), ('name1', 'value1'),
                ('name1', 'value3')], URL='https://launchpad.net/example')
            utility.raising(sys.exc_info(), request, now=now)

        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertTrue(os.path.exists(errorfile))
        lines = open(errorfile, 'r').readlines()

        # the header
        self.assertEqual(lines[0], 'Oops-Id: OOPS-91T1\n')
        self.assertEqual(lines[1], 'Exception-Type: ArbitraryException\n')
        self.assertEqual(lines[2], 'Exception-Value: xyz abc\n')
        self.assertEqual(lines[3], 'Date: 2006-04-01T00:30:00+00:00\n')
        self.assertEqual(lines[4], 'Page-Id: \n')
        self.assertEqual(lines[5], 'Branch: %s\n' % versioninfo.branch_nick)
        self.assertEqual(lines[6], 'Revision: %s\n' % versioninfo.revno)
        self.assertEqual(lines[7], 'User: None\n')
        self.assertEqual(lines[8], 'URL: https://launchpad.net/example\n')
        self.assertEqual(lines[9], 'Duration: -1\n')
        self.assertEqual(lines[10], 'Informational: False\n')
        self.assertEqual(lines[11], '\n')

        # request vars
        self.assertEqual(lines[12], 'name1=value1\n')
        self.assertEqual(lines[13], 'name1=value3\n')
        self.assertEqual(lines[14], 'name2=value2\n')
        self.assertEqual(lines[15], '\n')

        # no database statements
        self.assertEqual(lines[16], '\n')

        # traceback
        self.assertEqual(lines[17], 'Traceback (most recent call last):\n')
        #  Module canonical.launchpad.webapp.ftests.test_errorlog, ...
        #    raise ArbitraryException(\'xyz\')
        self.assertEqual(lines[20], 'ArbitraryException: xyz\n')

        # verify that the oopsid was set on the request
        self.assertEqual(request.oopsid, 'OOPS-91T1')

    def test_raising_with_unprintable_exception(self):
        # Test ErrorReportingUtility.raising() with an unprintable exception.
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 01, 01, 00, 30, 00, tzinfo=UTC)

        class UnprintableException(Exception):

            def __str__(self):
                raise RuntimeError('arrgh')
            __repr__ = __str__

        log = InstalledHandler('SiteError')
        try:
            raise UnprintableException()
        except UnprintableException:
            utility.raising(sys.exc_info(), now=now)
        log.uninstall()

        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertTrue(os.path.exists(errorfile))
        lines = open(errorfile, 'r').readlines()

        # the header
        self.assertEqual(lines[0], 'Oops-Id: OOPS-1T1\n')
        self.assertEqual(lines[1], 'Exception-Type: UnprintableException\n')
        self.assertEqual(
            lines[2],
            'Exception-Value: <unprintable UnprintableException object>\n')
        self.assertEqual(lines[3], 'Date: 2006-01-01T00:30:00+00:00\n')
        self.assertEqual(lines[4], 'Page-Id: \n')
        self.assertEqual(lines[5], 'Branch: %s\n' % versioninfo.branch_nick)
        self.assertEqual(lines[6], 'Revision: %s\n' % versioninfo.revno)
        self.assertEqual(lines[7], 'User: None\n')
        self.assertEqual(lines[8], 'URL: None\n')
        self.assertEqual(lines[9], 'Duration: -1\n')
        self.assertEqual(lines[10], 'Informational: False\n')
        self.assertEqual(lines[11], '\n')

        # no request vars
        self.assertEqual(lines[12], '\n')

        # no database statements
        self.assertEqual(lines[13], '\n')

        # traceback
        self.assertEqual(lines[14], 'Traceback (most recent call last):\n')
        #  Module canonical.launchpad.webapp.ftests.test_errorlog, ...
        #    raise UnprintableException()
        self.assertEqual(
            lines[17],
            'UnprintableException:'
            ' <unprintable UnprintableException object>\n')

    def test_raising_unauthorized_without_request(self):
        """Unauthorized exceptions are logged when there's no request."""
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)
        try:
            raise Unauthorized('xyz')
        except Unauthorized:
            utility.raising(sys.exc_info(), now=now)
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.failUnless(os.path.exists(errorfile))

    def test_raising_unauthorized_without_principal(self):
        """Unauthorized exceptions are logged when the request has no
        principal."""
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)
        request = ScriptRequest([('name2', 'value2')])
        try:
            raise Unauthorized('xyz')
        except Unauthorized:
            utility.raising(sys.exc_info(), request, now=now)
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.failUnless(os.path.exists(errorfile))

    def test_raising_unauthorized_with_unauthenticated_principal(self):
        """Unauthorized exceptions are not logged when the request has an
        unauthenticated principal."""
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)
        request = TestRequestWithUnauthenticatedPrincipal()
        try:
            raise Unauthorized('xyz')
        except Unauthorized:
            utility.raising(sys.exc_info(), request, now=now)
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.failIf(os.path.exists(errorfile))

    def test_raising_unauthorized_with_authenticated_principal(self):
        """Unauthorized exceptions are logged when the request has an
        authenticated principal."""
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)
        request = TestRequestWithPrincipal()
        try:
            raise Unauthorized('xyz')
        except Unauthorized:
            utility.raising(sys.exc_info(), request, now=now)
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.failUnless(os.path.exists(errorfile))

    def test_raising_translation_unavailable(self):
        """Test ErrorReportingUtility.raising() with a TranslationUnavailable
        exception.

        An OOPS is not recorded when a TranslationUnavailable exception is
        raised.
        """
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)

        try:
            raise TranslationUnavailable('xyz')
        except TranslationUnavailable:
            utility.raising(sys.exc_info(), now=now)

        self.assertTrue(
            TranslationUnavailable.__name__ in utility._ignored_exceptions,
            'TranslationUnavailable is not in _ignored_exceptions.')
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertFalse(os.path.exists(errorfile))

    def test_ignored_exceptions_for_offsite_referer(self):
        # Exceptions caused by bad URLs that may not be an Lp code issue.
        utility = ErrorReportingUtility()
        errors = set([
            GoneError.__name__, InvalidBatchSizeError.__name__,
            NotFound.__name__])
        self.assertEqual(
            errors, utility._ignored_exceptions_for_offsite_referer)

    def test_ignored_exceptions_for_offsite_referer_reported(self):
        # Oopses are reported when Launchpad is the referer for a URL
        # that caused an exception.
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)
        request = TestRequest(
            environ={
                'SERVER_URL': 'http://launchpad.dev/fnord',
                'HTTP_REFERER': 'http://launchpad.dev/snarf'})
        try:
            raise GoneError('fnord')
        except GoneError:
            utility.raising(sys.exc_info(), request, now=now)
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertTrue(os.path.exists(errorfile))

    def test_ignored_exceptions_for_cross_vhost_referer_reported(self):
        # Oopses are reported when a Launchpad  vhost is the referer for a URL
        # that caused an exception.
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)
        request = TestRequest(
            environ={
                'SERVER_URL': 'http://launchpad.dev/fnord',
                'HTTP_REFERER': 'http://bazaar.launchpad.dev/snarf'})
        try:
            raise GoneError('fnord')
        except GoneError:
            utility.raising(sys.exc_info(), request, now=now)
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertTrue(os.path.exists(errorfile))

    def test_ignored_exceptions_for_criss_cross_vhost_referer_reported(self):
        # Oopses are reported when a Launchpad referer for a bad URL on a
        # vhost that caused an exception.
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)
        request = TestRequest(
            environ={
                'SERVER_URL': 'http://bazaar.launchpad.dev/fnord',
                'HTTP_REFERER': 'http://launchpad.dev/snarf'})
        try:
            raise GoneError('fnord')
        except GoneError:
            utility.raising(sys.exc_info(), request, now=now)
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertTrue(os.path.exists(errorfile))

    def test_ignored_exceptions_for_offsite_referer_not_reported(self):
        # Oopses are not reported when Launchpad is not the referer.
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)
        # There is no HTTP_REFERER header in this request
        request = TestRequest(
            environ={'SERVER_URL': 'http://launchpad.dev/fnord'})
        try:
            raise GoneError('fnord')
        except GoneError:
            utility.raising(sys.exc_info(), request, now=now)
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertFalse(os.path.exists(errorfile))

    def test_raising_no_referrer_error(self):
        """Test ErrorReportingUtility.raising() with a NoReferrerError
        exception.

        An OOPS is not recorded when a NoReferrerError exception is
        raised.
        """
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)

        try:
            raise NoReferrerError('xyz')
        except NoReferrerError:
            utility.raising(sys.exc_info(), now=now)

        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertFalse(os.path.exists(errorfile))

    def test_raising_with_string_as_traceback(self):
        # ErrorReportingUtility.raising() can be called with a string in the
        # place of a traceback. This is useful when the original traceback
        # object is unavailable.
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)

        try:
            raise RuntimeError('hello')
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            # Turn the traceback into a string. When the traceback itself
            # cannot be passed to ErrorReportingUtility.raising, a string like
            # one generated by format_exc is sometimes passed instead.
            exc_tb = traceback.format_exc()

        utility.raising((exc_type, exc_value, exc_tb), now=now)
        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')

        self.assertTrue(os.path.exists(errorfile))
        lines = open(errorfile, 'r').readlines()

        # the header
        self.assertEqual(lines[0], 'Oops-Id: OOPS-91T1\n')
        self.assertEqual(lines[1], 'Exception-Type: RuntimeError\n')
        self.assertEqual(lines[2], 'Exception-Value: hello\n')
        self.assertEqual(lines[3], 'Date: 2006-04-01T00:30:00+00:00\n')
        self.assertEqual(lines[4], 'Page-Id: \n')
        self.assertEqual(lines[5], 'Branch: %s\n' % versioninfo.branch_nick)
        self.assertEqual(lines[6], 'Revision: %s\n' % versioninfo.revno)
        self.assertEqual(lines[7], 'User: None\n')
        self.assertEqual(lines[8], 'URL: None\n')
        self.assertEqual(lines[9], 'Duration: -1\n')
        self.assertEqual(lines[10], 'Informational: False\n')
        self.assertEqual(lines[11], '\n')

        # no request vars
        self.assertEqual(lines[12], '\n')

        # no database statements
        self.assertEqual(lines[13], '\n')

        # traceback
        self.assertEqual(''.join(lines[14:18]), exc_tb)

    def test_handling(self):
        """Test ErrorReportingUtility.handling()."""
        utility = ErrorReportingUtility()
        now = datetime.datetime(2006, 04, 01, 00, 30, 00, tzinfo=UTC)

        try:
            raise ArbitraryException('xyz')
        except ArbitraryException:
            utility.handling(sys.exc_info(), now=now)

        errorfile = os.path.join(
            utility.log_namer.output_dir(now), '01800.T1')
        self.assertTrue(os.path.exists(errorfile))
        lines = open(errorfile, 'r').readlines()

        # the header
        self.assertEqual(lines[0], 'Oops-Id: OOPS-91T1\n')
        self.assertEqual(lines[1], 'Exception-Type: ArbitraryException\n')
        self.assertEqual(lines[2], 'Exception-Value: xyz\n')
        self.assertEqual(lines[3], 'Date: 2006-04-01T00:30:00+00:00\n')
        self.assertEqual(lines[4], 'Page-Id: \n')
        self.assertEqual(lines[5], 'Branch: %s\n' % versioninfo.branch_nick)
        self.assertEqual(lines[6], 'Revision: %s\n' % versioninfo.revno)
        self.assertEqual(lines[7], 'User: None\n')
        self.assertEqual(lines[8], 'URL: None\n')
        self.assertEqual(lines[9], 'Duration: -1\n')
        self.assertEqual(lines[10], 'Informational: True\n')
        self.assertEqual(lines[11], '\n')

        # no request vars
        self.assertEqual(lines[12], '\n')

        # no database statements
        self.assertEqual(lines[13], '\n')

        # traceback
        self.assertEqual(lines[14], 'Traceback (most recent call last):\n')
        #  Module canonical.launchpad.webapp.ftests.test_errorlog, ...
        #    raise ArbitraryException(\'xyz\')
        self.assertEqual(lines[17], 'ArbitraryException: xyz\n')

    def test_oopsMessage(self):
        """oopsMessage pushes and pops the messages."""
        utility = ErrorReportingUtility()
        with utility.oopsMessage({'a': 'b', 'c': 'd'}):
            self.assertEqual(
                {0: {'a': 'b', 'c': 'd'}}, utility._oops_messages)
            # An additional message doesn't supplant the original message.
            with utility.oopsMessage(dict(e='f', a='z', c='d')):
                self.assertEqual({
                    0: {'a': 'b', 'c': 'd'},
                    1: {'a': 'z', 'e': 'f', 'c': 'd'},
                    }, utility._oops_messages)
            # Messages are removed when out of context.
            self.assertEqual(
                {0: {'a': 'b', 'c': 'd'}},
                utility._oops_messages)

    def test__makeErrorReport_includes_oops_messages(self):
        """The error report should include the oops messages."""
        utility = ErrorReportingUtility()
        with utility.oopsMessage(dict(a='b', c='d')):
            try:
                raise ArbitraryException('foo')
            except ArbitraryException:
                info = sys.exc_info()
                oops, _ = utility._makeErrorReport(info)
                self.assertEqual(
                    [('<oops-message-0>', "{'a': 'b', 'c': 'd'}")],
                    oops['req_vars'])

    def test__makeErrorReport_combines_request_and_error_vars(self):
        """The oops messages should be distinct from real request vars."""
        utility = ErrorReportingUtility()
        request = ScriptRequest([('c', 'd')])
        with utility.oopsMessage(dict(a='b')):
            try:
                raise ArbitraryException('foo')
            except ArbitraryException:
                info = sys.exc_info()
                oops, _ = utility._makeErrorReport(info, request)
                self.assertEqual(
                    [('<oops-message-0>', "{'a': 'b'}"), ('c', 'd')],
                    oops['req_vars'])

    def test_filter_session_statement(self):
        """Removes quoted strings if database_id is SQL-session."""
        utility = ErrorReportingUtility()
        statement = "SELECT 'gone'"
        self.assertEqual(
            "SELECT '%s'",
            utility.filter_session_statement('SQL-session', statement))

    def test_filter_session_statement_noop(self):
        """If database_id is not SQL-session, it's a no-op."""
        utility = ErrorReportingUtility()
        statement = "SELECT 'gone'"
        self.assertEqual(
            statement,
            utility.filter_session_statement('SQL-launchpad', statement))

    def test_session_queries_filtered(self):
        """Test that session queries are filtered."""
        utility = ErrorReportingUtility()
        request = ScriptRequest([], URL="test_session_queries_filtered")
        set_request_started()
        try:
            timeline = get_request_timeline(request)
            timeline.start("SQL-session", "SELECT 'gone'").finish()
            try:
                raise ArbitraryException('foo')
            except ArbitraryException:
                info = sys.exc_info()
                oops, _ = utility._makeErrorReport(info)
            self.assertEqual("SELECT '%s'", oops['db_statements'][0][3])
        finally:
            clear_request_started()



class TestSensitiveRequestVariables(testtools.TestCase):
    """Test request variables that should not end up in the stored OOPS.

    The _is_sensitive() method will return True for any variable name that
    should not be included in the OOPS.
    """

    def test_oauth_signature_is_sensitive(self):
        """The OAuth signature can be in the body of a POST request, but if
        that happens we don't want it to be included in the OOPS, so we need
        to mark it as sensitive.
        """
        request = TestRequest(
            environ={'SERVER_URL': 'http://api.launchpad.dev'},
            form={'oauth_signature': '&BTXPJ6pQTvh49r9p'})
        self.failUnless(_is_sensitive(request, 'oauth_signature'))


class TestRequestWithUnauthenticatedPrincipal(TestRequest):
    principal = UnauthenticatedPrincipal(42)


class TestRequestWithPrincipal(TestRequest):

    def setInWSGIEnvironment(self, key, value):
        self._orig_env[key] = value

    class principal:
        id = 42
        title = u'title'
        # non ASCII description
        description = u'description |\N{BLACK SQUARE}|'

        @staticmethod
        def getLogin():
            return u'Login'


class TestOopsLoggingHandler(TestCase):
    """Tests for a Python logging handler that logs OOPSes."""

    def assertOopsMatches(self, report, exc_type, exc_value):
        """Assert that 'report' is an OOPS of a particular exception.

        :param report: An `IErrorReport`.
        :param exc_type: The string of an exception type.
        :param exc_value: The string of an exception value.
        """
        self.assertEqual(exc_type, report.type)
        self.assertEqual(exc_value, report.value)
        self.assertTrue(
            report.tb_text.startswith('Traceback (most recent call last):\n'),
            report.tb_text)
        self.assertEqual('', report.pageid)
        self.assertEqual('None', report.username)
        self.assertEqual('None', report.url)
        self.assertEqual([], report.req_vars)
        self.assertEqual([], report.db_statements)

    def setUp(self):
        TestCase.setUp(self)
        self.logger = logging.getLogger(self.factory.getUniqueString())
        self.error_utility = ErrorReportingUtility()
        self.error_utility.log_namer._output_root = tempfile.mkdtemp()
        self.logger.addHandler(
            OopsLoggingHandler(error_utility=self.error_utility))
        self.addCleanup(
            remove_tree, self.error_utility.log_namer._output_root)

    def test_exception_records_oops(self):
        # When OopsLoggingHandler is a handler for a logger, any exceptions
        # logged will have OOPS reports generated for them.
        error_message = self.factory.getUniqueString()
        try:
            1 / 0
        except ZeroDivisionError:
            self.logger.exception(error_message)
        oops_report = self.error_utility.getLastOopsReport()
        self.assertOopsMatches(
            oops_report, 'ZeroDivisionError',
            'integer division or modulo by zero')

    def test_warning_does_nothing(self):
        # Logging a warning doesn't generate an OOPS.
        self.logger.warning("Cheeseburger")
        self.assertIs(None, self.error_utility.getLastOopsReport())

    def test_error_does_nothing(self):
        # Logging an error without an exception does nothing.
        self.logger.error("Delicious ponies")
        self.assertIs(None, self.error_utility.getLastOopsReport())


class TestOopsIgnoring(testtools.TestCase):

    def test_offsite_404_ignored(self):
        # A request originating from another site that generates a NotFound
        # (404) is ignored (i.e., no OOPS is logged).
        utility = ErrorReportingUtility()
        request = dict(HTTP_REFERER='example.com')
        self.assertTrue(utility._isIgnoredException('NotFound', request))

    def test_onsite_404_not_ignored(self):
        # A request originating from a local site that generates a NotFound
        # (404) produces an OOPS.
        utility = ErrorReportingUtility()
        request = dict(HTTP_REFERER='canonical.com')
        self.assertTrue(utility._isIgnoredException('NotFound', request))

    def test_404_without_referer_is_ignored(self):
        # If a 404 is generated and there is no HTTP referer, we don't produce
        # an OOPS.
        utility = ErrorReportingUtility()
        request = dict()
        self.assertTrue(utility._isIgnoredException('NotFound', request))

    def test_marked_exception_is_ignored(self):
        # If an exception has been marked as ignorable, then it is ignored.
        utility = ErrorReportingUtility()
        exception = Exception()
        directlyProvides(exception, IUnloggedException)
        self.assertTrue(
            utility._isIgnoredException('RuntimeError', exception=exception))

    def test_unmarked_exception_generates_oops(self):
        # If an exception has not been marked as ignorable, then it is not.
        utility = ErrorReportingUtility()
        exception = Exception()
        self.assertFalse(
            utility._isIgnoredException('RuntimeError', exception=exception))


class TestWrappedParameterConverter(testtools.TestCase):
    """Make sure URL parameter type conversions don't generate OOPS reports"""

    def test_return_value_untouched(self):
        # When a converter succeeds, its return value is passed through the
        # wrapper untouched.

        class FauxZopePublisherBrowserModule:
            def get_converter(self, type_):
                def the_converter(value):
                    return 'converted %r to %s' % (value, type_)
                return the_converter

        module = FauxZopePublisherBrowserModule()
        customize_get_converter(module)
        converter = module.get_converter('int')
        self.assertEqual("converted '42' to int", converter('42'))

    def test_value_errors_marked(self):
        # When a ValueError is raised by the wrapped converter, the exception
        # is marked with IUnloggedException so the OOPS machinery knows that a
        # report should not be logged.

        class FauxZopePublisherBrowserModule:
            def get_converter(self, type_):
                def the_converter(value):
                    raise ValueError
                return the_converter

        module = FauxZopePublisherBrowserModule()
        customize_get_converter(module)
        converter = module.get_converter('int')
        try:
            converter(42)
        except ValueError, e:
            self.assertTrue(IUnloggedException.providedBy(e))

    def test_other_errors_not_marked(self):
        # When an exception other than ValueError is raised by the wrapped
        # converter, the exception is not marked with IUnloggedException an
        # OOPS report will be created.

        class FauxZopePublisherBrowserModule:
            def get_converter(self, type_):
                def the_converter(value):
                    raise RuntimeError
                return the_converter

        module = FauxZopePublisherBrowserModule()
        customize_get_converter(module)
        converter = module.get_converter('int')
        try:
            converter(42)
        except RuntimeError, e:
            self.assertFalse(IUnloggedException.providedBy(e))

    def test_none_is_not_wrapped(self):
        # The get_converter function that we're wrapping can return None, in
        # that case there's no function for us to wrap and we just return None
        # as well.

        class FauxZopePublisherBrowserModule:
            def get_converter(self, type_):
                return None

        module = FauxZopePublisherBrowserModule()
        customize_get_converter(module)
        converter = module.get_converter('int')
        self.assertTrue(converter is None)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
