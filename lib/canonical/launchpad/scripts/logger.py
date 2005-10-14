# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""Logging setup for scripts.

Don't import from this module. Import it from canonical.scripts.

Parts of this may be moved into canonical.launchpad somewhere if it is
to be used for non-script stuff.
"""

__metaclass__ = type

# Don't import stuff from this module. Import it from canonical.scripts
__all__ = ['log', 'logger', 'logger_options']

import logging
import re
import sha
import sys
import time
from optparse import OptionParser
from cStringIO import StringIO

from zope.component import getUtility

from canonical.base import base
from canonical.librarian.interfaces import ILibrarianClient, UploadFailed
from canonical.config import config

class LibrarianFormatter(logging.Formatter):
    """A logging.Formatter that stores tracebacks in the Librarian and emits
    a URL rather than emitting the traceback directly.

    The traceback will be emitted as a fallback if the Librarian cannot be
    contacted.
    """
    def formatException(self, ei):
        """Format the exception and store it in the Librian.
        
        Returns the URL, or the formatted exception if the Librarian is
        not available.
        """
        traceback = logging.Formatter.formatException(self, ei)
        try:
            librarian = getUtility(ILibrarianClient)
        except LookupError:
            return traceback

        exception_string = ''
        try:
            exception_string = str(ei[1]).encode('ascii')
        except:
            pass
        if not exception_string:
            exception_string = str(ei[0]).split('.')[-1]
   
        try:
            filename = base(
                    long(sha.new(traceback).hexdigest(),16), 62
                    ) + '.txt'
            url = librarian.remoteAddFile(
                    filename, len(traceback), StringIO(traceback),
                    'text/plain;charset=%s' % sys.getdefaultencoding()
                    )
            return ' -> %s (%s)' % (url, exception_string)
        except UploadFailed:
            return traceback
        except:
            # Exceptions raised by the Formatter get swallowed, but we want
            # to know about them. Since we are already spitting out exception
            # information, we can stuff our own problems in there too.
            return '%s\n\nException raised in formatter:\n%s\n' % (
                    traceback,
                    logging.Formatter.formatException(self, sys.exc_info())
                    )


def logger_options(parser, default=logging.INFO):
    """Add the --verbose and --quiet options to an optparse.OptionParser.

    The requested loglevel will end up in the option's loglevel attribute.

    >>> from optparse import OptionParser
    >>> parser = OptionParser()
    >>> logger_options(parser)
    >>> options, args = parser.parse_args(['-v', '-v', '-q', '-q', '-q'])
    >>> options.loglevel == logging.WARNING
    True

    >>> options, args = parser.parse_args([])
    >>> options.loglevel == logging.INFO
    True

    Cleanup:
    >>> reset_root_logger()

    As part of the options parsing, the 'log' global variable is updated.
    This can be used by code too lazy to pass it around as a variable.
    """

    # Raise an exception if the constants have changed. If they change we
    # will need to fix the arithmetic
    assert logging.DEBUG == 10
    assert logging.INFO == 20
    assert logging.WARNING == 30
    assert logging.ERROR == 40
    assert logging.CRITICAL == 50

    def counter(option, opt_str, value, parser, inc):
        parser.values.loglevel = (
                getattr(parser.values, 'loglevel', default) + inc
                )
        # Reset the global log
        global log
        log._log = _logger(parser.values.loglevel)

    parser.add_option(
            "-v", "--verbose", dest="loglevel", default=default,
            action="callback", callback=counter, callback_args=(-10, ),
            help="Increase verbosity. May be specified multiple times."
            )
    parser.add_option(
            "-q", "--quiet",
            action="callback", callback=counter, callback_args=(10, ),
            help="Decrease verbosity. May be specified multiple times."
            )

    # Set the global log
    global log
    log._log = _logger(default)


def logger(options=None, name=None):
    """Return a logging instance with standard setup.

    options should be the options as returned by an option parser that
    has been initilized with logger_options(parser)

    >>> from optparse import OptionParser
    >>> parser = OptionParser()
    >>> logger_options(parser)
    >>> options, args = parser.parse_args(['-v', '-v', '-q', '-q', '-q'])
    >>> log = logger(options)
    >>> log.debug("Not shown - I'm too quiet")

    Cleanup:
    >>> reset_root_logger()
    """ #'
    if options is None:
        parser = OptionParser()
        logger_options(parser)
        options, args = parser.parse_args()

    return _logger(options.loglevel, name)


def reset_root_logger():
    root_logger = logging.getLogger()
    for hdlr in root_logger.handlers[:]:
        hdlr.flush()
        hdlr.close()
        root_logger.removeHandler(hdlr)

def _logger(level, name=None):
    """Create the actual logger instance, logging at the given level

    if name is None, it will get args[0] without the extension (e.g. gina).
    """

    if name is None:
        # Determine the logger name from the script name
        name = sys.argv[0]
        name = re.sub('.py[oc]?$', '', name)

    # Clamp the loglevel
    if level < logging.DEBUG:
        level = logging.DEBUG
    elif level > logging.CRITICAL:
        level = logging.CRITICAL

    # We install our custom handlers and formatters on the root logger.
    # This means that if the root logger is used, we still get correct
    # formatting. The root logger should probably not be used.
    root_logger = logging.getLogger()

    # reset state of root logger
    reset_root_logger()

    # Make it print output in a standard format, suitable for 
    # both command line tools and cron jobs (command line tools often end
    # up being run from inside cron, so this is a good thing).
    hdlr = logging.StreamHandler(strm=sys.stderr)
    if config.default_section == 'testrunner':
        # Don't output timestamps in the test environment
        fmt = '%(levelname)-7s %(message)s'
    else:
        fmt='%(asctime)s %(levelname)-7s %(message)s'
    formatter = LibrarianFormatter(
        fmt=fmt,
        # Put date back if we need it, but I think just time is fine and
        # saves space.
        datefmt="%H:%M:%S",
        )
    formatter.converter = time.gmtime # Output should be UTC
    hdlr.setFormatter(formatter)
    root_logger.addHandler(hdlr)

    # Create our logger
    logger = logging.getLogger(name)

    logger.setLevel(level)


    global log
    log._log = logger

    return logger


class _LogWrapper:
    """Changes the logger instance.

    Other modules will do 'from canonical.launchpad.scripts import log'.
    This wrapper allows us to change the logger instance these other modules
    use, by replacing the _log attribute. This is done each call to logger()
    """

    def __init__(self, log):
        self._log = log

    def __getattr__(self, key):
        return getattr(self._log, key)

    def __setattr__(self, key, value):
        if key == '_log':
            self.__dict__['_log'] = value
            return value
        else:
            return setattr(self._log, key, value)

log = _LogWrapper(logging.getLogger())


