# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os
import signal
import socket
import subprocess
import threading
import time

from bzrlib import (
    osutils,
    tests,
    trace,
    )
from bzrlib.plugins import lpserve

from canonical.config import config
from lp.codehosting import get_bzr_path, get_BZR_PLUGIN_PATH_for_subprocess


class TestingLPServiceInAThread(lpserve.LPService):
    """Wrap starting and stopping an LPService instance in a thread."""

    # For testing, we set the timeouts much lower, because we want the tests to
    # run quickly
    WAIT_FOR_CHILDREN_TIMEOUT = 0.5
    SOCKET_TIMEOUT = 0.01
    SLEEP_FOR_CHILDREN_TIMEOUT = 0.01

    def __init__(self, host='127.0.0.1', port=0):
        self.service_started = threading.Event()
        self.service_stopped = threading.Event()
        self.this_thread = None
        super(TestingLPServiceInAThread, self).__init__(host=host, port=port)

    def _create_master_socket(self):
        trace.mutter('creating master socket')
        super(TestingLPServiceInAThread, self)._create_master_socket()
        trace.mutter('setting service_started')
        self.service_started.set()

    def main_loop(self):
        self.service_stopped.clear()
        super(TestingLPServiceInAThread, self).main_loop()
        self.service_stopped.set()

    @staticmethod
    def start_service(test):
        """Start a new LPService in a thread on a random port.

        This will block until the service has created its socket, and is ready
        to communicate.

        :return: A new TestingLPServiceInAThread instance
        """
        # Allocate a new port on only the loopback device
        new_service = TestingLPServiceInAThread()
        thread = threading.Thread(target=new_service.main_loop,
                                  name='TestingLPServiceInAThread')
        new_service.this_thread = thread
        # should we be doing thread.setDaemon(True) ?
        thread.start()
        new_service.service_started.wait(10.0)
        if not new_service.service_started.isSet():
            raise RuntimeError(
                'Failed to start the TestingLPServiceInAThread')
        test.addCleanup(new_service.stop_service)
        # what about returning new_service._sockname ?
        return new_service

    def stop_service(self):
        """Stop the test-server thread. This can be called multiple times."""
        if self.this_thread is None:
            # We already stopped the process
            return
        self._should_terminate.set()
        self.service_stopped.wait(10.0)
        if not self.service_stopped.isSet():
            raise RuntimeError(
                'Failed to stop the TestingLPServiceInAThread')
        self.this_thread.join()
        # Break any refcycles
        self.this_thread = None


class TestTestingLPServiceInAThread(tests.TestCaseWithTransport):

    def test_start_and_stop_service(self):
        service = TestingLPServiceInAThread.start_service(self)
        service.stop_service()

    def test_multiple_stops(self):
        service = TestingLPServiceInAThread.start_service(self)
        service.stop_service()
        service.stop_service()

    def test_autostop(self):
        # We shouldn't leak a thread here, as it should be part of the test
        # case teardown.
        service = TestingLPServiceInAThread.start_service(self)


class TestCaseWithLPService(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithLPService, self).setUp()
        self.service = TestingLPServiceInAThread.start_service(self)

    def send_message_to_service(self, message):
        host, port = self.service._sockname
        addrs = socket.getaddrinfo(host, port, socket.AF_UNSPEC,
            socket.SOCK_STREAM, 0, socket.AI_PASSIVE)
        (family, socktype, proto, canonname, sockaddr) = addrs[0]
        client_sock = socket.socket(family, socktype, proto)
        try:
            client_sock.connect(sockaddr)
            client_sock.sendall(message)
            response = client_sock.recv(1024)
        except socket.error, e:
            raise RuntimeError('Failed to connect: %s' % (e,))
        return response


class TestLPService(TestCaseWithLPService):

    def test_send_quit_message(self):
        response = self.send_message_to_service('quit\n')
        self.assertEqual('quit command requested... exiting\n', response)
        self.service.service_stopped.wait(10.0)
        self.assertTrue(self.service.service_stopped.isSet())

    def test_send_invalid_message_fails(self):
        response = self.send_message_to_service('unknown\n')
        self.assertStartsWith(response, 'FAILURE')

    def test_send_hello_heartbeat(self):
        response = self.send_message_to_service('hello\n')
        self.assertEqual('yep, still alive\n', response)


class TestCaseWithLPServiceSubprocess(tests.TestCaseWithTransport):
    """Tests will get a separate process to communicate to.

    The number of these tests should be small, because it is expensive to start
    and stop the daemon.

    TODO: This should probably use testresources, or layers somehow...
    """

    def setUp(self):
        super(TestCaseWithLPServiceSubprocess, self).setUp()
        self.service_process, self.service_port = self.start_service_subprocess()
        self.addCleanup(self.stop_service)

    def send_message_to_service(self, message):
        addrs = socket.getaddrinfo('127.0.0.1', self.service_port,
            socket.AF_UNSPEC, socket.SOCK_STREAM, 0, socket.AI_PASSIVE)
        (family, socktype, proto, canonname, sockaddr) = addrs[0]
        client_sock = socket.socket(family, socktype, proto)
        try:
            client_sock.connect(sockaddr)
            client_sock.sendall(message)
            response = client_sock.recv(1024)
        except socket.error, e:
            raise RuntimeError('Failed to connect: %s' % (e,))
        return response

    def get_python_path(self):
        """Return the path to the Python interpreter."""
        return '%s/bin/py' % config.root

    def start_bzr_subprocess(self, process_args, env_changes=None,
                             working_dir=None):
        """Start bzr in a subprocess for testing.

        Copied and modified from `bzrlib.tests.TestCase.start_bzr_subprocess`.
        This version removes some of the skipping stuff, some of the
        irrelevant comments (e.g. about win32) and uses Launchpad's own
        mechanisms for getting the path to 'bzr'.

        Comments starting with 'LAUNCHPAD' are comments about our
        modifications.
        """
        if env_changes is None:
            env_changes = {}
        env_changes['BZR_PLUGIN_PATH'] = get_BZR_PLUGIN_PATH_for_subprocess()
        old_env = {}

        def cleanup_environment():
            for env_var, value in env_changes.iteritems():
                old_env[env_var] = osutils.set_or_unset_env(env_var, value)

        def restore_environment():
            for env_var, value in old_env.iteritems():
                osutils.set_or_unset_env(env_var, value)

        cwd = None
        if working_dir is not None:
            cwd = osutils.getcwd()
            os.chdir(working_dir)

        # LAUNCHPAD: Because of buildout, we need to get a custom Python
        # binary, not sys.executable.
        python_path = self.get_python_path()
        # LAUNCHPAD: We can't use self.get_bzr_path(), since it'll find
        # lib/bzrlib, rather than the path to sourcecode/bzr/bzr.
        bzr_path = get_bzr_path()
        try:
            cleanup_environment()
            command = [python_path, bzr_path]
            command.extend(process_args)
            process = self._popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        finally:
            restore_environment()
            if cwd is not None:
                os.chdir(cwd)

        return process

    def start_service_subprocess(self):
        # Make sure this plugin is exposed to the subprocess
        # SLOOWWW (~2.4 seconds, which is why we are doing the work anyway)
        old_val = osutils.set_or_unset_env('BZR_PLUGIN_PATH',
                                           lpserve.__path__[0])
        self.addCleanup(osutils.set_or_unset_env, 'BZR_PLUGIN_PATH', old_val)
        proc = self.start_bzr_subprocess(['lp-service', '--port', '127.0.0.1:0'])
        trace.mutter('started lp-service subprocess')
        preload_line = proc.stderr.readline()
        self.assertStartsWith(preload_line, 'Preloading')
        prefix = 'Listening on port: '
        port_line = proc.stderr.readline()
        self.assertStartsWith(port_line, prefix)
        port = int(port_line[len(prefix):])
        trace.mutter(port_line)
        return proc, port

    def stop_service(self):
        if self.service_process is None:
            # Already stopped
            return
        # First, try to stop the service gracefully, by sending a 'quit'
        # message
        response = self.send_message_to_service('quit\n')
        tend = time.time() + 10.0
        while self.service_process.poll() is None:
            if time.time() > tend:
                self.finish_bzr_subprocess(process=self.service_process,
                    send_signal=signal.SIGINT, retcode=3)
                self.fail('Failed to quit gracefully after 10.0 seconds')
            time.sleep(0.1)
        self.assertEqual('quit command requested... exiting\n', response)

    def test_fork_child_hello(self):
        response = self.send_message_to_service('fork 2\n')
        if response.startswith('FAILURE'):
            self.fail('Fork request failed')
        self.assertContainsRe(response, '/lp-service-child-')
        path = response.strip()
        stdin_path = os.path.join(path, 'stdin')
        stdout_path = os.path.join(path, 'stdout')
        stderr_path = os.path.join(path, 'stderr')
        child_stdout = open(stdout_path, 'rb')
        child_stderr = open(stderr_path, 'rb')
        child_stdin = open(stdin_path, 'wb')
        child_stdin.write('hello\n')
        child_stdin.close()
        stdout_content = child_stdout.read()
        stderr_content = child_stderr.read()
        self.assertEqual('ok\x012\n', stdout_content)
        self.assertEqual('', stderr_content)
