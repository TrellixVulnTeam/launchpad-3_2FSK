# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = [
    'DoesNotProvide',
    'DoesNotCorrectlyProvide',
    'HasQueryCount',
    'IsNotProxied',
    'IsProxied',
    'Provides',
    'ProvidesAndIsProxied',
    ]

from zope.interface.verify import verifyObject
from zope.interface.exceptions import (
    BrokenImplementation, BrokenMethodImplementation, DoesNotImplement)
from zope.security.proxy import builtin_isinstance, Proxy

from testtools.content import Content
from testtools.content_type import ContentType
from testtools.matchers import Matcher, Mismatch


class DoesNotProvide(Mismatch):
    """An object does not provide an interface."""

    def __init__(self, obj, interface):
        """Create a DoesNotProvide Mismatch.

        :param obj: the object that does not match.
        :param interface: the Interface that the object was supposed to match.
        """
        self.obj = obj
        self.interface = interface

    def describe(self):
        return "%r does not provide %r." % (self.obj, self.interface)


class DoesNotCorrectlyProvide(DoesNotProvide):
    """An object does not correctly provide an interface."""

    def __init__(self, obj, interface, extra=None):
        """Create a DoesNotCorrectlyProvide Mismatch.

        :param obj: the object that does not match.
        :param interface: the Interface that the object was supposed to match.
        :param extra: any extra information about the mismatch as a string,
            or None
        """
        super(DoesNotCorrectlyProvide, self).__init__(obj, interface)
        self.extra = extra

    def describe(self):
        if self.extra is not None:
            extra = ": %s" % self.extra
        else:
            extra = "."
        return ("%r claims to provide %r, but does not do so correctly%s"
                % (self.obj, self.interface, extra))


class Provides(Matcher):
    """Test that an object provides a certain interface."""

    def __init__(self, interface):
        """Create a Provides Matcher.

        :param interface: the Interface that the object should provide.
        """
        self.interface = interface

    def __str__(self):
        return "provides %r." % self.interface

    def match(self, matchee):
        if not self.interface.providedBy(matchee):
            return DoesNotProvide(matchee, self.interface)
        passed = True
        extra = None
        try:
            if not verifyObject(self.interface, matchee):
                passed = False
        except (BrokenImplementation, BrokenMethodImplementation,
                DoesNotImplement), e:
            passed = False
            extra = str(e)
        if not passed:
            return DoesNotCorrectlyProvide(
                matchee, self.interface, extra=extra)
        return None


class HasQueryCount(Matcher):
    """Adapt a Binary Matcher to the query count on a QueryCollector.

    If there is a mismatch, the queries from the collector are provided as a
    test attachment.
    """

    def __init__(self, count_matcher):
        """Create a HasQueryCount that will match using count_matcher."""
        self.count_matcher = count_matcher

    def __str__(self):
        return "HasQueryCount(%s)" % self.count_matcher

    def match(self, something):
        mismatch = self.count_matcher.match(something.count)
        if mismatch is None:
            return None
        return _MismatchedQueryCount(mismatch, something)


class _MismatchedQueryCount(Mismatch):
    """The Mismatch for a HasQueryCount matcher."""

    def __init__(self, mismatch, query_collector):
        self.count_mismatch = mismatch
        self.query_collector = query_collector

    def describe(self):
        return "queries do not match: %s" % (self.count_mismatch.describe(),)

    def get_details(self):
        result = []
        for query in self.query_collector.queries:
            result.append(unicode(query).encode('utf8'))
        return {'queries': Content(ContentType('text', 'plain',
            {'charset': 'utf8'}), lambda:['\n'.join(result)])}
 

class IsNotProxied(Mismatch):
    """An object is not proxied."""

    def __init__(self, obj):
        """Create an IsNotProxied Mismatch.

        :param obj: the object that is not proxied.
        """
        self.obj = obj

    def describe(self):
        return "%r is not proxied." % self.obj


class IsProxied(Matcher):
    """Check that an object is proxied."""

    def __str__(self):
        return "Is proxied."

    def match(self, matchee):
        if not builtin_isinstance(matchee, Proxy):
            return IsNotProxied(matchee)
        return None


class ProvidesAndIsProxied(Matcher):
    """Test that an object implements an interface, and is proxied."""

    def __init__(self, interface):
        """Create a ProvidesAndIsProxied matcher.

        :param interface: the Interface the object must provide.
        """
        self.interface = interface

    def __str__(self):
        return "Provides %r and is proxied." % self.interface

    def match(self, matchee):
        mismatch = Provides(self.interface).match(matchee)
        if mismatch is not None:
            return mismatch
        return IsProxied().match(matchee)
