# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Bazaar plugin to run the smart server on Launchpad.

Cribbed from bzrlib.builtins.cmd_serve from Bazaar 0.16.
"""

__metaclass__ = type

__all__ = ['cmd_launchpad_server',
           'cmd_launchpad_forking_service',
          ]


import errno
import os
import resource
import shlex
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time

from bzrlib.commands import Command, register_command
from bzrlib.option import Option
from bzrlib import (
    commands,
    errors,
    lockdir,
    osutils,
    trace,
    ui,
    )

from bzrlib.smart import medium, server
from bzrlib.transport import get_transport


class cmd_launchpad_server(Command):
    """Run a Bazaar server that maps Launchpad branch URLs to the internal
    file-system format.
    """

    aliases = ['lp-serve']

    takes_options = [
        Option('inet',
               help='serve on stdin/out for use from inetd or sshd'),
        Option('port',
               help='listen for connections on nominated port of the form '
                    '[hostname:]portnumber. Passing 0 as the port number will'
                    ' result in a dynamically allocated port. Default port is'
                    ' 4155.',
               type=str),
        Option('upload-directory',
               help='upload branches to this directory. Defaults to '
                    'config.codehosting.hosted_branches_root.',
               type=unicode),
        Option('mirror-directory',
               help='serve branches from this directory. Defaults to '
                    'config.codehosting.mirrored_branches_root.'),
        Option('codehosting-endpoint',
               help='the url of the internal XML-RPC server. Defaults to '
                    'config.codehosting.codehosting_endpoint.',
               type=unicode),
        ]

    takes_args = ['user_id']

    def get_smart_server(self, transport, port, inet):
        """Construct a smart server."""
        if inet:
            smart_server = medium.SmartServerPipeStreamMedium(
                sys.stdin, sys.stdout, transport)
        else:
            host = medium.BZR_DEFAULT_INTERFACE
            if port is None:
                port = medium.BZR_DEFAULT_PORT
            else:
                if ':' in port:
                    host, port = port.split(':')
                port = int(port)
            smart_server = server.SmartTCPServer(
                transport, host=host, port=port)
            print 'listening on port: ', smart_server.port
            sys.stdout.flush()
        return smart_server

    def run_server(self, smart_server):
        """Run the given smart server."""
        # for the duration of this server, no UI output is permitted.
        # note that this may cause problems with blackbox tests. This should
        # be changed with care though, as we dont want to use bandwidth
        # sending progress over stderr to smart server clients!
        old_factory = ui.ui_factory
        try:
            ui.ui_factory = ui.SilentUIFactory()
            smart_server.serve()
        finally:
            ui.ui_factory = old_factory

    def run(self, user_id, port=None, branch_directory=None,
            codehosting_endpoint_url=None, inet=False):
        from lp.codehosting.bzrutils import install_oops_handler
        from lp.codehosting.vfs import get_lp_server, hooks
        install_oops_handler(user_id)
        four_gig = int(4e9)
        resource.setrlimit(resource.RLIMIT_AS, (four_gig, four_gig))
        seen_new_branch = hooks.SetProcTitleHook()
        lp_server = get_lp_server(
            int(user_id), codehosting_endpoint_url, branch_directory,
            seen_new_branch.seen)
        lp_server.start_server()

        old_lockdir_timeout = lockdir._DEFAULT_TIMEOUT_SECONDS
        try:
            lp_transport = get_transport(lp_server.get_url())
            smart_server = self.get_smart_server(lp_transport, port, inet)
            lockdir._DEFAULT_TIMEOUT_SECONDS = 0
            self.run_server(smart_server)
        finally:
            lockdir._DEFAULT_TIMEOUT_SECONDS = old_lockdir_timeout
            lp_server.stop_server()


register_command(cmd_launchpad_server)


class LPForkingService(object):
    """A service that can be asked to start a new bzr subprocess via fork.

    The basic idea is that python startup is very expensive. For example, the
    original 'lp-serve' command could take 2.5s just to start up, before any
    actual actions could be performed.

    This class provides a service sitting on a socket, which can then be
    requested to fork and run a given bzr command.

    Clients connect to the socket and make a simple request, which then
    receives a response. The possible requests are:

        "hello\n":  Trigger a heartbeat to report that the program is still
                    running, and write status information to the log file.
        "quit\n":   Stop the service, but do so 'nicely', waiting for children
                    to exit, etc. Once this is received the service will stop
                    taking new requests on the port.
        "fork <command>\n": Request a new subprocess to be started.
            <command> is the bzr command to be run, such as "rocks" or
            "lp-serve --inet 12".
            The immediate response will be the path-on-disk to a directory full
            of named pipes (fifos) that will be the stdout/stderr/stdin of the
            new process.
            If a client holds the socket open, when the child process exits,
            the exit status (as given by 'wait()') will be written to the
            socket.

            Note that one of the key bits is that the client will not be
            started with exec*, we just call 'commands.run_bzr*()' directly.
            This way, any modules that are already loaded will not need to be
            loaded again. However, care must be taken with any global-state
            that should be reset.
    """

    # Design decisions. These are bits where we could have chosen a different
    # method/implementation and weren't sure what would be best. Documenting
    # the current decision, and the alternatives.
    #
    # [Decision #1]
    #   Serve on a named AF_UNIX socket.
    #       1) It doesn't make sense to serve to arbitrary hosts, we only want
    #          the local host to make requests. (Since the client needs to
    #          access the named fifos on the current filesystem.)
    #       2) You can set security parameters on a filesystem path (g+rw,
    #          a-rw).
    # [Decision #2]
    #   SIGCHLD
    #       We want to quickly detect that children have exited so that we can
    #       inform the client process quickly. At the moment, we register a
    #       SIGCHLD handler that doesn't do anything. However, it means that
    #       when we get the signal, if we are currently blocked in something
    #       like '.accept()', we will jump out temporarily. At that point the
    #       main loop will check if any children have exited. We could have
    #       done this work as part of the signal handler, but that felt 'racy'
    #       doing any serious work in a signal handler.
    #       If we just used socket.timeout as the indicator to go poll for
    #       children exiting, it slows the disconnect by as much as the full
    #       timeout. (So a timeout of 1.0s will cause the process to hang by
    #       that long until it determines that a child has exited, and can
    #       close the connection.)
    #       The current flow means that we'll notice exited children whenever
    #       we finish the current work.
    # [Decision #3]
    #   Child vs Parent actions.
    #       There are several actions that are done when we get a new request.
    #       We have to create the fifos on disk, fork a new child, connect the
    #       child to those handles, and inform the client of the new path (not
    #       necessarily in that order.) It makes sense to wait to send the path
    #       message until after the fifos have been created. That way the
    #       client can just try to open them immediately, and the
    #       client-and-child will be synchronized by the open() calls.
    #       However, should the client be the one doing the mkfifo, should the
    #       server? Who should be sending the message? Should we fork after the
    #       mkfifo or before.
    #       The current thoughts:
    #           1) Try to do work in the child when possible. This should allow
    #              for 'scaling' because the server is single-threaded.
    #           2) We create the directory itself in the server, because that
    #              allows the server to monitor whether the client failed to
    #              clean up after itself or not.
    #           3) Otherwise we create the fifos in the client, and then send
    #              the message back.
    # [Decision #4]
    #   Exit information
    #       Inform the client that the child has exited on the socket they used
    #       to request the fork.
    #       1) Arguably they could see that stdout and stderr have been closed,
    #          and thus stop reading. In testing, I wrote a client which uses
    #          select.poll() over stdin/stdout/stderr and used that to ferry
    #          the content to the appropriate local handle. However for the
    #          FIFOs, when the remote end closed, I wouldn't see any
    #          corresponding information on the local end. There obviously
    #          wasn't any data to be read, so they wouldn't show up as
    #          'readable' (for me to try to read, and get 0 bytes, indicating
    #          it was closed). I also wasn't seeing POLLHUP, which seemed to be
    #          the correct indicator.  As such, we decided to inform the client
    #          on the socket that they originally made the fork request, rather
    #          than just closing the socket immediately.
    #       2) We could have had the forking server close the socket, and only
    #          the child hold the socket open. When the child exits, then the
    #          OS naturally closes the socket.
    #          If we want the returncode, then we should put that as bytes on
    #          the socket before we exit. Having the child do the work means
    #          that in error conditions, it could easily die before being able to
    #          write anything (think SEGFAULT, etc). The forking server is
    #          already 'wait'() ing on its children. So that we don't get
    #          zombies, and with wait3() we can get the rusage (user time,
    #          memory consumption, etc.)
    #          As such, it seems reasonable that the server can then also
    #          report back when a child is seen as exiting.
    # [Decision #5]
    #   cleanup once connected
    #       The child process blocks during 'open()' waiting for the client to
    #       connect to its fifos. Once the client has connected, the child then
    #       deletes the temporary directory and the fifos from disk. This means
    #       that there isn't much left for diagnosis, but it also means that
    #       the client won't leave garbage around if it crashes, etc.
    #       Note that the forking service itself still monitors the paths
    #       created, and will delete garbage if it sees that a child failed to
    #       do so.
    # [Decision #6]
    #   os._exit(retcode) in the child
    #       Calling sys.exit(retcode) raises an exception, which then bubbles
    #       up the stack and runs exit functions (and finally statements). When
    #       I tried using it originally, I would see the current child bubble
    #       all the way up the stack (through the server code that it fork()
    #       through), and then get to main() returning code 0. The process
    #       would still exit nonzero. My guess is that something in the atexit
    #       functions was failing, but that it was happening after logging, etc
    #       had been shut down.
    #       Any global state from the child process should be flushed before
    #       run_bzr_* has exited (which we *do* wait for), and any other global
    #       state is probably a remnant from the service process. Which will be
    #       cleaned up by the service itself, rather than the child.
    #       There is some concern that log files may not get flushed, so we
    #       currently call sys.exitfunc() first. The main problem is that I
    #       don't know any way to *remove* a function registered via 'atexit()'
    #       so if the forking service has some state, we my try to clean it up
    #       incorrectly.
    #       Note that the bzr script itself uses sys.exitfunc(); os._exit() in
    #       the 'bzr' main script, as the teardown time of all the python state
    #       was quite noticeable in real-world runtime. As such, bzrlib should
    #       be pretty safe, or it would have been failing for people already.
    # [Decision #7]
    #   prefork vs max children vs ?
    #       For simplicity it seemed easiest to just fork when requested. Over
    #       time, I realized it would be easy to allow running an arbitrary
    #       command (no harder than just running one command), so it seemed
    #       reasonable to switch over. If we go the prefork route, then we'll
    #       need a way to tell the pre-forked children what command to run.
    #       This could be as easy as just adding one more fifo that they wait
    #       on in the same directory.
    #       For now, I've chosen not to limit the number of forked children. I
    #       don't know what a reasonable value is, and probably there are
    #       already limitations at play. (If Conch limits connections, then it
    #       will already be doing all the work, etc.)
    # [Decision #8]
    #   nicer errors on the request socket
    #       This service is meant to be run only on the local system. As such,
    #       we don't try to be extra defensive about leaking information to
    #       the one connecting to the socket. (We should still watch out what
    #       we send across the per-child fifos, since those are connected to
    #       remote clients.) Instead we try to be helpful, and tell them as
    #       much as we know about what went wrong.

    DEFAULT_PATH = '/var/run/launchpad_forking_service.sock'
    DEFAULT_PERMISSIONS = 00660 # Permissions on the master socket (rw-rw----)
    WAIT_FOR_CHILDREN_TIMEOUT = 5*60 # Wait no more than 5 min for children
    SOCKET_TIMEOUT = 1.0
    SLEEP_FOR_CHILDREN_TIMEOUT = 1.0
    WAIT_FOR_REQUEST_TIMEOUT = 1.0 # No request should take longer than this to
                                   # be read

    _fork_function = os.fork

    def __init__(self, path=DEFAULT_PATH, perms=DEFAULT_PERMISSIONS):
        self.master_socket_path = path
        self._perms = perms
        self._start_time = time.time()
        self._should_terminate = threading.Event()
        # We address these locally, in case of shutdown socket may be gc'd
        # before we are
        self._socket_timeout = socket.timeout
        self._socket_error = socket.error
        self._socket_timeout = socket.timeout
        self._socket_error = socket.error
        # Map from pid => information
        self._child_processes = {}
        self._children_spawned = 0

    def _create_master_socket(self):
        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(self.master_socket_path)
        if self._perms is not None:
            os.chmod(self.master_socket_path, self._perms)
        self._server_socket.setsockopt(socket.SOL_SOCKET,
            socket.SO_REUSEADDR, 1)
        self._sockname = self._server_socket.getsockname()
        # self.host = self._sockname[0]
        self.port = self._sockname[1]
        self._server_socket.listen(5)
        self._server_socket.settimeout(self.SOCKET_TIMEOUT)
        trace.mutter('set socket timeout to: %s' % (self.SOCKET_TIMEOUT,))

    def _cleanup_master_socket(self):
        self._server_socket.close()
        try:
            os.remove(self.master_socket_path)
        except (OSError, IOError), e:
            # If we don't delete it, then we get 'address already in
            # use' failures
            trace.mutter('failed to cleanup: %s'
                         % (self.master_socket_path,))

    def _handle_sigchld(self, signum, frm):
        # We don't actually do anything here, we just want an interrupt (EINTR)
        # on socket.accept() when SIGCHLD occurs.
        pass

    def _handle_sigterm(self, signum, frm):
        # Unregister this as the default handler, 2 SIGTERMs will exit us.
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        # SIGTERM should also generate EINTR on our wait loop, so this should
        # be enough
        self._should_terminate.set()

    def _register_signals(self):
        """Register a SIGCHILD and SIGTERM handler.

        If we have a trigger for SIGCHILD then we can quickly respond to
        clients when their process exits. The main risk is getting more EAGAIN
        errors elsewhere.

        SIGTERM allows us to cleanup nicely before we exit.
        """
        signal.signal(signal.SIGCHLD, self._handle_sigchld)
        signal.signal(signal.SIGTERM, self._handle_sigterm)

    def _unregister_signals(self):
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    def _create_child_file_descriptors(self, base_path):
        stdin_path = os.path.join(base_path, 'stdin')
        stdout_path = os.path.join(base_path, 'stdout')
        stderr_path = os.path.join(base_path, 'stderr')
        os.mkfifo(stdin_path)
        os.mkfifo(stdout_path)
        os.mkfifo(stderr_path)

    def _bind_child_file_descriptors(self, base_path):
        import logging
        from bzrlib import ui
        stdin_path = os.path.join(base_path, 'stdin')
        stdout_path = os.path.join(base_path, 'stdout')
        stderr_path = os.path.join(base_path, 'stderr')
        # Opening for writing blocks (or fails), so do those last
        # TODO: Consider buffering, though that might interfere with reading
        #       and writing the smart protocol
        stdin_fid = os.open(stdin_path, os.O_RDONLY)
        stdout_fid = os.open(stdout_path, os.O_WRONLY)
        stderr_fid = os.open(stderr_path, os.O_WRONLY)
        # Note: by this point bzrlib has opened stderr for logging
        #       (as part of starting the service process in the first place). As
        #       such, it has a stream handler that writes to stderr. logging
        #       tries to flush and close that, but the file is already closed.
        #       This just supresses that exception
        logging.raiseExceptions = False
        sys.stdin.close()
        sys.stdout.close()
        sys.stderr.close()
        os.dup2(stdin_fid, 0)
        os.dup2(stdout_fid, 1)
        os.dup2(stderr_fid, 2)
        sys.stdin = os.fdopen(stdin_fid, 'rb')
        sys.stdout = os.fdopen(stdout_fid, 'wb')
        sys.stderr = os.fdopen(stderr_fid, 'wb')
        ui.ui_factory.stdin = sys.stdin
        ui.ui_factory.stdout = sys.stdout
        ui.ui_factory.stderr = sys.stderr
        # Now that we've opened the handles, delete everything so that we don't
        # leave garbage around. Because the open() is done in blocking mode, we
        # know that someone has already connected to them, and we don't want
        # anyone else getting confused and connecting.
        # See [Decision #5]
        os.remove(stderr_path)
        os.remove(stdout_path)
        os.remove(stdin_path)
        os.rmdir(base_path)

    def _close_child_file_descriptons(self):
        sys.stdin.close()
        sys.stderr.close()
        sys.stdout.close()

    def become_child(self, command_argv, path):
        """We are in the spawned child code, do our magic voodoo."""
        # Stop tracking new signals
        self._unregister_signals()
        # Reset the start time
        trace._bzr_log_start_time = time.time()
        trace.mutter('%d starting %r'
                     % (os.getpid(), command_argv,))
        self.host = None
        self.port = None
        self._sockname = None
        self._bind_child_file_descriptors(path)
        self._run_child_command(command_argv)

    def _run_child_command(self, command_argv):
        # This is the point where we would actually want to do something with
        # our life
        # TODO: We may want to consider special-casing the 'lp-serve' command.
        #       As that is the primary use-case for this service, it might be
        #       interesting to have an already-instantiated instance, where we
        #       can just pop on an extra argument and be ready to go. However,
        #       that would probably only really be measurable if we prefork. As
        #       it looks like ~200ms is 'fork()' time, but only 50ms is
        #       run-the-command time.
        retcode = commands.run_bzr_catch_errors(command_argv)
        self._close_child_file_descriptons()
        trace.mutter('%d finished %r'
                     % (os.getpid(), command_argv,))
        # We force os._exit() here, because we don't want to unwind the stack,
        # which has complex results. (We can get it to unwind back to the
        # cmd_launchpad_forking_service code, and even back to main() reporting
        # thereturn code, but after that, suddenly the return code changes from
        # a '0' to a '1', with no logging of info.
        # TODO: Should we call sys.exitfunc() here? it allows atexit functions
        #       to fire, however, some of those may be still around from the
        #       parent process, which we don't really want.
        sys.exitfunc()
        # See [Decision #6]
        os._exit(retcode)

    @staticmethod
    def command_to_argv(command_str):
        """Convert a 'foo bar' style command to [u'foo', u'bar']"""
        # command_str must be a utf-8 string
        return [s.decode('utf-8') for s in shlex.split(command_str)]

    @staticmethod
    def parse_env(env_str):
        """Convert the environment information into a dict.

        :param env_str: A string full of environment variable declarations.
            Each key is simple ascii "key: value\n"
            The string must end with "end\n".
        :return: A dict of environment variables
        """
        env = {}
        if not env_str.endswith('end\n'):
            raise ValueError('Invalid env-str: %r' % (env_str,))
        env_str = env_str[:-5]
        if not env_str:
            return env
        env_entries = env_str.split('\n')
        for entry in env_entries:
            key, value = entry.split(': ', 1)
            env[key] = value
        return env

    def fork_one_request(self, conn, client_addr, command_argv, env):
        """Fork myself and serve a request."""
        temp_name = tempfile.mkdtemp(prefix='lp-forking-service-child-')
        # Now that we've set everything up, send the response to the client we
        # create them first, so the client can start trying to connect to them,
        # while we fork and have the child do the same.
        self._children_spawned += 1
        pid = self._fork_function()
        if pid == 0:
            pid = os.getpid()
            trace.mutter('%d spawned' % (pid,))
            self._server_socket.close()
            for env_var, value in env.iteritems():
                osutils.set_or_unset_env(env_var, value)
            # See [Decision #3]
            self._create_child_file_descriptors(temp_name)
            conn.sendall('ok\n%d\n%s\n' % (pid, temp_name))
            conn.close()
            self.become_child(command_argv, temp_name)
            trace.warning('become_child returned!!!')
            sys.exit(1)
        else:
            self._child_processes[pid] = (temp_name, conn)
            self.log(client_addr, 'Spawned process %s for %r: %s'
                            % (pid, command_argv, temp_name))

    def main_loop(self):
        self._should_terminate.clear()
        self._register_signals()
        self._create_master_socket()
        trace.note('Listening on socket: %s' % (self.master_socket_path,))
        try:
            try:
                self._do_loop()
            finally:
                # Stop talking to others, we are shutting down
                self._cleanup_master_socket()
        except KeyboardInterrupt:
            # SIGINT received, try to shutdown cleanly
            pass
        trace.note('Shutting down. Waiting up to %.0fs for %d child processes'
                   % (self.WAIT_FOR_CHILDREN_TIMEOUT,
                      len(self._child_processes),))
        self._shutdown_children()
        trace.note('Exiting')

    def _do_loop(self):
        while not self._should_terminate.isSet():
            try:
                conn, client_addr = self._server_socket.accept()
            except self._socket_timeout:
                pass # run shutdown and children checks
            except self._socket_error, e:
                if e.args[0] == errno.EINTR:
                    pass # run shutdown and children checks
                elif e.args[0] != errno.EBADF:
                    # We can get EBADF here while we are shutting down
                    # So we just ignore it for now
                    pass
                else:
                    # Log any other failure mode
                    trace.warning("listening socket error: %s", e)
            else:
                self.log(client_addr, 'connected')
                # TODO: We should probably trap exceptions coming out of this
                #       and log them, so that we don't kill the service because
                #       of an unhandled error
                # Note: settimeout is used so that a malformed request doesn't
                #       cause us to hang forever. Note that the particular
                #       implementation means that a malicious client could
                #       probably send us one byte every Xms, and we would just
                #       keep trying to read it. However, as a local service, we
                #       aren't worrying about it.
                conn.settimeout(self.WAIT_FOR_REQUEST_TIMEOUT)
                try:
                    self.serve_one_connection(conn, client_addr)
                except self._socket_timeout, e:
                    trace.log_exception_quietly()
                    self.log(client_addr, 'request timeout failure: %s' % (e,))
                    conn.sendall('FAILURE\nrequest timed out\n')
                    conn.close()
            self._poll_children()

    def log(self, client_addr, message):
        """Log a message to the trace log.

        Include the information about what connection is being served.
        """
        if client_addr is not None:
            # Note, we don't use conn.getpeername() because if a client
            # disconnects before we get here, that raises an exception
            conn_info = '[%s] ' % (client_addr,)
        else:
            conn_info = ''
        trace.mutter('%s%s' % (conn_info, message))

    def log_information(self):
        """Log the status information.

        This includes stuff like number of children, and ... ?
        """
        self._poll_children()
        self.log(None, 'Running for %.3fs' % (time.time() - self._start_time))
        self.log(None, '%d children currently running (spawned %d total)'
                       % (len(self._child_processes), self._children_spawned))
        # Read the current information about memory consumption, etc.
        self.log(None, 'Self: %s'
                       % (resource.getrusage(resource.RUSAGE_SELF),))
        # This seems to be the sum of all rusage for all children that have
        # been collected (not for currently running children, or ones we
        # haven't "wait"ed on.) We may want to read /proc/PID/status, since
        # 'live' information is probably more useful.
        self.log(None, 'Finished children: %s'
                       % (resource.getrusage(resource.RUSAGE_CHILDREN),))

    def _poll_children(self):
        """See if children are still running, etc.

        One interesting hook here would be to track memory consumption, etc.
        """
        while self._child_processes:
            try:
                c_id, exit_code, rusage = os.wait3(os.WNOHANG)
            except OSError, e:
                if e.errno == errno.ECHILD:
                    # TODO: We handle this right now because the test suite
                    #       fakes a child, since we wanted to test some code
                    #       without actually forking anything
                    trace.mutter('_poll_children() called, and'
                        ' self._child_processes indicates there are'
                        ' children, but os.wait3() says there are not.'
                        ' current_children: %s' % (self._child_processes,))
                    return
            if c_id == 0:
                # No more children stopped right now
                return
            c_path, sock = self._child_processes.pop(c_id)
            trace.mutter('%s exited %s and usage: %s'
                         % (c_id, exit_code, rusage))
            # See [Decision #4]
            try:
                sock.sendall('exited\n%s\n' % (exit_code,))
            except (self._socket_timeout, self._socket_error), e:
                # The client disconnected before we wanted them to,
                # no big deal
                trace.mutter('%s\'s socket already closed: %s' % (c_id, e))
            else:
                sock.close()
            if os.path.exists(c_path):
                # The child failed to cleanup after itself, do the work here
                trace.warning('Had to clean up after child %d: %s\n'
                              % (c_id, c_path))
                shutil.rmtree(c_path, ignore_errors=True)

    def _wait_for_children(self, secs):
        start = time.time()
        end = start + secs
        while self._child_processes:
            self._poll_children()
            if secs > 0 and time.time() > end:
                break
            time.sleep(self.SLEEP_FOR_CHILDREN_TIMEOUT)

    def _shutdown_children(self):
        self._wait_for_children(self.WAIT_FOR_CHILDREN_TIMEOUT)
        if self._child_processes:
            trace.warning('Failed to stop children: %s'
                % ', '.join(map(str, self._child_processes)))
            for c_id in self._child_processes:
                trace.warning('sending SIGINT to %d' % (c_id,))
                os.kill(c_id, signal.SIGINT)
            # We sent the SIGINT signal, see if they exited
            self._wait_for_children(self.SLEEP_FOR_CHILDREN_TIMEOUT)
        if self._child_processes:
            # No? Then maybe something more powerful
            for c_id in self._child_processes:
                trace.warning('sending SIGKILL to %d' % (c_id,))
                os.kill(c_id, signal.SIGKILL)
            # We sent the SIGKILL signal, see if they exited
            self._wait_for_children(self.SLEEP_FOR_CHILDREN_TIMEOUT)
        if self._child_processes:
            for c_id, (c_path, sock) in self._child_processes.iteritems():
                # TODO: We should probably put something into this message?
                #       However, the likelyhood is very small that this isn't
                #       already closed because of SIGKILL + _wait_for_children
                #       And I don't really know what to say...
                sock.close()
                if os.path.exists(c_path):
                    trace.warning('Cleaning up after immortal child %d: %s\n'
                                  % (c_id, c_path))
                    shutil.rmtree(c_path)

    def _parse_fork_request(self, conn, client_addr, request):
        if request.startswith('fork-env '):
            while not request.endswith('end\n'):
                request += osutils.read_bytes_from_socket(conn)
                request = request.replace('\r\n', '\n')
            command, env = request[9:].split('\n', 1)
        else:
            command = request[5:].strip()
            env = 'end\n' # No env set
        try:
            command_argv = self.command_to_argv(command)
            env = self.parse_env(env)
        except Exception, e:
            # TODO: Log the traceback?
            self.log(client_addr, 'command or env parsing failed: %r'
                                  % (str(e),))
            conn.sendall('FAILURE\ncommand or env parsing failed: %r'
                         % (str(e),))
        else:
            return command_argv, env
        return None, None

    def serve_one_connection(self, conn, client_addr):
        request = ''
        while '\n' not in request:
            request += osutils.read_bytes_from_socket(conn)
        # telnet likes to use '\r\n' rather than '\n', and it is nice to have
        # an easy way to debug.
        request = request.replace('\r\n', '\n')
        self.log(client_addr, 'request: %r' % (request,))
        if request == 'hello\n':
            conn.sendall('ok\nyep, still alive\n')
            self.log_information()
        elif request == 'quit\n':
            self._should_terminate.set()
            conn.sendall('ok\nquit command requested... exiting\n')
        elif request.startswith('fork ') or request.startswith('fork-env '):
            command_argv, env = self._parse_fork_request(conn, client_addr,
                                                         request)
            if command_argv is not None:
                # See [Decision #7]
                # TODO: Do we want to limit the number of children? And/or
                #       prefork additional instances? (the design will need to
                #       change if we prefork and run arbitrary commands.)
                self.fork_one_request(conn, client_addr, command_argv, env)
                # We don't close the conn like other code paths, since we use
                # it again later.
                return
        else:
            self.log(client_addr, 'FAILURE: unknown request: %r' % (request,))
            # See [Decision #8]
            conn.sendall('FAILURE\nunknown request: %r\n' % (request,))
        conn.close()


class cmd_launchpad_forking_service(Command):
    """Launch a long-running process, where you can ask for new processes.

    The process will block on a given --port waiting for requests to be made.
    When a request is made, it will fork itself and redirect stdout/in/err to
    fifos on the filesystem, and start running the requested command. The
    caller will be informed where those file handles can be found. Thus it only
    makes sense that the process connecting to the port must be on the same
    system.
    """

    aliases = ['lp-service']

    takes_options = [Option('path',
                        help='Listen for connections at PATH',
                        type=str),
                     Option('perms',
                        help='Set the mode bits for the socket, interpreted'
                             ' as an octal integer (same as chmod)'),
                     Option('preload',
                        help="Do/don't preload libraries before startup."),
                     Option('children-timeout', type=int,
                        help="Only wait XX seconds for children to exit"),
                    ]

    def _preload_libraries(self):
        global libraries_to_preload
        for pyname in libraries_to_preload:
            try:
                __import__(pyname)
            except ImportError, e:
                trace.mutter('failed to preload %s: %s' % (pyname, e))

    def run(self, path=None, perms=None, preload=True,
            children_timeout=LPForkingService.WAIT_FOR_CHILDREN_TIMEOUT):
        if path is None:
            path = LPForkingService.DEFAULT_PATH
        if perms is None:
            perms = LPForkingService.DEFAULT_PERMISSIONS
        if preload:
            # We 'note' this because it often takes a fair amount of time.
            trace.note('Preloading %d modules' % (len(libraries_to_preload),))
            self._preload_libraries()
        service = LPForkingService(path, perms)
        service.WAIT_FOR_CHILDREN_TIMEOUT = children_timeout
        service.main_loop()

register_command(cmd_launchpad_forking_service)


class cmd_launchpad_replay(Command):
    """Write input from stdin back to stdout or stderr.

    This is a hidden command, primarily available for testing
    cmd_launchpad_forking_service.
    """

    hidden = True

    def run(self):
        # Just read line-by-line from stdin, and write out to stdout or stderr
        # depending on the prefix
        for line in sys.stdin:
            channel, contents = line.split(' ', 1)
            channel = int(channel)
            if channel == 1:
                sys.stdout.write(contents)
                sys.stdout.flush()
            elif channel == 2:
                sys.stderr.write(contents)
                sys.stderr.flush()
            else:
                raise RuntimeError('Invalid channel request.')
        return 0

register_command(cmd_launchpad_replay)

# This list was generated by run lsprofing a spawned child, and looking for
# <module ...> times, which indicate an import occured. Other possibilities are
# to just run "bzr lp-serve --profile-imports" manually, and observe what was
# expensive to import. It doesn't seem very easy to get this right
# automatically.
libraries_to_preload = [
    'bzrlib.errors',
    'bzrlib.repofmt.groupcompress_repo',
    'bzrlib.repository',
    'bzrlib.smart',
    'bzrlib.smart.protocol',
    'bzrlib.smart.request',
    'bzrlib.smart.server',
    'bzrlib.smart.vfs',
    'bzrlib.transport.local',
    'bzrlib.transport.readonly',
    'lp.codehosting.bzrutils',
    'lp.codehosting.vfs',
    'lp.codehosting.vfs.branchfs',
    'lp.codehosting.vfs.branchfsclient',
    'lp.codehosting.vfs.hooks',
    'lp.codehosting.vfs.transport',
    ]



def load_tests(standard_tests, module, loader):
    standard_tests.addTests(loader.loadTestsFromModuleNames(
        [__name__ + '.' + x for x in [
            'test_lpserve',
        ]]))
    return standard_tests
