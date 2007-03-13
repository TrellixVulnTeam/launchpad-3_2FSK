#!/usr/bin/python
# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Script to probe distribution mirrors and check how up-to-date they are."""

import _pythonpath

from StringIO import StringIO

from twisted.internet import reactor

from zope.component import getUtility

from canonical.config import config
from canonical.lp.dbschema import MirrorContent
from canonical.launchpad.scripts.base import (
    LaunchpadScript, LaunchpadScriptFailure)
from canonical.launchpad.interfaces import (
    IDistributionMirrorSet, ILibraryFileAliasSet)
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.scripts.distributionmirror_prober import (
    get_expected_cdimage_paths, probe_archive_mirror, probe_release_mirror)


class DistroMirrorProber(LaunchpadScript):
    usage = ('%prog --content-type=(archive|release) [--force] '
             '[--no-owner-notification]')

    def _sanity_check_mirror(self, mirror):
        """Check that the given mirror is official and has an http_base_url."""
        assert mirror.isOfficial(), 'Non-official mirrors should not be probed'
        if mirror.base_url is None:
            self.logger.warning(
                "Mirror '%s' of distribution '%s' doesn't have a base URL; "
                "we can't probe it." % (mirror.name, mirror.distribution.name))
            return False
        return True

    def _create_probe_record(self, mirror, logfile):
        """Create a probe record for the given mirror with the given logfile."""
        logfile.seek(0)
        filename = '%s-probe-logfile.txt' % mirror.name
        log_file = getUtility(ILibraryFileAliasSet).create(
            name=filename, size=len(logfile.getvalue()),
            file=logfile, contentType='text/plain')
        mirror.newProbeRecord(log_file)

    def add_my_options(self):
        self.parser.add_option('--content-type',
            dest='content_type', default=None, action='store',
            help='Probe only mirrors of the given type')
        self.parser.add_option('--force',
            dest='force', default=False, action='store_true',
            help='Force the probing of mirrors that have been probed recently')
        self.parser.add_option('--no-owner-notification',
            dest='no_owner_notification', default=False, action='store_true',
            help='Do not send failure notification to mirror owners.')
        self.parser.add_option('--no-remote-hosts',
            dest='no_remote_hosts', default=False, action='store_true',
            help='Do not try to connect to any host other than localhost.')

    def main(self):
        if self.options.content_type == 'archive':
            probe_function = probe_archive_mirror
            content_type = MirrorContent.ARCHIVE
        elif self.options.content_type == 'release':
            probe_function = probe_release_mirror
            content_type = MirrorContent.RELEASE
        else:
            raise LaunchpadScriptFailure(
                'Wrong value for argument --content-type: %s'
                % self.options.content_type)

        # Using a script argument to control a config variable is not a great
        # idea, but to me this seems better than passing the no_remote_hosts
        # value through a lot of method/function calls, until it reaches the
        # probe() method.
        if self.options.no_remote_hosts:
            config.distributionmirrorprober.localhost_only = True

        self.logger.info('Probing %s Mirrors' % content_type.title)

        mirror_set = getUtility(IDistributionMirrorSet)

        self.txn.begin()

        results = mirror_set.getMirrorsToProbe(
            content_type, ignore_last_probe=self.options.force)
        mirror_ids = [mirror.id for mirror in results]
        unchecked_keys = []
        logfiles = {}
        probed_mirrors = []

        for mirror_id in mirror_ids:
            mirror = mirror_set[mirror_id]
            if not self._sanity_check_mirror(mirror):
                continue

            # XXX: Some people registered mirrors on distros other than Ubuntu
            # back in the old times, so now we need to do this small hack here.
            # Guilherme Salgado, 2006-05-26
            if not mirror.distribution.full_functionality:
                self.logger.info(
                    "Mirror '%s' of distribution '%s' can't be probed --we only "
                    "probe Ubuntu mirrors." 
                    % (mirror.name, mirror.distribution.name))
                continue

            probed_mirrors.append(mirror)
            logfile = StringIO()
            logfiles[mirror_id] = logfile
            probe_function(mirror, logfile, unchecked_keys, self.logger)

        if probed_mirrors:
            reactor.run()
            self.logger.info('Probed %d mirrors.' % len(probed_mirrors))
        else:
            self.logger.info('No mirrors to probe.')
        self.txn.commit()

        # Now that we finished probing all mirrors, we check if any of these
        # mirrors appear to have no content mirrored, and, if so, mark them as
        # disabled and notify their owners.
        self.txn.begin()
        expected_iso_images_count = len(get_expected_cdimage_paths())
        notify_owner = not self.options.no_owner_notification
        for mirror in probed_mirrors:
            self._create_probe_record(mirror, logfiles[mirror.id])
            if mirror.shouldDisable(expected_iso_images_count):
                if mirror.enabled:
                    mirror.disable(notify_owner)
                    self.logger.info('Disabled %s' % canonical_url(mirror))
            else:
                # Ensure the mirror is enabled, so that it shows up on public
                # mirror listings.
                if not mirror.enabled:
                    mirror.enabled = True
                    self.logger.info('Enabled %s' % canonical_url(mirror))

        self.txn.commit()
        self.logger.info('Done.')


if __name__ == '__main__':
    script = DistroMirrorProber('distributionmirror-prober',
                                dbuser=config.distributionmirrorprober.dbuser)
    script.lock_and_run()

