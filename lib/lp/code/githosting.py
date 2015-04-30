# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Communication with the Git hosting service."""

__metaclass__ = type
__all__ = [
    'GitHostingClient',
    ]

import json
from urlparse import urljoin

import requests

from lp.code.errors import (
    GitRepositoryCreationFault,
    GitRepositoryScanFault,
    )


class GitHostingClient:
    """A client for the internal API provided by the Git hosting system."""

    def __init__(self, endpoint):
        self.endpoint = endpoint

    def _makeSession(self):
        session = requests.Session()
        session.trust_env = False
        return session

    @property
    def timeout(self):
        # XXX cjwatson 2015-03-01: The hardcoded timeout at least means that
        # we don't lock tables indefinitely if the hosting service falls
        # over, but is there some more robust way to do this?
        return 5.0

    def create(self, path, clone_from=None):
        try:
            # XXX cjwatson 2015-03-01: Once we're on requests >= 2.4.2, we
            # should just use post(json=) and drop the explicit Content-Type
            # header.
            if clone_from:
                request = {"repo_path": path, "clone_from": clone_from}
            else:
                request = {"repo_path": path}
            response = self._makeSession().post(
                urljoin(self.endpoint, "/repo"),
                headers={"Content-Type": "application/json"},
                data=json.dumps(request),
                timeout=self.timeout)
        except Exception as e:
            raise GitRepositoryCreationFault(
                "Failed to create Git repository: %s" % unicode(e))
        if response.status_code != 200:
            raise GitRepositoryCreationFault(
                "Failed to create Git repository: %s" % response.text)

    def getRefs(self, path):
        try:
            response = self._makeSession().get(
                urljoin(self.endpoint, "/repo/%s/refs" % path),
                timeout=self.timeout)
        except Exception as e:
            raise GitRepositoryScanFault(
                "Failed to get refs from Git repository: %s" % unicode(e))
        if response.status_code != 200:
            raise GitRepositoryScanFault(
                "Failed to get refs from Git repository: %s" % response.text)
        try:
            return response.json()
        except ValueError as e:
            raise GitRepositoryScanFault(
                "Failed to decode ref-scan response: %s" % unicode(e))

    def getCommits(self, path, commit_oids, logger=None):
        commit_oids = list(commit_oids)
        try:
            # XXX cjwatson 2015-03-01: Once we're on requests >= 2.4.2, we
            # should just use post(json=) and drop the explicit Content-Type
            # header.
            if logger is not None:
                logger.info("Requesting commit details for %s" % commit_oids)
            response = self._makeSession().post(
                urljoin(self.endpoint, "/repo/%s/commits" % path),
                headers={"Content-Type": "application/json"},
                data=json.dumps({"commits": commit_oids}),
                timeout=self.timeout)
        except Exception as e:
            raise GitRepositoryScanFault(
                "Failed to get commit details from Git repository: %s" %
                unicode(e))
        if response.status_code != 200:
            raise GitRepositoryScanFault(
                "Failed to get commit details from Git repository: %s" %
                response.text)
        try:
            return response.json()
        except ValueError as e:
            raise GitRepositoryScanFault(
                "Failed to decode commit-scan response: %s" % unicode(e))

    def getMergeDiff(self, path, base, head, logger=None):
        """Get the merge preview diff between two commits.

        :return: A dict mapping 'commits' to a list of commits between
            'base' and 'head' (formatted as with `getCommits`), 'patch' to
            the text of the diff between 'base' and 'head', and 'conflicts'
            to a list of conflicted paths.
        """
        try:
            if logger is not None:
                logger.info(
                    "Requesting merge diff for %s from %s to %s" % (
                        path, base, head))
            response = self._makeSession().get(
                urljoin(
                    self.endpoint,
                    "/repo/%s/compare-merge/%s:%s" % (path, base, head)),
                timeout=self.timeout)
        except Exception as e:
            raise GitRepositoryScanFault(
                "Failed to get merge diff from Git repository: %s" %
                unicode(e))
        if response.status_code != 200:
            raise GitRepositoryScanFault(
                "Failed to get merge diff from Git repository: %s" %
                unicode(e))
        try:
            return response.json()
        except ValueError as e:
            raise GitRepositoryScanFault(
                "Failed to decode merge-diff response: %s" % unicode(e))
