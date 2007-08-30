# Copyright 2006 Canonical Ltd.  All rights reserved.

import datetime

import pytz

from canonical.launchpad.scripts.supermirror.jobmanager import LockError
from canonical.authserver.client.branchstatus import BranchStatusClient


UTC = pytz.timezone('UTC')


def mirror(logger, manager):
    """Mirror all current branches that need to be mirrored."""
    client = BranchStatusClient()

    try:
        manager.lock()
    except LockError, exception:
        logger.info('Could not acquire lock: %s', exception)
        return 0

    try:
        date_started = datetime.datetime.now(UTC)
        manager.addBranches(client)
        manager.run(logger)
        date_completed = datetime.datetime.now(UTC)
        manager.recordActivity(client, date_started, date_completed)
    finally:
        manager.unlock()
    return 0

