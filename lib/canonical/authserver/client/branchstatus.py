__metaclass__ = type

import xmlrpclib

from canonical.config import config

class BranchStatusError(Exception):
    pass

class BranchStatusClient:

    def __init__(self):
        self.client = xmlrpclib.ServerProxy(
            config.supermirror.authserver_url,
            allow_none=True)

    def getBranchPullQueue(self):
        return self.client.getBranchPullQueue()

    def startMirroring(self, branch_id):
        assert isinstance(branch_id, int)
        if not self.client.startMirroring(branch_id):
            raise BranchStatusError('startMirroring() failed for branch %d'
                                    % branch_id)

    def mirrorComplete(self, branch_id, last_revision_id):
        assert isinstance(branch_id, int)
        assert last_revision_id is None or isinstance(last_revision_id, str)
        if not self.client.mirrorComplete(branch_id, last_revision_id):
            raise BranchStatusError('mirrorComplete() failed for branch %d'
                                    % branch_id)

    def mirrorFailed(self, branch_id, reason):
        assert isinstance(branch_id, int)
        if not self.client.mirrorFailed(branch_id, reason):
            raise BranchStatusError('mirrorFailed() failed for branch %d'
                                    % branch_id)
