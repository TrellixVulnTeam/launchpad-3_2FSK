# Copyright 2004 Canonical Ltd.  All rights reserved.
#
"""What you get from the lp: namespace in TALES.

"""
__metaclass__ = type

# XXX IPerson should be defined in this canonical.lp package
from canonical.launchpad.interfaces import IPerson
from zope.publisher.interfaces import IApplicationRequest
from zope.interface import Interface, Attribute, implements
import canonical.lp.dbschema

class IRequestAPI(Interface):
    """Launchpad lp:... API available for an IApplicationRequest."""

    person = Attribute("The IPerson for the request's principal.")

class RequestAPI:
    """Adapter from IApplicationRequest to IRequestAPI."""
    implements(IRequestAPI)

    __used_for__ = IApplicationRequest

    def __init__(self, request):
        self.request = request

    def person(self):
        return IPerson(self.request.principal, None)
    person = property(person)


class DBSchemaAPI:
    """Adapter from integers to things that can extract information from
    DBSchemas.
    """
    _all = dict([(name, getattr(canonical.lp.dbschema, name))
                 for name in canonical.lp.dbschema.__all__])

    def __init__(self, number):
        self._number = number

    def __getattr__(self, name):
        if name in self._all:
            return self._all[name]._items[self._number].title
        else:
            raise AttributeError, name

import cgi

class FormattersAPI:
    """Adapter from strings to HTML formatted text."""

    def __init__(self, s):
        self._s = s

    def nl_to_br(self):
        '''Quote HTML characters, then replace newlines with <br /> tags'''
        return cgi.escape(self._s).replace('\n','<br />')

