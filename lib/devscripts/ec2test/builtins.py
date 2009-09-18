import pdb

from bzrlib.commands import Command
from bzrlib.errors import BzrCommandError
from bzrlib.help import help_commands
from bzrlib.option import ListOption, Option

import socket

from devscripts.ec2test.credentials import EC2Credentials
from devscripts.ec2test.instance import (
    AVAILABLE_INSTANCE_TYPES, DEFAULT_INSTANCE_TYPE, EC2Instance)
from devscripts.ec2test.testrunner import EC2TestRunner, TRUNK_BRANCH


branch_option = ListOption(
    'branch', type=str, short_name='b', argname='BRANCH',
    help=('Branches to include in this run in sourcecode. '
          'If the argument is only the project name, the trunk will be '
          'used (e.g., ``-b launchpadlib``).  If you want to use a '
          'specific branch, if it is on launchpad, you can usually '
          'simply specify it instead (e.g., '
          '``-b lp:~username/launchpadlib/branchname``).  If this does '
          'not appear to work, or if the desired branch is not on '
          'launchpad, specify the project name and then the branch '
          'after an equals sign (e.g., '
          '``-b launchpadlib=lp:~username/launchpadlib/branchname``). '
          'Branches for multiple projects may be specified with '
          'multiple instances of this option. '
          'You may also use this option to specify the branch of launchpad '
          'into which your branch may be merged.  This defaults to %s. '
          'Because typically the important branches of launchpad are owned '
          'by the launchpad-pqm user, you can shorten this to only the '
          'branch name, if desired, and the launchpad-pqm user will be '
          'assumed.  For instance, if you specify '
          '``-b launchpad=db-devel`` then this is equivalent to '
          '``-b lp:~launchpad-pqm/launchpad/db-devel``, or the even longer'
          '``-b launchpad=lp:~launchpad-pqm/launchpad/db-devel``.'
          % (TRUNK_BRANCH,)))


machine_id_option = Option(
    'machine', short_name='m', type=str,
    help=('The AWS machine identifier (AMI) on which to base this run. '
          'You should typically only have to supply this if you are '
          'testing new AWS images. Defaults to trying to find the most '
          'recent one with an approved owner.'))


def _convert_instance_type(arg):
    """Ensure that `arg` is acceptable as an instance type."""
    if arg not in AVAILABLE_INSTANCE_TYPES:
        raise BzrCommandError('Unknown instance type %r' % arg)
    return arg


instance_type_option = Option(
    'instance', short_name='i', type=_convert_instance_type,
    param_name='instance_type',
    help=('The AWS instance type on which to base this run. '
          'Available options are %r. Defaults to `%s`.' %
          (AVAILABLE_INSTANCE_TYPES, DEFAULT_INSTANCE_TYPE)))


debug_option = Option(
    'debug', short_name='d',
    help=('Drop to pdb trace as soon as possible.'))


trunk_option = Option(
    'trunk', short_name='t',
    help=('Run the trunk as the branch'))


include_download_cache_changes_option = Option(
    'include-download-cache-changes', short_name='c',
    help=('Include any changes in the download cache (added or unknown) '
          'in the download cache of the test run.  Note that, if you have '
          'any changes in your download cache, trying to submit to pqm '
          'will always raise an error.  Also note that, if you have any '
          'changes in your download cache, you must explicitly choose to '
          'include or ignore the changes.'))


class EC2Command(Command):
    """Subclass of `Command` that customizes usage to say 'ec2' not 'bzr'.

    When https://bugs.edge.launchpad.net/bzr/+bug/431054 is fixed, we can
    delete this class, or at least make it less of a copy/paste/hack of the
    superclass.
    """

    def _usage(self):
        """Return single-line grammar for this command.

        Only describes arguments, not options.
        """
        s = 'ec2 ' + self.name() + ' '
        for aname in self.takes_args:
            aname = aname.upper()
            if aname[-1] in ['$', '+']:
                aname = aname[:-1] + '...'
            elif aname[-1] == '?':
                aname = '[' + aname[:-1] + ']'
            elif aname[-1] == '*':
                aname = '[' + aname[:-1] + '...]'
            s += aname + ' '
        s = s[:-1]      # remove last space
        return s


class cmd_test(EC2Command):
    """Run the test suite in ec2."""

    takes_options = [
        branch_option,
        trunk_option,
        machine_id_option,
        instance_type_option,
        Option(
            'file', short_name='f',
            help=('Store abridged test results in FILE.')),
        ListOption(
            'email', short_name='e', argname='EMAIL', type=str,
            help=('Email address to which results should be mailed.  Defaults to '
                  'the email address from `bzr whoami`. May be supplied multiple '
                  'times. The first supplied email address will be used as the '
                  'From: address.')),
        Option(
            'noemail', short_name='n',
            help=('Do not try to email results.')),
        Option(
            'test-options', short_name='o', type=str,
            help=('Test options to pass to the remote test runner.  Defaults to '
                  "``-o '-vv'``.  For instance, to run specific tests, you might "
                  "use ``-o '-vvt my_test_pattern'``.")),
        Option(
            'submit-pqm-message', short_name='s', type=str, argname="MSG",
            help=('A pqm message to submit if the test run is successful.  If '
                  'provided, you will be asked for your GPG passphrase before '
                  'the test run begins.')),
        Option(
            'pqm-public-location', type=str,
            help=('The public location for the pqm submit, if a pqm message is '
                  'provided (see --submit-pqm-message).  If this is not provided, '
                  'for local branches, bzr configuration is consulted; for '
                  'remote branches, it is assumed that the remote branch *is* '
                  'a public branch.')),
        Option(
            'pqm-submit-location', type=str,
            help=('The submit location for the pqm submit, if a pqm message is '
                  'provided (see --submit-pqm-message).  If this option is not '
                  'provided, the script will look for an explicitly specified '
                  'launchpad branch using the -b/--branch option; if that branch '
                  'was specified and is owned by the launchpad-pqm user on '
                  'launchpad, it is used as the pqm submit location. Otherwise, '
                  'for local branches, bzr configuration is consulted; for '
                  'remote branches, it is assumed that the submit branch is %s.'
                  % (TRUNK_BRANCH,))),
        Option(
            'pqm-email', type=str,
            help=('Specify the email address of the PQM you are submitting to. '
                  'If the branch is local, then the bzr configuration is '
                  'consulted; for remote branches "Launchpad PQM '
                  '<launchpad@pqm.canonical.com>" is used by default.')),
        Option(
            'postmortem', short_name='p',
            help=('Drop to interactive prompt after the test and before shutting '
                  'down the instance for postmortem analysis of the EC2 instance '
                  'and/or of this script.')),
        Option(
            'headless',
            help=('After building the instance and test, run the remote tests '
                  'headless.  Cannot be used with postmortem '
                  'or file.')),
        debug_option,
        Option(
            'open-browser',
            help=('Open the results page in your default browser')),
        include_download_cache_changes_option,
        ]

    takes_args = ['test_branch?']

    def run(self, test_branch=None, branch=[], trunk=False, machine=None,
            instance_type=DEFAULT_INSTANCE_TYPE,
            file=None, email=None, test_options='-vv', noemail=False,
            submit_pqm_message=None, pqm_public_location=None,
            pqm_submit_location=None, pqm_email=None, postmortem=False,
            headless=False, debug=False, open_browser=False,
            include_download_cache_changes=False):
        if debug:
            pdb.set_trace()
        if trunk:
            if test_branch is not None:
                raise BzrCommandError(
                    "Cannot specify both a branch to test and --trunk")
            else:
                test_branch = TRUNK_BRANCH
        else:
            if test_branch is None:
                test_branch = '.'
        if ((postmortem or file) and headless):
            raise BzrCommandError(
                'Headless mode currently does not support postmortem or file '
                ' options.')
        if noemail:
            if email:
                raise BzrCommandError(
                    'May not supply both --no-email and an --email address')
        else:
            if email == []:
                email = True
        branches = [data.split('=', 1) for data in branch]

        if headless and not (email or submit_pqm_message):
            raise BzrCommandError(
                'You have specified no way to get the results '
                'of your headless test run.')


        instance = EC2Instance(
            EC2TestRunner.name, instance_type, machine)

        runner = EC2TestRunner(
            test_branch, email=email, file=file,
            test_options=test_options, headless=headless,
            branches=branches, pqm_message=submit_pqm_message,
            pqm_public_location=pqm_public_location,
            pqm_submit_location=pqm_submit_location,
            open_browser=open_browser, pqm_email=pqm_email,
            include_download_cache_changes=include_download_cache_changes,
            instance=instance, vals=instance._vals)

        instance.set_up_and_run(postmortem, not headless, runner.run_tests)


class cmd_demo(EC2Command):
    """Start a demo instance of Launchpad.

    See https://wiki.canonical.com/Launchpad/EC2Test/ForDemos
    """

    takes_options = [
        branch_option,
        trunk_option,
        machine_id_option,
        instance_type_option,
        Option(
            'postmortem', short_name='p',
            help=('Drop to interactive prompt after the test and before shutting '
                  'down the instance for postmortem analysis of the EC2 instance '
                  'and/or of this script.')),
        debug_option,
        include_download_cache_changes_option,
        ListOption(
            'demo', type=str,
            help="Allow this netmask to connect to the instance."),
        ]

    takes_args = ['test_branch?']

    def run(self, test_branch=None, branch=[], trunk=False, machine=None,
            instance_type=DEFAULT_INSTANCE_TYPE, debug=False,
            include_download_cache_changes=False, demo=None):
        if debug:
            pdb.set_trace()
        if trunk:
            if test_branch is not None:
                raise BzrCommandError(
                    "Cannot specify both a branch to test and --trunk")
            else:
                test_branch = TRUNK_BRANCH
        else:
            if test_branch is None:
                test_branch = '.'
        branches = [data.split('=', 1) for data in branch]

        instance = EC2Instance.make(
            EC2TestRunner.name, instance_type, machine, demo)

        runner = EC2TestRunner(
            test_branch, branches=branches,
            include_download_cache_changes=include_download_cache_changes,
            instance=instance, vals=instance._vals)

        demo_network_string = '\n'.join(
            '  ' + network for network in demo)

        instance.set_up_and_run(
            True, False, self.run_server, runner,
            demo_network_string)


    def run_server(self, runner, instance, demo_network_string):
        runner.run_demo_server()
        ec2_ip = socket.gethostbyname(instance.hostname)
        print (
            "\n\n"
            "********************** DEMO *************************\n"
            "It may take 20 seconds for the demo server to start up."
            "\nTo demo to other users, you still need to open up\n"
            "network access to the ec2 instance from their IPs by\n"
            "entering command like this in the interactive python\n"
            "interpreter at the end of the setup. "
            "\n  instance.security_group.authorize("
            "'tcp', 443, 443, '10.0.0.5/32')\n\n"
            "These demo networks have already been granted access on "
            "port 80 and 443:\n" + demo_network_string +
            "\n\nYou also need to edit your /etc/hosts to point\n"
            "launchpad.dev at the ec2 instance's IP like this:\n"
            "  " + ec2_ip + "    launchpad.dev\n\n"
            "See "
            "<https://wiki.canonical.com/Launchpad/EC2Test/ForDemos>."
            "\n*****************************************************"
            "\n\n")



class cmd_update_image(EC2Command):
    """Make a new AMI."""

    takes_options = [
        machine_id_option,
        instance_type_option,
        Option(
            'postmortem', short_name='p',
            help=('Drop to interactive prompt after the test and before shutting '
                  'down the instance for postmortem analysis of the EC2 instance '
                  'and/or of this script.')),
        debug_option,
        ListOption(
            'extra-update-image-command', type=str,
            help=('Run this command (with an ssh agent) on the image before '
                  'running the default update steps.  Can be passed more than '
                  'once, the commands will be run in the order specified.')),
        ]

    takes_args = ['ami_name']

    def run(self, ami_name, machine=None, instance_type='m1.large',
            debug=False, postmortem=False, extra_update_image_command=[]):
        if debug:
            pdb.set_trace()

        credentials = EC2Credentials.load_from_file()

        instance = EC2Instance.make(
            EC2TestRunner.name, instance_type, machine,
            credentials=credentials)
        instance.check_bundling_prerequisites()

        instance.set_up_and_run(
            postmortem, True, self.update_image, instance,
            extra_update_image_command, ami_name, credentials)

    def update_image(self, instance, extra_update_image_command, ami_name,
                     credentials):
        user_connection = instance.connect_as_user()
        user_connection.perform('bzr launchpad-login %(launchpad-login)s')
        for cmd in extra_update_image_command:
            user_connection.run_with_ssh_agent(cmd)
        user_connection.run_with_ssh_agent(
            "rsync -avp --partial --delete "
            "--filter='P *.o' --filter='P *.pyc' --filter='P *.so' "
            "devpad.canonical.com:/code/rocketfuel-built/launchpad/sourcecode/* "
            "/var/launchpad/sourcecode/")
        user_connection.run_with_ssh_agent(
            'bzr pull -d /var/launchpad/test ' + TRUNK_BRANCH)
        user_connection.run_with_ssh_agent(
            'bzr pull -d /var/launchpad/download-cache lp:lp-source-dependencies')
        user_connection.close()
        root_connection = instance.connect_as_root()
        root_connection.perform(
            'deluser --remove-home %(USER)s', ignore_failure=True)
        root_connection.close()
        instance.bundle(ami_name, credentials)


class cmd_help(EC2Command):
    """Show general help or help for a command."""

    aliases = ["?", "--help", "-?", "-h"]
    takes_args = ["topic?"]

    def run(self, topic=None):
        """
        Show help for the C{bzrlib.commands.Command} matching C{topic}.

        @param topic: Optionally, the name of the topic to show.  Default is
            to show some basic usage information.
        """
        if topic is None:
            print >>self.outf, 'Usage:    ec2 <command> <options>'
            print >>self.outf
            print >>self.outf, 'Available commands:'
            help_commands(self.outf)
        else:
            command = self.controller._get_command(None, topic)
            if command is None:
                print >>self.outf, "%s is an unknown command." % (topic,)
            text = command.get_help_text()
            if text:
                print >>self.outf, text
