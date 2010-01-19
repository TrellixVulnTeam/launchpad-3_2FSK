#! /usr/bin/python2.5
# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import os.path
import sys
from subprocess import call


class GenerateTranslationTemplates:
    """Script to generate translation templates from a branch."""

    def __init__(self, branch_spec):
        """Prepare to generate templates for a branch.

        :param branch_spec: Either a branch URL or the path of a local
            branch.  URLs are recognized by the occurrence of ':'.  In
            the case of a URL, this will make up a path for the branch
            and check out the branch to there.
        """
        self.home = os.environ['HOME']
        self.branch_spec = branch_spec

    def _getBranch(self):
        if ':' in self.branch_spec:
            # This is a branch URL.  Check out the branch.
            self.branch_dir = os.path.join(self.home, 'source-tree')
            self._checkout(self.branch_spec)
        else:
            # This is a local filesystem path.  Use the branch in-place.
            self.branch_dir = self.branch_spec

        
    def _checkout(self, branch_url):
        """Check out a source branch to generate from.

        The branch is checked out to the location specified by
        `self.branch_dir`.
        """
        command = ['/usr/bin/bzr', 'checkout', branch_url, self.branch_dir]
        return call(command, cwd=self.home)

    def generate(self):
        """Do It.  Generate templates."""
        self._getBranch()
# XXX: Actual payload goes here.
        return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print "Usage: %s branch" % sys.argv[0]
        print "Where 'branch' is a branch URL or directory."
        sys.exit(1)
    sys.exit(GenerateTranslationTemplates(sys.argv[1]).generate())
