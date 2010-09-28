# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test cron script for processing jobs from any job source class."""

__metaclass__ = type

import os
import subprocess

import transaction
from zope.component import getUtility

from canonical.config import config
from canonical.testing import LaunchpadFunctionalLayer
from lp.registry.interfaces.teammembership import (
    ITeamMembershipSet,
    TeamMembershipStatus,
    )
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    )


class ProcessJobSourceTest(TestCaseWithFactory):
    """Test the process-job-source.py script."""
    layer = LaunchpadFunctionalLayer

    def _run(self, *args):
        script = os.path.join(
            config.root, 'cronscripts', 'process-job-source.py')
        cmd = [script] + list(args)
        process = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        (stdout, empty_stderr) = process.communicate()
        return stdout

    def test_missing_argument(self):
        output = self._run()
        self.assertIn('Usage:', output)
        self.assertIn('process-job-source.py [options] JOB_SOURCE', output)

    def test_empty_queue(self):
        output = self._run('IMembershipNotificationJobSource')
        expected = (
            'INFO    Creating lockfile: /var/lock/launchpad-process-job-'
            'source-IMembershipNotificationJobSource.lock\n'
            'INFO    Running synchronously.\n')
        self.assertEqual(expected, output)

    def test_processed(self):
        person = self.factory.makePerson(name='murdock')
        team = self.factory.makeTeam(name='a-team')
        login_person(team.teamowner)
        team.addMember(person, team.teamowner)
        membership_set = getUtility(ITeamMembershipSet)
        tm = membership_set.getByPersonAndTeam(person, team)
        tm.setStatus(TeamMembershipStatus.ADMIN, team.teamowner)
        transaction.commit()
        output = self._run('-v', 'IMembershipNotificationJobSource')
        self.assertIn(
            ('DEBUG   Running <MEMBERSHIP_NOTIFICATION branch job (1) '
             'for murdock as part of a-team. status=Waiting>'),
            output)
        self.assertIn('DEBUG   MembershipNotificationJob sent email', output)
        self.assertIn('Ran 1 MembershipNotificationJob jobs.', output)


class ProcessJobSourceGroupsTest(TestCaseWithFactory):
    """Test the process-job-source-groups.py script."""
    layer = LaunchpadFunctionalLayer

    def _run(self, *args):
        script = os.path.join(
            config.root, 'cronscripts', 'process-job-source-groups.py')
        cmd = [script] + list(args)
        process = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        (stdout, empty_stderr) = process.communicate()
        return stdout

    def test_missing_argument(self):
        output = self._run()
        self.assertIn(
            ('Usage: process-job-source-groups.py '
             '[ -e JOB_SOURCE ] GROUP [GROUP]...'),
            output)
        self.assertIn('-e JOB_SOURCE, --exclude=JOB_SOURCE', output)
        self.assertIn('At least one group must be specified.', output)
        self.assertIn('Group: MAIN\n    IMembershipNotificationJobSource',
                      output)

    def test_empty_queue(self):
        output = self._run('MAIN')
        expected = (
            'INFO    Creating lockfile: /var/lock/launchpad-'
            'processjobsourcegroups.lock\n'
            'INFO    Creating lockfile: /var/lock/launchpad-process-job-'
            'source-IMembershipNotificationJobSource.lock\n'
            'INFO    Running synchronously.\n')
        self.assertEqual(expected, output)

    def test_processed(self):
        person = self.factory.makePerson(name='murdock')
        team = self.factory.makeTeam(name='a-team')
        login_person(team.teamowner)
        team.addMember(person, team.teamowner)
        membership_set = getUtility(ITeamMembershipSet)
        tm = membership_set.getByPersonAndTeam(person, team)
        tm.setStatus(TeamMembershipStatus.ADMIN, team.teamowner)
        transaction.commit()
        output = self._run('-v', 'MAIN')
        self.assertIn(
            ('DEBUG   Running <MEMBERSHIP_NOTIFICATION branch job (1) '
             'for murdock as part of a-team. status=Waiting>'),
            output)
        self.assertIn('DEBUG   MembershipNotificationJob sent email', output)
        self.assertIn('Ran 1 MembershipNotificationJob jobs.', output)
