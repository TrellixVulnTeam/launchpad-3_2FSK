# Copyright 2004 Canonical Ltd.  All rights reserved.

from twisted.web import xmlrpc

class UserDetailsResource(xmlrpc.XMLRPC):

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

    def xmlrpc_authUser(self, loginID, sshaDigestedPassword):
        """Authenticate a user
        
        :returns: user dict if authenticated, otherwise empty dict
        """
        if self.debug:
            print 'authUser(%r, %r)' % (loginID, sshaDigestedPassword)
        return self.storage.authUser(loginID,
                                     sshaDigestedPassword.decode('base64'))

    def xmlrpc_createUser(self, loginID, sshaDigestedPassword, displayname,
                          emailAddresses):
        """Create a user
        
        :returns: user dict, or TBD if there is an error such as a database
            constraint being violated.
        """
        if self.debug:
            print ("createUser(%r, %r, %r, %r)"
                   % (loginID, sshaDigestedPassword, displayname,
                      emailAddresses))
        return self.storage.createUser(loginID,
                                       sshaDigestedPassword.decode('base64'), 
                                       displayname, emailAddresses)

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

