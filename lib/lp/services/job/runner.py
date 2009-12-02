# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Facilities for running Jobs."""


from __future__ import with_statement
__metaclass__ = type


__all__ = ['JobRunner']


import sys

from ampoule import child, pool, main

from twisted.internet import reactor, defer
from twisted.protocols import amp
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.twistedsupport.task import (
    ParallelLimitedTaskConsumer, PollingTaskSource)
from lazr.delegates import delegates
import transaction

from lp.codehosting.vfs import get_scanner_server
from lp.services.scripts.base import LaunchpadCronScript
from lp.services.job.interfaces.job import LeaseHeld, IRunnableJob, IJob
from lp.services.mail.sendmail import MailController
from canonical.launchpad.webapp import errorlog

BOOTSTRAP = """\
import sys

def main(reactor, ampChildPath):
    from twisted.application import reactors
    reactors.installReactor(reactor)
    
    from twisted.python import log
    log.startLogging(sys.stderr)

    from twisted.internet import reactor, stdio
    from twisted.python import reflect

    ampChild = reflect.namedAny(ampChildPath)
    stdio.StandardIO(ampChild(), 3, 4)
    from canonical.launchpad import scripts
    scripts.execute_zcml_for_scripts(use_web_security=False)
    reactor.run()
main(sys.argv[-2], sys.argv[-1])
"""


class BaseRunnableJob:
    """Base class for jobs to be run via JobRunner.

    Derived classes should implement IRunnableJob, which requires implementing
    IRunnableJob.run.  They should have a `job` member which implements IJob.

    Subclasses may provide getOopsRecipients, to send mail about oopses.
    If so, they should also provide getOperationDescription.
    """
    delegates(IJob, 'job')

    user_error_types = ()

    def getOopsRecipients(self):
        """Return a list of email-ids to notify about oopses."""
        return self.getErrorRecipients()

    def getErrorRecipients(self):
        """Return a list of email-ids to notify about user errors."""
        return []

    def getOopsMailController(self, oops_id):
        """Return a MailController for notifying people about oopses.

        Return None if there is no-one to notify.
        """
        recipients = self.getOopsRecipients()
        if len(recipients) == 0:
            return None
        subject = 'Launchpad internal error'
        body = (
            'Launchpad encountered an internal error during the following'
            ' operation: %s.  It was logged with id %s.  Sorry for the'
            ' inconvenience.' % (self.getOperationDescription(), oops_id))
        from_addr = config.canonical.noreply_from_address
        return MailController(from_addr, recipients, subject, body)

    def getUserErrorMailController(self, e):
        """Return a MailController for notifying about user errors.

        Return None if there is no-one to notify.
        """
        recipients = self.getErrorRecipients()
        if len(recipients) == 0:
            return None
        subject = 'Launchpad error while %s' % self.getOperationDescription()
        body = (
            'Launchpad encountered an error during the following'
            ' operation: %s.  %s' % (self.getOperationDescription(), str(e)))
        from_addr = config.canonical.noreply_from_address
        return MailController(from_addr, recipients, subject, body)

    def notifyOops(self, oops):
        """Report this oops."""
        ctrl = self.getOopsMailController(oops.id)
        if ctrl is None:
            return
        ctrl.send()

    def getOopsVars(self):
        """See `IRunnableJob`."""
        return [('job_id', self.job.id)]

    def notifyUserError(self, e):
        """See `IRunnableJob`."""
        ctrl = self.getUserErrorMailController(e)
        if ctrl is None:
            return
        ctrl.send()


class BaseJobRunner(object):
    """Runner of Jobs."""

    def __init__(self, logger=None):
        self.completed_jobs = []
        self.incomplete_jobs = []
        self.logger = logger

    def runJob(self, job):
        """Attempt to run a job, updating its status as appropriate."""
        job = IRunnableJob(job)
        job.acquireLease()
        # Commit transaction to clear the row lock.
        transaction.commit()
        try:
            job.start()
            transaction.commit()
            job.run()
        except Exception:
            transaction.abort()
            job.fail()
            # Record the failure.
            transaction.commit()
            self.incomplete_jobs.append(job)
            raise
        else:
            # Commit transaction to update the DB time.
            transaction.commit()
            job.complete()
            self.completed_jobs.append(job)
        # Commit transaction to update job status.
        transaction.commit()

    def runJobHandleError(self, job):
        job = IRunnableJob(job)
        with errorlog.globalErrorUtility.oopsMessage(
            dict(job.getOopsVars())):
            try:
                self.runJob(job)
            except LeaseHeld:
                self.incomplete_jobs.append(job)
            except job.user_error_types, e:
                job.notifyUserError(e)
            except Exception:
                info = sys.exc_info()
                errorlog.globalErrorUtility.raising(info)
                oops = errorlog.globalErrorUtility.getLastOopsReport()
                job.notifyOops(oops)
                if self.logger is not None:
                    self.logger.info('Job resulted in OOPS: %s' % oops.id)


class JobRunner(BaseJobRunner):

    def __init__(self, jobs, logger=None):
        BaseJobRunner.__init__(self, logger=logger)
        self.jobs = jobs

    @classmethod
    def fromReady(cls, job_class, logger=None):
        """Return a job runner for all ready jobs of a given class."""
        return cls(job_class.iterReady(), logger)

    @classmethod
    def runFromSource(cls, job_source, logger):
        logger.info("Running synchronously.")
        runner = cls.fromReady(job_source, logger)
        runner.runAll()
        return runner

    def runAll(self):
        """Run all the Jobs for this JobRunner."""
        for job in self.jobs:
            self.runJobHandleError(job)


class RunAmpouleJob(amp.Command):

    arguments = [('job_id', amp.Integer())]
    response = [('success', amp.Integer())]


class JobRunnerProto(child.AMPChild):
    @RunAmpouleJob.responder
    def runAmpouleJob(self, job_id):
        runner = BaseJobRunner()
        from lp.code.model.branchmergeproposaljob import UpdatePreviewDiffJob
        job = UpdatePreviewDiffJob.get(job_id)
        server = get_scanner_server()
        server.setUp()
        try:
            runner.runJobHandleError(job)
        finally:
            server.tearDown()
        return {'success': len(runner.completed_jobs)}


class TwistedJobRunner(BaseJobRunner):

    def __init__(self, job_source, logger=None):
        import os
        starter = main.ProcessStarter(
            bootstrap=BOOTSTRAP, packages=('twisted', 'ampoule'),
            env={'PYTHONPATH': os.environ['PYTHONPATH'],
            'PATH': os.environ['PATH'],
            'LPCONFIG': os.environ['LPCONFIG']})
        BaseJobRunner.__init__(self, logger=logger)
        self.job_source = job_source
        self.pp = pool.ProcessPool(
            JobRunnerProto, min=1, max=1, starter=starter)

    def runJobInSubprocess(self, job):
        job_id = removeSecurityProxy(job).context.id
        deferred = self.pp.doWork(RunAmpouleJob, job_id = job_id)
        def update(response):
            if response['success']:
                self.completed_jobs.append(job)
            else:
                self.incomplete_jobs.append(job)
        deferred.addCallback(update)
        return deferred

    def getTaskSource(self):
        def producer():
            while True:
                for job in self.job_source.iterReady():
                    yield lambda: self.runJobInSubprocess(job)
                yield None
        return PollingTaskSource(5, producer().next)

    def doConsumer(self):
        consumer = ParallelLimitedTaskConsumer(1)
        return consumer.consume(self.getTaskSource())

    def runAll(self):
        self.pp.start()
        d = defer.maybeDeferred(self.doConsumer)
        d.addCallbacks(self.terminated, self.failed)

    def terminated(self, ignored=None):
        deferred = self.pp.stop()
        deferred.addBoth(lambda ignored: reactor.stop())

    def failed(self, failure):
        failure.printTraceback()
        self.terminated()

    @classmethod
    def runFromSource(cls, job_source, logger):
        logger.info("Running through Twisted.")
        runner = cls(job_source, logger)
        reactor.callWhenRunning(runner.runAll)
        reactor.run()
        return runner


class JobCronScript(LaunchpadCronScript):
    """Base class for scripts that run jobs."""

    def __init__(self, runner_class=JobRunner):
        dbuser = getattr(config, self.config_name).dbuser
        super(JobCronScript, self).__init__(self.config_name, dbuser)
        self.runner_class = runner_class

    def main(self):
        errorlog.globalErrorUtility.configure(self.config_name)
        cleanups = self.setUp()
        try:
            job_source = getUtility(self.source_interface)
            runner = self.runner_class.runFromSource(job_source, self.logger)
        finally:
            for cleanup in reversed(cleanups):
                cleanup()
        self.logger.info(
            'Ran %d %s jobs.',
            len(runner.completed_jobs), self.source_interface.__name__)
        self.logger.info(
            '%d %s jobs did not complete.',
            len(runner.incomplete_jobs), self.source_interface.__name__)
