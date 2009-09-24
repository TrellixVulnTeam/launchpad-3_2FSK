# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Code to represent a single machine instance in EC2."""

__metaclass__ = type
__all__ = [
    'EC2Instance',
    ]

import code
import glob
import os
import select
import socket
import subprocess
import sys
import time
import traceback

from bzrlib.errors import BzrCommandError
from bzrlib.plugins.launchpad.account import get_lp_login

import paramiko

from devscripts.ec2test.credentials import EC2Credentials


DEFAULT_INSTANCE_TYPE = 'c1.xlarge'
AVAILABLE_INSTANCE_TYPES = ('m1.large', 'm1.xlarge', 'c1.xlarge')

class AcceptAllPolicy:
    """We accept all unknown host key."""

    # Normally the console output is supposed to contain the Host key
    # but it doesn't seem to be the case here, so we trust that the host
    # we are connecting to is the correct one.
    def missing_host_key(self, client, hostname, key):
        pass


def get_user_key():
    """Get a SSH key from the agent.  Raise an error if not found.

    This key will be used to let the user log in (as $USER) to the instance.
    """
    agent = paramiko.Agent()
    keys = agent.get_keys()
    if len(keys) == 0:
        raise BzrCommandError(
            'You must have an ssh agent running with keys installed that '
            'will allow the script to rsync to devpad and get your '
            'branch.\n')
    user_key = agent.get_keys()[0]
    return user_key


# Commands to run to turn a blank image into one usable for the rest of the
# ec2 functionality.  They come in two parts, one set that need to be run as
# root and another that should be run as the 'ec2test' user.

from_scratch_root = """
set -xe

sed -ie 's/main universe/main universe multiverse/' /etc/apt/sources.list

. /etc/lsb-release

cat >> /etc/apt/sources.list << EOF
deb http://ppa.launchpad.net/launchpad/ubuntu $DISTRIB_CODENAME main
deb http://ppa.launchpad.net/bzr/ubuntu $DISTRIB_CODENAME main
deb http://ppa.launchpad.net/bzr-beta-ppa/ubuntu $DISTRIB_CODENAME main
EOF

# This next part is cribbed from rocketfuel-setup
dev_host() {
  sed -i 's/^127.0.0.88.*$/&\ ${hostname}/' /etc/hosts
}

echo 'Adding development hosts on local machine'
echo '
# Launchpad virtual domains. This should be on one line.
127.0.0.88      launchpad.dev
' >> /etc/hosts

declare -a hostnames
hostnames=$(cat <<EOF
    answers.launchpad.dev
    api.launchpad.dev
    bazaar-internal.launchpad.dev
    beta.launchpad.dev
    blueprints.launchpad.dev
    bugs.launchpad.dev
    code.launchpad.dev
    feeds.launchpad.dev
    id.launchpad.dev
    keyserver.launchpad.dev
    lists.launchpad.dev
    openid.launchpad.dev
    ppa.launchpad.dev
    private-ppa.launchpad.dev
    shipit.edubuntu.dev
    shipit.kubuntu.dev
    shipit.ubuntu.dev
    translations.launchpad.dev
    xmlrpc-private.launchpad.dev
    xmlrpc.launchpad.dev
EOF
    )

for hostname in $hostnames; do
  dev_host;
done

echo '
127.0.0.99      bazaar.launchpad.dev
' >> /etc/hosts

# Add the keys for the three PPAs added to sources.list above.
apt-key adv --recv-keys --keyserver pool.sks-keyservers.net 2af499cb24ac5f65461405572d1ffb6c0a5174af
apt-key adv --recv-keys --keyserver pool.sks-keyservers.net ece2800bacf028b31ee3657cd702bf6b8c6c1efd
apt-key adv --recv-keys --keyserver pool.sks-keyservers.net cbede690576d1e4e813f6bb3ebaf723d37b19b80

aptitude update
aptitude -y full-upgrade

apt-get -y install launchpad-developer-dependencies apache2 apache2-mpm-worker

# Creat the ec2test user, give them passwordless sudo.
adduser --gecos "" --disabled-password ec2test
echo 'ec2test\tALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers

mkdir /home/ec2test/.ssh
cat > /home/ec2test/.ssh/config << EOF
CheckHostIP no
StrictHostKeyChecking no
EOF

mkdir /var/launchpad
chown -R ec2test:ec2test /var/www /var/launchpad /home/ec2test/
"""


from_scratch_ec2test = """
set -xe

bzr launchpad-login %(launchpad-login)s
bzr init-repo --2a /var/launchpad
bzr branch lp:~mwhudson/launchpad/no-more-devpad-ssh /var/launchpad/test
bzr branch --standalone lp:lp-source-dependencies /var/launchpad/download-cache
mkdir /var/launchpad/sourcecode
/var/launchpad/test/utilities/update-sourcecode /var/launchpad/sourcecode
"""


class EC2Instance:
    """A single EC2 instance."""

    @classmethod
    def make(cls, name, instance_type, machine_id, demo_networks=None,
             credentials=None):
        """Construct an `EC2Instance`.

        :param name: The name to use for the key pair and security group for
            the instance.
        :param instance_type: One of the AVAILABLE_INSTANCE_TYPES.
        :param machine_id: The AMI to use, or None to do the usual regexp
            matching.  If you put 'based-on:' before the AMI id, it is assumed
            that the id specifies a blank image that should be made into one
            suitable for the other ec2 functions (see `from_scratch_root` and
            `from_scratch_ec2test` above).
        :param demo_networks: A list of networks to add to the security group
            to allow access to the instance.
        :param credentials: An `EC2Credentials` object.
        """
        if instance_type not in AVAILABLE_INSTANCE_TYPES:
            raise ValueError('unknown instance_type %s' % (instance_type,))

        # We call this here so that it has a chance to complain before the
        # instance is started (which can take some time).
        get_user_key()

        if credentials is None:
            credentials = EC2Credentials.load_from_file()

        # Make the EC2 connection.
        account = credentials.connect(name)

        # We do this here because it (1) cleans things up and (2) verifies
        # that the account is correctly set up. Both of these are appropriate
        # for initialization.
        #
        # We always recreate the keypairs because there is no way to
        # programmatically retrieve the private key component, unless we
        # generate it.
        account.delete_previous_key_pair()

        if machine_id and machine_id.startswith('based-on:'):
            from_scratch = True
            machine_id = machine_id[len('based-on:'):]
        else:
            from_scratch = False

        # get the image
        image = account.acquire_image(machine_id)

        vals = os.environ.copy()
        login = get_lp_login()
        if not login:
            raise BzrCommandError(
                'you must have set your launchpad login in bzr.')
        vals['launchpad-login'] = login

        return EC2Instance(
            name, image, instance_type, demo_networks, account, vals,
            from_scratch)

    def __init__(self, name, image, instance_type, demo_networks, account,
                 vals, from_scratch):
        self._name = name
        self._image = image
        self._account = account
        self._instance_type = instance_type
        self._demo_networks = demo_networks
        self._boto_instance = None
        self._vals = vals
        self._from_scratch = from_scratch

    def log(self, msg):
        """Log a message on stdout, flushing afterwards."""
        # XXX: JonathanLange 2009-05-31 bug=383076: Should delete this and use
        # Python logging module instead.
        sys.stdout.write(msg)
        sys.stdout.flush()

    def start(self):
        """Start the instance."""
        if self._boto_instance is not None:
            self.log('Instance %s already started' % self._boto_instance.id)
            return
        start = time.time()
        self.private_key = self._account.acquire_private_key()
        self.security_group = self._account.acquire_security_group(
            demo_networks=self._demo_networks)
        reservation = self._image.run(
            key_name=self._name, security_groups=[self._name],
            instance_type=self._instance_type)
        self._boto_instance = reservation.instances[0]
        self.log('Instance %s starting..' % self._boto_instance.id)
        while self._boto_instance.state == 'pending':
            self.log('.')
            time.sleep(5)
            self._boto_instance.update()
        if self._boto_instance.state == 'running':
            self.log(' started on %s\n' % self.hostname)
            elapsed = time.time() - start
            self.log('Started in %d minutes %d seconds\n' %
                     (elapsed // 60, elapsed % 60))
            self._output = self._boto_instance.get_console_output()
            self.log(self._output.output)
            self._ec2test_user_has_keys = False
        else:
            raise BzrCommandError(
                'failed to start: %s\n' % self._boto_instance.state)

    def shutdown(self):
        """Shut down the instance."""
        if self._boto_instance is None:
            self.log('no instance created\n')
            return
        self._boto_instance.update()
        if self._boto_instance.state not in ('shutting-down', 'terminated'):
            # terminate instance
            self._boto_instance.stop()
            self._boto_instance.update()
        self.log('instance %s\n' % (self._boto_instance.state,))

    @property
    def hostname(self):
        if self._boto_instance is None:
            return None
        return self._boto_instance.public_dns_name

    def _connect(self, username):
        """Connect to the instance as `user`. """
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(AcceptAllPolicy())
        connect_args = {
            'username': username,
            'pkey': self.private_key,
            'allow_agent': False,
            'look_for_keys': False,
            }
        for count in range(10):
            try:
                ssh.connect(self.hostname, **connect_args)
            except (socket.error, paramiko.AuthenticationException), e:
                self.log('_connect: %r\n' % (e,))
                if count < 9:
                    time.sleep(5)
                    self.log('retrying...')
                else:
                    raise
            else:
                break
        return EC2InstanceConnection(self, username, ssh)

    def _upload_local_key(self, conn, remote_filename):
        """ """
        user_key = get_user_key()
        authorized_keys_file = conn.sftp.open(remote_filename, 'w')
        authorized_keys_file.write(
            "%s %s\n" % (user_key.get_name(), user_key.get_base64()))
        authorized_keys_file.close()

    def connect(self):
        """Connect to the instance as a user with passwordless sudo.

        This may involve first connecting as root and adding SSH keys to the
        user's account, and in the case of a from scratch image, it will do a
        lot of set up.
        """
        if self._from_scratch:
            root_connection = self._connect('root')
            self._upload_local_key(root_connection, 'local_key')
            root_connection.perform(
                'cat local_key >> ~/.ssh/authorized_keys && rm local_key')
            root_connection.run_script(from_scratch_root % self._vals)
            root_connection.close()
            # Don't set self._from_scratch to True yet, we haven't run
            # from_scratch_ec2test yet!
        if not self._ec2test_user_has_keys:
            root_connection = self._connect('root')
            self._upload_local_key(root_connection, 'local_key')
            root_connection.perform(
                'cat /root/.ssh/authorized_keys local_key '
                '> /home/ec2test/.ssh/authorized_keys && rm local_key')
            root_connection.perform('chown -R ec2test:ec2test /home/ec2test/')
            root_connection.perform('chmod 644 /home/ec2test/.ssh/*')
            root_connection.close()
            self.log(
                'You can now use ssh -A ec2test@%s to log in the instance.\n' %
                self.hostname)
            self._ec2test_user_has_keys = True
        conn = self._connect('ec2test')
        if self._from_scratch:
            conn.run_script(from_scratch_ec2test % self._vals)
            self._from_scratch = False
        return conn

    def set_up_and_run(self, config, func, *args, **kw):
        """Start, run `func` and then maybe shut down.

        :param config: A dictionary specifying details of how the instance
            should be run:
             * `postmortem`: If true, any exceptions will be caught and an
               interactive session run to allow debugging the problem.
               Defaults to False.
             * `shutdown`: If true, shut down the instance after `func` and
               postmortem (if any) are completed.  Defaults to True.
        :param func: A callable that will be called when the instance is
            running and a user account has been set up on it.
        :param args: Passed to `func`.
        :param kw: Passed to `func`.
        """
        self.start()
        try:
            try:
                return func(*args, **kw)
            except Exception:
                # When running in postmortem mode, it is really helpful to see if
                # there are any exceptions before it waits in the console (in the
                # finally block), and you can't figure out why it's broken.
                traceback.print_exc()
        finally:
            try:
                if config.get('postmortem', False):
                    console = code.InteractiveConsole(locals())
                    console.interact((
                        'Postmortem Console.  EC2 instance is not yet dead.\n'
                        'It will shut down when you exit this prompt (CTRL-D).\n'
                        '\n'
                        'Tab-completion is enabled.'
                        '\n'
                        'EC2Instance is available as `instance`.\n'
                        'Also try these:\n'
                        '  http://%(dns)s/current_test.log\n'
                        '  ssh -A %(dns)s') %
                                     {'dns': self.hostname})
                    print 'Postmortem console closed.'
            finally:
                if config.get('shutdown', True):
                    self.shutdown()

    def _copy_single_file(self, sftp, local_path, remote_dir):
        """Copy `local_path` to `remote_dir` on this instance.

        The name in the remote directory will be that of the local file.

        :param sftp: A paramiko SFTP object.
        :param local_path: The local path.
        :param remote_dir: The directory on the instance to copy into.
        """
        name = os.path.basename(local_path)
        remote_path = os.path.join(remote_dir, name)
        remote_file = sftp.open(remote_path, 'w')
        remote_file.write(open(local_path).read())
        remote_file.close()
        return remote_path

    def copy_key_and_certificate_to_image(self, sftp):
        """Copy the AWS private key and certificate to the image.

        :param sftp: A paramiko SFTP object.
        """
        remote_ec2_dir = '/mnt/ec2'
        remote_pk = self._copy_single_file(
            sftp, self.local_pk, remote_ec2_dir)
        remote_cert = self._copy_single_file(
            sftp, self.local_cert, remote_ec2_dir)
        return (remote_pk, remote_cert)

    def _check_single_glob_match(self, local_dir, pattern, file_kind):
        """Check that `pattern` matches one file in `local_dir` and return it.

        :param local_dir: The local directory to look in.
        :param pattern: The glob patten to match.
        :param file_kind: The sort of file we're looking for, to be used in
            error messages.
        """
        pattern = os.path.join(local_dir, pattern)
        matches = glob.glob(pattern)
        if len(matches) != 1:
            raise BzrCommandError(
                '%r must match a single %s file' % (pattern, file_kind))
        return matches[0]

    def check_bundling_prerequisites(self):
        """Check, as best we can, that all the files we need to bundle exist.
        """
        local_ec2_dir = os.path.expanduser('~/.ec2')
        if not os.path.exists(local_ec2_dir):
            raise BzrCommandError(
                "~/.ec2 must exist and contain aws_user, aws_id, a private "
                "key file and a certificate.")
        aws_user_file = os.path.expanduser('~/.ec2/aws_user')
        if not os.path.exists(aws_user_file):
            raise BzrCommandError(
                "~/.ec2/aws_user must exist and contain your numeric AWS id.")
        self.aws_user = open(aws_user_file).read().strip()
        self.local_cert = self._check_single_glob_match(
            local_ec2_dir, 'cert-*.pem', 'certificate')
        self.local_pk = self._check_single_glob_match(
            local_ec2_dir, 'pk-*.pem', 'private key')

    def bundle(self, name, credentials):
        """Bundle, upload and register the instance as a new AMI.

        :param name: The name-to-be of the new AMI.
        :param credentials: An `EC2Credentials` object.
        """
        connection = self.connect()
        connection.perform('rm -f .ssh/authorized_keys')
        connection.perform('sudo mkdir /mnt/ec2')
        connection.perform('sudo chown $USER:$USER /mnt/ec2')

        remote_pk, remote_cert =  self.copy_key_and_certificate_to_image(
            connection.sftp)

        bundle_dir = os.path.join('/mnt', name)

        connection.perform('sudo mkdir ' + bundle_dir)
        connection.perform(' '.join([
            'sudo ec2-bundle-vol',
            '-d %s' % bundle_dir,
            '--batch',   # Set batch-mode, which doesn't use prompts.
            '-k %s' % remote_pk,
            '-c %s' % remote_cert,
            '-u %s' % self.aws_user,
            ]))

        # Assume that the manifest is 'image.manifest.xml', since "image" is
        # the default prefix.
        manifest = os.path.join(bundle_dir, 'image.manifest.xml')

        # Best check that the manifest actually exists though.
        test = 'test -f %s' % manifest
        connection.perform(test)

        connection.perform(' '.join([
            'sudo ec2-upload-bundle',
            '-b %s' % name,
            '-m %s' % manifest,
            '-a %s' % credentials.identifier,
            '-s %s' % credentials.secret,
            ]))

        connection.close()

        # This is invoked locally.
        mfilename = os.path.basename(manifest)
        manifest_path = os.path.join(name, mfilename)

        env = os.environ.copy()
        if 'JAVA_HOME' not in os.environ:
            env['JAVA_HOME'] = '/usr/lib/jvm/default-java'
        cmd = [
            'ec2-register',
            '--private-key=%s' % self.local_pk,
            '--cert=%s' % self.local_cert,
            manifest_path
            ]
        self.log("Executing command: %s" % ' '.join(cmd))
        subprocess.check_call(cmd, env=env)


class EC2InstanceConnection:
    """An ssh connection to an `EC2Instance`."""

    def __init__(self, instance, username, ssh):
        self._instance = instance
        self._username = username
        self._ssh = ssh
        self._sftp = None

    @property
    def sftp(self):
        if self._sftp is None:
            self._sftp = self._ssh.open_sftp()
        return self._sftp

    def perform(self, cmd, ignore_failure=False, out=None):
        """Perform 'cmd' on server.

        :param ignore_failure: If False, raise an error on non-zero exit
            statuses.
        :param out: A stream to write the output of the remote command to.
        """
        cmd = cmd % self._instance._vals
        self._instance.log(
            '%s@%s$ %s\n'
            % (self._username, self._instance._boto_instance.id, cmd))
        session = self._ssh.get_transport().open_session()
        session.exec_command(cmd)
        session.shutdown_write()
        while 1:
            select.select([session], [], [], 0.5)
            if session.recv_ready():
                data = session.recv(4096)
                if data:
                    sys.stdout.write(data)
                    sys.stdout.flush()
                    if out is not None:
                        out.write(data)
            if session.recv_stderr_ready():
                data = session.recv_stderr(4096)
                if data:
                    sys.stderr.write(data)
                    sys.stderr.flush()
            if session.exit_status_ready():
                break
        session.close()
        # XXX: JonathanLange 2009-05-31: If the command is killed by a signal
        # on the remote server, the SSH protocol does not send an exit_status,
        # it instead sends a different message with the number of the signal
        # that killed the process. AIUI, this code will fail confusingly if
        # that happens.
        res = session.recv_exit_status()
        if res and not ignore_failure:
            raise RuntimeError('Command failed: %s' % (cmd,))
        return res

    def run_with_ssh_agent(self, cmd, ignore_failure=False):
        """Run 'cmd' in a subprocess.

        Use this to run commands that require local SSH credentials. For
        example, getting private branches from Launchpad.
        """
        cmd = cmd % self._instance._vals
        self._instance.log(
            '%s@%s$ %s\n'
            % (self._username, self._instance._boto_instance.id, cmd))
        call = ['ssh', '-A', self._username + '@' + self._instance.hostname,
               '-o', 'CheckHostIP no',
               '-o', 'StrictHostKeyChecking no',
               '-o', 'UserKnownHostsFile ~/.ec2/known_hosts',
               cmd]
        res = subprocess.call(call)
        if res and not ignore_failure:
            raise RuntimeError('Command failed: %s' % (cmd,))
        return res

    def run_script(self, script_text):
        script = self.sftp.open('script.sh', 'w')
        script.write(script_text)
        script.close()
        self.run_with_ssh_agent('/bin/bash script.sh')
        # At least for mwhudson, the paramiko connection often drops while the
        # script is running.  Reconnect just in case.
        self.close()
        self._ssh = self._instance._connect(self._username)._ssh
        self.perform('rm script.sh')

    def close(self):
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        self._ssh.close()
        self._ssh = None
