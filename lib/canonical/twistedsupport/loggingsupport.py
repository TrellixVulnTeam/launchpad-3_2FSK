# Copyright 2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0702

"""Integration between the normal Launchpad logging and Twisted's."""

__metaclass__ = type
__all__ = [
    'OOPSLoggingObserver',
    'log_oops_from_failure',
    'set_up_logging_for_script',
    'set_up_oops_reporting',
    ]


from twisted.python import log

from canonical.launchpad.scripts import logger
from canonical.launchpad.webapp import errorlog


class OOPSLoggingObserver(log.PythonLoggingObserver):
    """A version of `PythonLoggingObserver` that logs OOPSes for errors."""

    # XXX: JonathanLange 2008-12-23: As best as I can tell, this ought to be a
    # log *handler*, not a feature of the bridge from Twisted->Python logging.
    # Ask Michael about this.

    def emit(self, eventDict):
        """See `PythonLoggingObserver.emit`."""
        if eventDict.get('isError', False) and 'failure' in eventDict:
            try:
                failure = eventDict['failure']
                now = eventDict.get('error_time')
                request = log_oops_from_failure(failure, now=now)
                self.logger.info(
                    "Logged OOPS id %s: %s: %s",
                    request.oopsid, failure.type.__name__, failure.value)
            except:
                self.logger.exception("Error reporting OOPS:")
        else:
            log.PythonLoggingObserver.emit(self, eventDict)


def log_oops_from_failure(failure, now=None, URL=None, **args):
    request = errorlog.ScriptRequest(args.items(), URL=URL)
    errorlog.globalErrorUtility.raising(
        (failure.type, failure.value, failure.getTraceback()),
        request, now)
    return request


def set_up_logging_for_script(options, name):
    """Create a `Logger` object and configure twisted to use it.

    This also configures oops reporting to use the section named
    'name'."""
    logger_object = logger(options, name)
    set_up_oops_reporting(name)
    return logger_object


def set_up_oops_reporting(name):
    errorlog.globalErrorUtility.configure(name)
    log.startLoggingWithObserver(OOPSLoggingObserver(loggerName=name).emit)

