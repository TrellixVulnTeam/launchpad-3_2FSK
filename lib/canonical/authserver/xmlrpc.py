# Copyright 2004 Canonical Ltd.  All rights reserved.

from twisted.web import xmlrpc

class UserDetailsResource(xmlrpc.XMLRPC):

    def __init__(self, storage, debug=False):
        xmlrpc.XMLRPC.__init__(self)
        self.storage = storage
        self.debug = debug

    def xmlrpc_getUser(self, loginID):
        """Get a user
        
        :returns: user dict if loginID exists, otherwise empty dict
        """
        if self.debug:
            print 'getUser(%r)' % (loginID,)
        return self.storage.getUser(loginID)

    def xmlrpc_authUser(self, loginID, sshaDigestedPassword):
        """Authenticate a user
        
        :returns: user dict if authenticated, otherwise empty dict
        """
        if self.debug:
            print 'authUser(%r, %r)' % (loginID, sshaDigestedPassword)
        return self.storage.authUser(loginID,
                                     sshaDigestedPassword.decode('base64'))

    def xmlrpc_changePassword(self, loginID, sshaDigestedPassword,
                              newSshaDigestedPassword):
        if self.debug:
            print ("changePassword(%r, %r, %r)"
                   % (loginID, sshaDigestedPassword, newSshaDigestedPassword))
        return self.storage.changePassword(
            loginID, sshaDigestedPassword.decode('base64'),
            newSshaDigestedPassword.decode('base64')
        )

    def xmlrpc_getSSHKeys(self, loginID):
        """Retrieve SSH public keys for a given user
        
        :param loginID: a login ID.
        :returns: list of 2-tuples of (key type, key text).  This list will be
            empty if the user has no keys or does not exist.
        
        :returns: user dict if loginID exists, otherwise empty dict
        """
        if self.debug:
            print 'getSSHKeys(%r)' % (loginID,)
        return self.storage.getSSHKeys(loginID)


class UserDetailsResourceV2(xmlrpc.XMLRPC):
    """A new (and simpler) version of the user details XML-RPC API."""

    def __init__(self, storage, debug=False):
        self.storage = storage
        self.debug = debug

    def xmlrpc_getUser(self, loginID):
        """Get a user
        
        :returns: user dict if loginID exists, otherwise empty dict
        """
        if self.debug:
            print 'getUser(%r)' % (loginID,)
        return self.storage.getUser(loginID)

    def xmlrpc_authUser(self, loginID, password):
        """Authenticate a user
        
        :returns: user dict if authenticated, otherwise empty dict
        """
        if self.debug:
            print 'authUser(%r, %r)' % (loginID, password)
        return self.storage.authUser(loginID, password)
        
    def xmlrpc_changePassword(self, loginID, oldPassword, newPassword):
        """Change a password

        :param loginID: A login ID, same as for getUser.
        :param sshaDigestedPassword: The current password.
        :param newSshaDigestedPassword: The password to change to.
        """
        if self.debug:
            print ("changePassword(%r, %r, %r)"
                   % (loginID, oldPassword, newPassword))
        return self.storage.changePassword(loginID, oldPassword, newPassword)
        
    def xmlrpc_getSSHKeys(self, loginID):
        """Retrieve SSH public keys for a given user
        
        :param loginID: a login ID.
        :returns: list of 2-tuples of (key type, key text).  This list will be
            empty if the user has no keys or does not exist.
        """
        if self.debug:
            print 'getSSHKeys(%r)' % (loginID,)
        return self.storage.getSSHKeys(loginID)

    def xmlrpc_getBranchesForUser(self, personID):
        # XXX: docstring
        if self.debug:
            print 'getBranchesForUser(%r)' % (personID,)
        return self.storage.getBranchesForUser(personID)

    def xmlrpc_fetchProductID(self, productName):
        # XXX: docstring
        if self.debug:
            print 'fetchProductID(%r)' % (productName,)
        return self.storage.fetchProductID(productName)

    def xmlrpc_createBranch(self, personID, productID, branchName):
        # XXX: docstring
        if self.debug:
            print 'createBranch(%r, %r, %r)' % (personID, productID, branchName)
        return self.storage.createBranch(personID, productID, branchName)


class BranchDetailsResource(xmlrpc.XMLRPC):

    def __init__(self, storage, debug=False):
        xmlrpc.XMLRPC.__init__(self)
        self.storage = storage
        self.debug = debug

    def xmlrpc_getBranchPullQueue(self):
        if self.debug:
            print 'getBranchPullQueue()'
        d = self.storage.getBranchPullQueue()
        if self.debug:
            def printresult(result):
                for (branch_id, pull_url) in result:
                    print branch_id, pull_url
                return result
            d.addCallback(printresult)
        return d

    def xmlrpc_startMirroring(self, branchID):
        if self.debug:
            print 'startMirroring(%r)' % branchID
        d = self.storage.startMirroring(branchID)
        if self.debug:
            def printresult(result):
                print result
                return result
            d.addBoth(printresult)
        return d

    def xmlrpc_mirrorComplete(self, branchID, lastRevisionID):
        if self.debug:
            print 'mirrorComplete(%r, %r)' % (branchID, lastRevisionID)
        return self.storage.mirrorComplete(branchID, lastRevisionID)

    def xmlrpc_mirrorFailed(self, branchID, reason):
        if self.debug:
            print 'mirrorFailed(%r, %r)' % (branchID, reason)
        return self.storage.mirrorFailed(branchID, reason)

        
