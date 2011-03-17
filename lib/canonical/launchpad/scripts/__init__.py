# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Library functions for use in all scripts.

"""
__metaclass__ = type

__all__ = [
    'db_options',
    'execute_zcml_for_scripts',
    'log',
    'logger',
    'logger_options',
    'WatchedFileHandler',
    ]

import atexit
import os
import sys
from textwrap import dedent
import threading

from zope.configuration.config import ConfigurationMachine
from zope.security.management import setSecurityPolicy
from zope.security.simplepolicies import PermissiveSecurityPolicy
import zope.sendmail.delivery
import zope.site.hooks

from canonical import lp
from canonical.config import config
# these are intentional re-exports, apparently, used by *many* files.
from canonical.launchpad.scripts.logger import (
    log,
    logger,
    logger_options,
    )
# Intentional re-export, following along the lines of the logger module.
from canonical.launchpad.scripts.loghandlers import WatchedFileHandler
from canonical.launchpad.webapp.authorization import LaunchpadSecurityPolicy
from canonical.launchpad.webapp.interaction import (
    ANONYMOUS,
    setupInteractionByEmail,
    )


def execute_zcml_for_scripts(use_web_security=False):
    """Execute the zcml rooted at launchpad/script.zcml

    If use_web_security is True, the same security policy as the web
    application uses will be used. Otherwise everything protected by a
    permission is allowed, and everything else denied.
    """

    # When in testing mode, prevent some cases of erroneous layer usage.
    # But we don't want to import that module in production usage, thus
    # the conditional block.
    if 'canonical.testing.layers' in sys.modules:
        from canonical.testing.layers import (
                FunctionalLayer, BaseLayer, ZopelessLayer)
        assert not FunctionalLayer.isSetUp, \
                'Setting up Zopeless CA when Zopefull CA is already running'
        assert not BaseLayer.isSetUp or ZopelessLayer.isSetUp, """
                execute_zcml_for_scripts should not be called from tests.
                Instead, your test should use the Zopeless layer.
            """

    if config.isTestRunner():
        scriptzcmlfilename = 'script-testing.zcml'
    else:
        scriptzcmlfilename = 'script.zcml'

    scriptzcmlfilename = os.path.abspath(
        os.path.join(config.root, 'zcml', scriptzcmlfilename))

    from zope.configuration import xmlconfig

    # Hook up custom component architecture calls
    zope.site.hooks.setHooks()

    # Load server-independent site config
    context = ConfigurationMachine()
    xmlconfig.registerCommonDirectives(context)
    context = xmlconfig.file(
        scriptzcmlfilename, execute=True, context=context)

    if use_web_security:
        setSecurityPolicy(LaunchpadSecurityPolicy)
    else:
        setSecurityPolicy(PermissiveSecurityPolicy)

    # Register atexit handler to kill off mail delivery daemon threads, and
    # thus avoid spew at exit.  See:
    # http://mail.python.org/pipermail/python-list/2003-October/192044.html
    # http://mail.python.org/pipermail/python-dev/2003-September/038151.html
    # http://mail.python.org/pipermail/python-dev/2003-September/038153.html

    def kill_queue_processor_threads():
        for thread in threading.enumerate():
            if isinstance(
                thread, zope.sendmail.delivery.QueueProcessorThread):
                thread.stop()
                thread.join(30)
                if thread.isAlive():
                    raise RuntimeError(
                        "QueueProcessorThread did not shut down")
    atexit.register(kill_queue_processor_threads)

    # This is a convenient hack to set up a zope interaction, before we get
    # the proper API for having a principal / user running in scripts.
    # The script will have full permissions because of the
    # PermissiveSecurityPolicy set up in script.zcml.
    setupInteractionByEmail(ANONYMOUS)


def db_options(parser):
    """Add and handle default database connection options on the command line

    Adds -d (--database), -H (--host) and -U (--user)

    Parsed options provide dbname, dbhost and dbuser attributes.

    Generally, scripts will not need this and should instead pull their
    connection details from launchpad.config.config. The database setup and
    maintenance tools cannot do this however.

    dbname and dbhost are also propagated to config.database.dbname and
    config.database.dbhost. dbname, dbhost and dbuser are also propagated to
    lp.get_dbname(), lp.dbhost and lp.dbuser. This ensures that all systems will
    be using the requested connection details.

    To test, we first need to store the current values so we can reset them
    later.

    >>> dbname, dbhost, dbuser = lp.get_dbname(), lp.dbhost, lp.dbuser

    Ensure that command line options propagate to where we say they do

    >>> parser = OptionParser()
    >>> db_options(parser)
    >>> options, args = parser.parse_args(
    ...     ['--dbname=foo', '--host=bar', '--user=baz'])
    >>> options.dbname, lp.get_dbname(), config.database.dbname
    ('foo', 'foo', 'foo')
    >>> (options.dbhost, lp.dbhost, config.database.dbhost)
    ('bar', 'bar', 'bar')
    >>> (options.dbuser, lp.dbuser)
    ('baz', 'baz')

    Make sure that the default user is None

    >>> parser = OptionParser()
    >>> db_options(parser)
    >>> options, args = parser.parse_args([])
    >>> options.dbuser, lp.dbuser
    (None, None)

    Reset config

    >>> lp.dbhost, lp.dbuser = dbhost, dbuser
    """
    def dbname_callback(option, opt_str, value, parser):
        parser.values.dbname = value
        config_data = dedent("""
            [database]
            dbname: %s
            """ % value)
        config.push('dbname_callback', config_data)
        lp.dbname_override = value

    parser.add_option(
            "-d", "--dbname", action="callback", callback=dbname_callback,
            type="string", dest="dbname", default=config.database.rw_main_master,
            help="PostgreSQL database to connect to."
            )

    def dbhost_callback(options, opt_str, value, parser):
        parser.values.dbhost = value
        config_data = dedent("""
            [database]
            dbhost: %s
            """ % value)
        config.push('dbhost_callback', config_data)
        lp.dbhost = value

    parser.add_option(
             "-H", "--host", action="callback", callback=dbhost_callback,
             type="string", dest="dbhost", default=lp.dbhost,
             help="Hostname or IP address of PostgreSQL server."
             )

    def dbuser_callback(options, opt_str, value, parser):
        parser.values.dbuser = value
        lp.dbuser = value

    parser.add_option(
             "-U", "--user", action="callback", callback=dbuser_callback,
             type="string", dest="dbuser", default=None,
             help="PostgreSQL user to connect as."
             )

    # The default user is None for scripts (which translates to 'connect
    # as a PostgreSQL user named the same as the current Unix user').
    # If the -U option was not given on the command line, our callback is
    # never called so we need to set this different default here.
    # Same for dbhost
    lp.dbuser = None
    lp.dbhost = None
