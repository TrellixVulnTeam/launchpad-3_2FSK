#! /usr/bin/python2.5
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=C0103,W0403

"""Perform auto-approvals and auto-blocks on translation import queue"""

import _pythonpath

from lp.translations.scripts.import_queue_gardener import ImportQueueGardener


if __name__ == '__main__':
    script = ImportQueueGardener(
        'translations-import-queue-gardener',
        dbuser='translations_import_queue_gardener')
    script.lock_and_run()
