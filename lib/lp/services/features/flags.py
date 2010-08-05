# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    'FeatureController',
    ]


__metaclass__ = type


from storm.locals import Desc

from lp.services.features.model import (
    FeatureFlag,
    getFeatureStore,
    )


class Memoize(object):

    def __init__(self, calc):
        self._known = {}
        self._calc = calc

    def lookup(self, key):
        if key in self._known:
            return self._known[key]
        v = self._calc(key)
        self._known[key] = v
        return v


class ScopeDict(object):
    """Allow scopes to be looked up by getitem"""

    def __init__(self, features):
        self.features = features

    def __getitem__(self, scope_name):
        return self.features.isInScope(scope_name)


class FeatureController(object):
    """A FeatureController tells application code what features are active.

    It does this by meshing together two sources of data:
    - feature flags, typically set by an administrator into the database
    - feature scopes, which would typically be looked up based on attributes
      of the current web request, or the user for whom a job is being run, or
      something similar.

    FeatureController presents a high level interface for application code to
    query flag values, without it needing to know that they are stored in the
    database.

    At this level flag names and scope names are presented as strings for
    easier use in Python code, though the values remain unicode.  They
    should always be ascii like Python identifiers.

    One instance of FeatureController should be constructed for the lifetime
    of code that has consistent configuration values.  For instance there will
    be one per web app request.

    Intended performance: when this object is first constructed, it will read
    the whole feature flag table from the database.  It is expected to be
    reasonably small.  The scopes may be expensive to compute (eg checking
    team membership) so they are checked at most once when they are first
    needed.

    The controller is then supposed to be held in a thread-local and reused
    for the duration of the request.

    See <https://dev.launchpad.net/LEP/FeatureFlags>
    """

    def __init__(self, scope_check_callback):
        """Construct a new view of the features for a set of scopes.

        :param scope_check_callback: Given a scope name, says whether
            it's active or not.
        """
        self._known_scopes = Memoize(scope_check_callback)
        self._known_flags = Memoize(self._checkFlag)
        # rules are read from the database the first time they're needed
        self._rules = None
        self.scopes = ScopeDict(self)

    def getFlag(self, flag):
        """Get the value of a specific flag.
        
        :param flag: A name to lookup. e.g. 'recipes.enabled'
        :return: The value of the flag determined by the highest priority rule
            that matched.
        """
        return self._known_flags.lookup(flag)

    def _checkFlag(self, flag):
        self._needRules()
        if flag in self._rules:
            for scope, value in self._rules[flag]:
                if self._known_scopes.lookup(scope):
                    return value

    def isInScope(self, scope):
        return self._known_scopes.lookup(scope)

    def __getitem__(self, flag_name):
        """FeatureController can be indexed.

        This is to support easy zope traversal through eg
        "request/features/a.b.c".  We don't support other collection
        protocols.

        Note that calling this the first time for any key may cause
        arbitrarily large amounts of work to be done to determine if the
        controller is in any scopes relevant to this flag.
        """
        return self.getFlag(flag_name)

    def getAllFlags(self):
        """Return a dict of all active flags.

        This may be expensive because of evaluating many scopes, so it
        shouldn't normally be used by code that only wants to know about one
        or a few flags.
        """
        self._needRules()
        return dict((f, self.getFlag(f)) for f in self._rules)

    def _loadRules(self):
        store = getFeatureStore()
        d = {}
        rs = (store
                .find(FeatureFlag)
                .order_by(Desc(FeatureFlag.priority))
                .values(FeatureFlag.flag, FeatureFlag.scope,
                    FeatureFlag.value))
        for flag, scope, value in rs:
            d.setdefault(str(flag), []).append((str(scope), value))
        return d

    def _needRules(self):
        if self._rules is None:
            self._rules = self._loadRules()

    def usedFlags(self):
        """Return dict of flags used in this controller so far."""
        return dict(self._known_flags._known)

    def usedScopes(self):
        """Return {scope: active} for scopes that have been used so far."""
        return dict(self._known_scopes._known)
