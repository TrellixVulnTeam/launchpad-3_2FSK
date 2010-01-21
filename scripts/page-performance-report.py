#!/usr/bin/python2.5
#
# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Page performance report generated from zserver tracelogs."""

__metaclass__ = type

import _pythonpath

import sys

from lp.scripts.pageperformancereport import main


if __name__ == '__main__':
    sys.exit(main())
