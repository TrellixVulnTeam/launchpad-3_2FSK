#!/usr/bin/python2.6 -S
#
# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=C0103,W0403

import _pythonpath

from lp.soyuz.scripts.ppa_add_missing_builds import PPAMissingBuilds
from canonical.config import config

if __name__ == "__main__":
    script = PPAMissingBuilds(
        "ppa-add-missing-builds", dbuser=config.builddmaster.dbuser)
    script.lock_and_run()
