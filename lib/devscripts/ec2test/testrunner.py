# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Code to actually run the tests in an EC2 instance."""

__metaclass__ = type
__all__ = [
    'AVAILABLE_INSTANCE_TYPES',
    'DEFAULT_INSTANCE_TYPE',
    'EC2TestRunner',
    'TRUNK_BRANCH',
    ]

import os
import pickle
import re
import sys


from bzrlib.plugin import load_plugins
load_plugins()
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.config import GlobalConfig
from bzrlib.errors import UncommittedChanges
from bzrlib.plugins.launchpad.account import get_lp_login
from bzrlib.plugins.pqm.pqm_submit import (
    NoPQMSubmissionAddress, PQMSubmission)

import paramiko

from devscripts.ec2test.credentials import CredentialsError, EC2Credentials
from devscripts.ec2test.instance import EC2Instance
from devscripts.ec2test.sshconfig import SSHConfig

# XXX duplicated from __init__.py .. fix that
TRUNK_BRANCH = 'bzr+ssh://bazaar.launchpad.net/~launchpad-pqm/launchpad/devel'
DEFAULT_INSTANCE_TYPE = 'c1.xlarge'
AVAILABLE_INSTANCE_TYPES = ('m1.large', 'm1.xlarge', 'c1.xlarge')


class UnknownBranchURL(Exception):
    """Raised when we try to parse an unrecognized branch url."""

    def __init__(self, branch_url):
        Exception.__init__(
            self,
            "Couldn't parse '%s', not a Launchpad branch." % (branch_url,))

def validate_file(filename):
    """Raise an error if 'filename' is not a file we can write to."""
    if filename is None:
        return

    check_file = filename
    if os.path.exists(check_file):
        if not os.path.isfile(check_file):
            raise ValueError(
                'file argument %s exists and is not a file' % (filename,))
    else:
        check_file = os.path.dirname(check_file)
        if (not os.path.exists(check_file) or
            not os.path.isdir(check_file)):
            raise ValueError(
                'file %s cannot be created.' % (filename,))
    if not os.access(check_file, os.W_OK):
        raise ValueError(
            'you do not have permission to write %s' % (filename,))


def parse_branch_url(branch_url):
    """Given the URL of a branch, return its components in a dict."""
    _lp_match = re.compile(
        r'lp:\~([^/]+)/([^/]+)/([^/]+)$').match
    _bazaar_match = re.compile(
        r'bzr+ssh://bazaar.launchpad.net/\~([^/]+)/([^/]+)/([^/]+)$').match
    match = _lp_match(branch_url)
    if match is None:
        match = _bazaar_match(branch_url)
    if match is None:
        raise UnknownBranchURL(branch_url)
    owner = match.group(1)
    product = match.group(2)
    branch = match.group(3)
    unique_name = '~%s/%s/%s' % (owner, product, branch)
    url = 'bzr+ssh://bazaar.launchpad.net/%s' % (unique_name,)
    return dict(
        owner=owner, product=product, branch=branch, unique_name=unique_name,
        url=url)


def normalize_branch_input(data):
    """Given 'data' return a ('dest', 'src') pair.

    :param data: One of::
       - a double of (sourcecode_location, branch_url).
         If 'sourcecode_location' is Launchpad, then 'branch_url' can
         also be the name of a branch of launchpad owned by
         launchpad-pqm.
       - a singleton of (branch_url,)
       - a singleton of (sourcecode_location,) where
         sourcecode_location corresponds to a Launchpad upstream
         project as well as a rocketfuel sourcecode location.
       - a string which could populate any of the above singletons.

    :return: ('dest', 'src') where 'dest' is the destination
        sourcecode location in the rocketfuel tree and 'src' is the
        URL of the branch to put there. The URL can be either a bzr+ssh
        URL or the name of a branch of launchpad owned by launchpad-pqm.
    """
    # XXX: JonathanLange 2009-06-05: Should convert lp: URL branches to
    # bzr+ssh:// branches.
    if isinstance(data, basestring):
        data = (data,)
    if len(data) == 2:
        # Already in dest, src format.
        return data
    if len(data) != 1:
        raise ValueError(
            'invalid argument for ``branches`` argument: %r' %
            (data,))
    branch_location = data[0]
    try:
        parsed_url = parse_branch_url(branch_location)
    except UnknownBranchURL:
        return branch_location, 'lp:%s' % (branch_location,)
    return parsed_url['product'], parsed_url['url']


def parse_specified_branches(branches):
    """Given 'branches' from the command line, return a sanitized dict.

    The dict maps sourcecode locations to branch URLs, according to the
    rules in `normalize_branch_input`.
    """
    return dict(map(normalize_branch_input, branches))


class EC2TestRunner:

    name = 'ec2-test-runner'

    message = instance = image = None
    _running = False

    def __init__(self, branch, email=False, file=None, test_options='-vv',
                 headless=False, branches=(),
                 machine_id=None, instance_type=DEFAULT_INSTANCE_TYPE,
                 pqm_message=None, pqm_public_location=None,
                 pqm_submit_location=None, demo_networks=None,
                 open_browser=False, pqm_email=None,
                 include_download_cache_changes=None):
        """Create a new EC2TestRunner.

        This sets the following attributes:
          - original_branch
          - test_options
          - headless
          - include_download_cache_changes
          - download_cache_additions
          - branches (parses, validates)
          - message (after validating PQM submisson)
          - email (after validating email capabilities)
          - instance_type (validates)
          - image (after connecting to ec2)
          - file (after checking we can write to it)
          - ssh_config_file_name (after checking it exists)
          - vals, a dict containing
            - the environment
            - trunk_branch (either from global or derived from branches)
            - branch
            - smtp_server
            - smtp_username
            - smtp_password
            - email (distinct from the email attribute)
            - key_type
            - key
            - launchpad_login
        """
        self.original_branch = branch # just for easy access in debugging
        self.test_options = test_options
        self.headless = headless
        self.include_download_cache_changes = include_download_cache_changes
        if demo_networks is None:
            demo_networks = ()
        else:
            demo_networks = demo_networks
        self.open_browser = open_browser
        if headless and file:
            raise ValueError(
                'currently do not support files with headless mode.')
        if headless and not (email or pqm_message):
            raise ValueError('You have specified no way to get the results '
                             'of your headless test run.')

        if test_options != '-vv' and pqm_message is not None:
            raise ValueError(
                "Submitting to PQM with non-default test options isn't "
                "supported")

        trunk_specified = False
        trunk_branch = TRUNK_BRANCH

        # normalize and validate branches
        branches = parse_specified_branches(branches)
        try:
            launchpad_url = branches.pop('launchpad')
        except KeyError:
            # No Launchpad branch specified.
            pass
        else:
            try:
                parsed_url = parse_branch_url(launchpad_url)
            except UnknownBranchURL:
                user = 'launchpad-pqm'
                src = ('bzr+ssh://bazaar.launchpad.net/'
                       '~launchpad-pqm/launchpad/%s' % (launchpad_url,))
            else:
                user = parsed_url['owner']
                src = parsed_url['url']
            if user == 'launchpad-pqm':
                trunk_specified = True
            trunk_branch = src

        self.branches = branches.items()

        # XXX: JonathanLange 2009-05-31: The trunk_specified stuff above and
        # the pqm location stuff below are actually doing the equivalent of
        # preparing a merge directive. Perhaps we can leverage that to make
        # this code simpler.
        self.download_cache_additions = None
        if branch is None:
            config = GlobalConfig()
            if pqm_message is not None:
                raise ValueError('Cannot submit trunk to pqm.')
        else:
            (tree,
             bzrbranch,
             relpath) = BzrDir.open_containing_tree_or_branch(branch)
            # if tree is None, remote...I'm assuming.
            if tree is None:
                config = GlobalConfig()
            else:
                config = bzrbranch.get_config()

            if pqm_message is not None or tree is not None:
                # if we are going to maybe send a pqm_message, we're going to
                # go down this path. Also, even if we are not but this is a
                # local branch, we're going to use the PQM machinery to make
                # sure that the local branch has been made public, and has all
                # working changes there.
                if tree is None:
                    # remote.  We will make some assumptions.
                    if pqm_public_location is None:
                        pqm_public_location = branch
                    if pqm_submit_location is None:
                        pqm_submit_location = trunk_branch
                elif pqm_submit_location is None and trunk_specified:
                    pqm_submit_location = trunk_branch
                # modified from pqm_submit.py
                submission = PQMSubmission(
                    source_branch=bzrbranch,
                    public_location=pqm_public_location,
                    message=pqm_message or '',
                    submit_location=pqm_submit_location,
                    tree=tree)
                if tree is not None:
                    # this is the part we want to do whether or not we're
                    # submitting.
                    submission.check_tree() # any working changes
                    submission.check_public_branch() # everything public
                    branch = submission.public_location
                    if (include_download_cache_changes is None or
                        include_download_cache_changes):
                        # We need to get the download cache settings
                        cache_tree, cache_bzrbranch, cache_relpath = (
                            BzrDir.open_containing_tree_or_branch(
                                os.path.join(
                                    self.original_branch, 'download-cache')))
                        cache_tree.lock_read()
                        try:
                            cache_basis_tree = cache_tree.basis_tree()
                            cache_basis_tree.lock_read()
                            try:
                                delta = cache_tree.changes_from(
                                    cache_basis_tree, want_unversioned=True)
                                unversioned = [
                                    un for un in delta.unversioned
                                    if not cache_tree.is_ignored(un[0])]
                                added = delta.added
                                self.download_cache_additions = (
                                    unversioned + added)
                            finally:
                                cache_basis_tree.unlock()
                        finally:
                            cache_tree.unlock()
                if pqm_message is not None:
                    if self.download_cache_additions:
                        raise UncommittedChanges(cache_tree)
                    # get the submission message
                    mail_from = config.get_user_option('pqm_user_email')
                    if not mail_from:
                        mail_from = config.username()
                    # Make sure this isn't unicode
                    mail_from = mail_from.encode('utf8')
                    if pqm_email is None:
                        if tree is None:
                            pqm_email = (
                                "Launchpad PQM <launchpad@pqm.canonical.com>")
                        else:
                            pqm_email = config.get_user_option('pqm_email')
                    if not pqm_email:
                        raise NoPQMSubmissionAddress(bzrbranch)
                    mail_to = pqm_email.encode('utf8') # same here
                    self.message = submission.to_email(mail_from, mail_to)
                elif (self.download_cache_additions and
                      self.include_download_cache_changes is None):
                    raise UncommittedChanges(
                        cache_tree,
                        'You must select whether to include download cache '
                        'changes (see --include-download-cache-changes and '
                        '--ignore-download-cache-changes, -c and -g '
                        'respectively), or '
                        'commit or remove the files in the download-cache.')
        if email is not False:
            if email is True:
                email = [config.username()]
                if not email[0]:
                    raise ValueError('cannot find your email address.')
            elif isinstance(email, basestring):
                email = [email]
            else:
                tmp = []
                for item in email:
                    if not isinstance(item, basestring):
                        raise ValueError(
                            'email must be True, False, a string, or a list of '
                            'strings')
                    tmp.append(item)
                email = tmp
        else:
            email = None
        self.email = email

        # We do a lot of looking before leaping here because we want to avoid
        # wasting time and money on errors we could have caught early.

        # Validate instance_type and get default kernal and ramdisk.
        if instance_type not in AVAILABLE_INSTANCE_TYPES:
            raise ValueError('unknown instance_type %s' % (instance_type,))

        # Validate and set file.
        validate_file(file)
        self.file = file

        # Make a dict for string substitution based on the environ.
        #
        # XXX: JonathanLange 2009-06-02: Although this defintely makes the
        # scripts & commands easier to write, it makes it harder to figure out
        # how the different bits of the system interoperate (passing 'vals' to
        # a method means it uses...?). Consider changing things around so that
        # vals is not needed.
        self.vals = dict(os.environ)
        self.vals['trunk_branch'] = trunk_branch
        self.vals['branch'] = branch
        home = self.vals['HOME']

        # Email configuration.
        if email is not None or pqm_message is not None:
            server = self.vals['smtp_server'] = config.get_user_option(
                'smtp_server')
            if server is None or server == 'localhost':
                raise ValueError(
                    'To send email, a remotely accessible smtp_server (and '
                    'smtp_username and smtp_password, if necessary) must be '
                    'configured in bzr.  See the SMTP server information '
                    'here: https://wiki.canonical.com/EmailSetup .')
            self.vals['smtp_username'] = config.get_user_option(
                'smtp_username')
            self.vals['smtp_password'] = config.get_user_option(
                'smtp_password')
            from_email = config.username()
            if not from_email:
                raise ValueError(
                    'To send email, your bzr email address must be set '
                    '(use ``bzr whoami``).')
            else:
                self.vals['email'] = (
                    from_email.encode('utf8').encode('string-escape'))

        # Get a public key from the agent.
        agent = paramiko.Agent()
        keys = agent.get_keys()
        if len(keys) == 0:
            self.error_and_quit(
                'You must have an ssh agent running with keys installed that '
                'will allow the script to rsync to devpad and get your '
                'branch.\n')
        key = agent.get_keys()[0]
        self.vals['key_type'] = key.get_name()
        self.vals['key'] = key.get_base64()

        # Verify the .ssh config file
        self.ssh_config_file_name = os.path.join(home, '.ssh', 'config')
        if not os.path.exists(self.ssh_config_file_name):
            self.error_and_quit(
                'This script expects to find the .ssh config in %s.  Please '
                'make sure it exists and contains the necessary '
                'configuration to access devpad.' % (
                    self.ssh_config_file_name,))

        # Get the bzr login.
        login = get_lp_login()
        if not login:
            self.error_and_quit(
                'you must have set your launchpad login in bzr.')
        self.vals['launchpad-login'] = login

        # Get the AWS identifier and secret identifier.
        try:
            credentials = EC2Credentials.load_from_file()
        except CredentialsError, e:
            self.error_and_quit(str(e))

        # Make the EC2 connection.
        controller = credentials.connect(self.name)

        # We do this here because it (1) cleans things up and (2) verifies
        # that the account is correctly set up. Both of these are appropriate
        # for initialization.
        #
        # We always recreate the keypairs because there is no way to
        # programmatically retrieve the private key component, unless we
        # generate it.
        controller.delete_previous_key_pair()

        # get the image
        image = controller.acquire_image(machine_id)
        self._instance = EC2Instance(
            self.name, image, instance_type, demo_networks,
            controller, self.vals)
        # now, as best as we can tell, we should be good to go.

    def error_and_quit(self, msg):
        """Print error message and exit."""
        sys.stderr.write(msg)
        sys.exit(1)

    def log(self, msg):
        """Log a message on stdout, flushing afterwards."""
        # XXX: JonathanLange 2009-05-31 bug=383076: This should use Python
        # logging, rather than printing to stdout.
        sys.stdout.write(msg)
        sys.stdout.flush()

    def start(self):
        """Start the EC2 instance."""
        self._instance.start()

    def shutdown(self):
        if self.headless and self._running:
            self.log('letting instance run, to shut down headlessly '
                     'at completion of tests.\n')
            return
        return self._instance.shutdown()

    def configure_system(self):
        # AS ROOT
        root_connection = self._instance.connect_as_root()
        root_p = root_connection.perform
        if self.vals['USER'] == 'gary':
            # This helps gary debug problems others are having by removing
            # much of the initial setup used to work on the original image.
            root_p('deluser --remove-home gary', ignore_failure=True)
        # Let root perform sudo without a password.
        root_p('echo "root\tALL=NOPASSWD: ALL" >> /etc/sudoers')
        # Add the user.
        root_p('adduser --gecos "" --disabled-password %(USER)s')
        # Give user sudo without password.
        root_p('echo "%(USER)s\tALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers')
            # Make /var/launchpad owned by user.
        root_p('chown -R %(USER)s:%(USER)s /var/launchpad')
        # Clean out left-overs from the instance image.
        root_p('rm -fr /var/tmp/*')
        # Update the system.
        root_p('aptitude update')
        root_p('aptitude -y full-upgrade')
        # Set up ssh for user
        # Make user's .ssh directory
        root_p('sudo -u %(USER)s mkdir /home/%(USER)s/.ssh')
        root_sftp = root_connection.ssh.open_sftp()
        remote_ssh_dir = '/home/%(USER)s/.ssh' % self.vals
        # Create config file
        self.log('Creating %s/config\n' % (remote_ssh_dir,))
        ssh_config_source = open(self.ssh_config_file_name)
        config = SSHConfig()
        config.parse(ssh_config_source)
        ssh_config_source.close()
        ssh_config_dest = root_sftp.open("%s/config" % remote_ssh_dir, 'w')
        ssh_config_dest.write('CheckHostIP no\n')
        ssh_config_dest.write('StrictHostKeyChecking no\n')
        for hostname in ('devpad.canonical.com', 'chinstrap.canonical.com'):
            ssh_config_dest.write('Host %s\n' % (hostname,))
            data = config.lookup(hostname)
            for key in ('hostname', 'gssapiauthentication', 'proxycommand',
                        'user', 'forwardagent'):
                value = data.get(key)
                if value is not None:
                    ssh_config_dest.write('    %s %s\n' % (key, value))
        ssh_config_dest.write('Host bazaar.launchpad.net\n')
        ssh_config_dest.write('    user %(launchpad-login)s\n' % self.vals)
        ssh_config_dest.close()
        # create authorized_keys
        self.log('Setting up %s/authorized_keys\n' % remote_ssh_dir)
        authorized_keys_file = root_sftp.open(
            "%s/authorized_keys" % remote_ssh_dir, 'w')
        authorized_keys_file.write("%(key_type)s %(key)s\n" % self.vals)
        authorized_keys_file.close()
        root_sftp.close()
        # Chown and chmod the .ssh directory and contents that we just
        # created.
        root_p('chown -R %(USER)s:%(USER)s /home/%(USER)s/')
        root_p('chmod 644 /home/%(USER)s/.ssh/*')
        self.log(
            'You can now use ssh -A %s to log in the instance.\n' %
            self._instance.hostname)
        # give the user permission to do whatever in /var/www
        root_p('chown -R %(USER)s:%(USER)s /var/www')
        root_connection.close()

        # AS USER
        user_connection = self._instance.connect_as_user()
        user_p = user_connection.perform
        user_sftp = user_connection.ssh.open_sftp()
        # Set up bazaar.conf with smtp information if necessary
        if self.email or self.message:
            user_p('sudo -u %(USER)s mkdir /home/%(USER)s/.bazaar')
            bazaar_conf_file = user_sftp.open(
                "/home/%(USER)s/.bazaar/bazaar.conf" % self.vals, 'w')
            bazaar_conf_file.write(
                'smtp_server = %(smtp_server)s\n' % self.vals)
            if self.vals['smtp_username']:
                bazaar_conf_file.write(
                    'smtp_username = %(smtp_username)s\n' % self.vals)
            if self.vals['smtp_password']:
                bazaar_conf_file.write(
                    'smtp_password = %(smtp_password)s\n' % self.vals)
            bazaar_conf_file.close()
        # Copy remote ec2-remote over
        self.log('Copying ec2test-remote.py to remote machine.\n')
        user_sftp.put(
            os.path.join(os.path.dirname(os.path.realpath(__file__)),
                         'ec2test-remote.py'),
            '/var/launchpad/ec2test-remote.py')
        user_sftp.close()
        # Set up launchpad login and email
        user_p('bzr launchpad-login %(launchpad-login)s')
        user_p("bzr whoami '%(email)s'")
        user_connection.close()

    def prepare_tests(self):
        user_connection = self._instance.connect_as_user()
        # Clean up the test branch left in the instance image.
        user_connection.perform('rm -rf /var/launchpad/test')
        # get newest sources
        user_connection.run_with_ssh_agent(
            "rsync -avp --partial --delete "
            "--filter='P *.o' --filter='P *.pyc' --filter='P *.so' "
            "devpad.canonical.com:/code/rocketfuel-built/launchpad/sourcecode/* "
            "/var/launchpad/sourcecode/")
        # Get trunk.
        user_connection.run_with_ssh_agent(
            'bzr branch %(trunk_branch)s /var/launchpad/test')
        # Merge the branch in.
        if self.vals['branch'] is not None:
            user_connection.run_with_ssh_agent(
                'cd /var/launchpad/test; bzr merge %(branch)s')
        else:
            self.log('(Testing trunk, so no branch merge.)')
        # Get any new sourcecode branches as requested
        for dest, src in self.branches:
            fulldest = os.path.join('/var/launchpad/test/sourcecode', dest)
            if dest in ('canonical-identity-provider', 'shipit'):
                # These two branches share some of the history with Launchpad.
                # So we create a stacked branch on Launchpad so that the shared
                # history isn't duplicated.
                user_connection.run_with_ssh_agent(
                    'bzr branch --no-tree --stacked %s %s' %
                    (TRUNK_BRANCH, fulldest))
                # The --overwrite is needed because they are actually two
                # different branches (canonical-identity-provider was not
                # branched off launchpad, but some revisions are shared.)
                user_connection.run_with_ssh_agent(
                    'bzr pull --overwrite %s -d %s' % (src, fulldest))
                # The third line is necessary because of the --no-tree option
                # used initially. --no-tree doesn't create a working tree.
                # It only works with the .bzr directory (branch metadata and
                # revisions history). The third line creates a working tree
                # based on the actual branch.
                user_connection.run_with_ssh_agent(
                    'bzr checkout "%s" "%s"' % (fulldest, fulldest))
            else:
                # The "--standalone" option is needed because some branches
                # are/were using a different repository format than Launchpad
                # (bzr-svn branch for example).
                user_connection.run_with_ssh_agent(
                    'bzr branch --standalone %s %s' % (src, fulldest))
        # prepare fresh copy of sourcecode and buildout sources for building
        p = user_connection.perform
        p('rm -rf /var/launchpad/tmp')
        p('mkdir /var/launchpad/tmp')
        p('cp -R /var/launchpad/sourcecode /var/launchpad/tmp/sourcecode')
        p('mkdir /var/launchpad/tmp/eggs')
        user_connection.run_with_ssh_agent(
            'bzr co lp:lp-source-dependencies '
            '/var/launchpad/tmp/download-cache')
        if (self.include_download_cache_changes and
            self.download_cache_additions):
            sftp = user_connection.ssh.open_sftp()
            root = os.path.realpath(
                os.path.join(self.original_branch, 'download-cache'))
            for info in self.download_cache_additions:
                src = os.path.join(root, info[0])
                self.log('Copying %s to remote machine.\n' % (src,))
                sftp.put(
                    src,
                    os.path.join('/var/launchpad/tmp/download-cache', info[0]))
            sftp.close()
        p('/var/launchpad/test/utilities/link-external-sourcecode '
          '-p/var/launchpad/tmp -t/var/launchpad/test'),
        # set up database
        p('/var/launchpad/test/utilities/launchpad-database-setup %(USER)s')
        p('cd /var/launchpad/test && make build')
        p('cd /var/launchpad/test && make schema')
        # close ssh connection
        user_connection.close()

    def start_demo_webserver(self):
        """Turn ec2 instance into a demo server."""
        user_connection = self._instance.connect_as_user()
        p = user_connection.perform
        p('mkdir -p /var/tmp/bazaar.launchpad.dev/static')
        p('mkdir -p /var/tmp/bazaar.launchpad.dev/mirrors')
        p('sudo a2enmod proxy > /dev/null')
        p('sudo a2enmod proxy_http > /dev/null')
        p('sudo a2enmod rewrite > /dev/null')
        p('sudo a2enmod ssl > /dev/null')
        p('sudo a2enmod deflate > /dev/null')
        p('sudo a2enmod headers > /dev/null')
        # Install apache config file.
        p('cd /var/launchpad/test/; sudo make install')
        # Use raw string to eliminate the need to escape the backslash.
        # Put eth0's ip address in the /tmp/ip file.
        p(r"ifconfig eth0 | grep 'inet addr' "
          r"| sed -re 's/.*addr:([0-9.]*) .*/\1/' > /tmp/ip")
        # Replace 127.0.0.88 in Launchpad's apache config file with the
        # ip address just stored in the /tmp/ip file. Perl allows for
        # inplace editing unlike sed.
        p('sudo perl -pi -e "s/127.0.0.88/$(cat /tmp/ip)/g" '
          '/etc/apache2/sites-available/local-launchpad')
        # Restart apache.
        p('sudo /etc/init.d/apache2 restart')
        # Build mailman and minified javascript, etc.
        p('cd /var/launchpad/test/; make')
        # Start launchpad in the background.
        p('cd /var/launchpad/test/; make start')
        # close ssh connection
        user_connection.close()

    def run_tests(self):
        user_connection = self._instance.connect_as_user()

        # Make sure we activate the failsafe --shutdown feature.  This will
        # make the server shut itself down after the test run completes, or
        # if the test harness suffers a critical failure.
        cmd = ['python /var/launchpad/ec2test-remote.py --shutdown']

        # Do we want to email the results to the user?
        if self.email:
            for email in self.email:
                cmd.append("--email='%s'" % (
                    email.encode('utf8').encode('string-escape'),))

        # Do we want to submit the branch to PQM if the tests pass?
        if self.message is not None:
            cmd.append(
                "--submit-pqm-message='%s'" % (
                    pickle.dumps(
                        self.message).encode(
                        'base64').encode('string-escape'),))

        # Do we want to disconnect the terminal once the test run starts?
        if self.headless:
            cmd.append('--daemon')

        # Which branch do we want to test?
        if self.vals['branch'] is not None:
            branch = self.vals['branch']
            remote_branch = Branch.open(branch)
            branch_revno = remote_branch.revno()
        else:
            branch = self.vals['trunk_branch']
            branch_revno = None
        cmd.append('--public-branch=%s'  % branch)
        if branch_revno is not None:
            cmd.append('--public-branch-revno=%d' % branch_revno)

        # Add any additional options for ec2test-remote.py
        cmd.extend(self.get_remote_test_options())
        self.log(
            'Running tests... (output is available on '
            'http://%s/)\n' % self._instance.hostname)

        # Try opening a browser pointed at the current test results.
        if self.open_browser:
            try:
                import webbrowser
            except ImportError:
                self.log("Could not open web browser due to ImportError.")
            else:
                status = webbrowser.open(self._instance.hostname)
                if not status:
                    self.log("Could not open web browser.")

        # Run the remote script!  Our execution will block here until the
        # remote side disconnects from the terminal.
        user_connection.perform(' '.join(cmd))
        self._running = True

        if not self.headless:
            sftp = self._instance.ssh.open_sftp()
            # We ran to completion locally, so we'll be in charge of shutting
            # down the instance, in case the user has requested a postmortem.
            #
            # We only have 60 seconds to do this before the remote test
            # script shuts the server down automatically.
            user_connection.perform(
                'kill `cat /var/launchpad/ec2test-remote.pid`')

            # deliver results as requested
            if self.file:
                self.log(
                    'Writing abridged test results to %s.\n' % self.file)
                sftp.get('/var/www/summary.log', self.file)
            sftp.close()
        # close ssh connection
        self._instance.ssh.close()

    def get_remote_test_options(self):
        """Return the test command that will be passed to ec2test-remote.py.

        Returns a tuple of command-line options and switches.
        """
        if '--jscheck' in self.test_options:
            # We want to run the JavaScript test suite.
            return ('--jscheck',)
        else:
            # Run the normal testsuite with our Zope testrunner options.
            # ec2test-remote.py wants the extra options to be after a double-
            # dash.
            return ('--', self.test_options)
