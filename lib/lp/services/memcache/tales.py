# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementation of the memcache: namespace in TALES."""

__metaclass__ = type
__all__ = []


from hashlib import md5
import logging
import os.path

from zope.component import getUtility
from zope.tal.talinterpreter import TALInterpreter, I18nMessageTypes

from canonical.base import base
from canonical.config import config
from canonical.launchpad import versioninfo
from canonical.launchpad.webapp.interfaces import ILaunchBag
from lp.services.memcache.interfaces import IMemcacheClient


class MemcacheExpr:
    """Namespace to provide memcache caching of page template chunks.

    This namespace is exclusively used in tal:content directives.
    The only sensible way of using this is the following syntax:

    <div tal:content="memcache:1h public">
        [... Potentially expensive page template chunk ...]
    </div>
    """
    def __init__(self, name, expr, engine):
        """expr is in the format "visibility, 42 units".

        visibility is one of...

            public: All users see the same cached information.

            private: Authenticated users see a personal copy of the cached
                     information. Unauthenticated users share a copy of
                     the cached information.

            anonymous: Unauthenticated users use a shared copy of the
                       cached information. Authenticated users don't
                       use the cache.

        units is one of 'seconds', 'minutes', 'hours' or 'days'.

        visibility is required. If the cache timeout is not specified,
        it defaults to 'never timeout' (memcache will still purge the
        information when in a LRU fashion when things fill up).
        """
        self._s = expr

        if ',' in expr:
            self.visibility, max_age = (s.strip() for s in expr.split(','))
        else:
            self.visibility = expr.strip()
            max_age = None
        assert self.visibility in ('anonymous', 'public', 'private'), (
            'visibility must be anonymous, public or private')

        if max_age is None:
            self.max_age = 0
        else:
            value, unit = max_age.split(' ')
            value = float(value)
            if unit[0] == 's':
                pass
            elif unit[0] == 'm':
                value *= 60
            elif unit[0] == 'h':
                value *= 60 * 60
            elif unit[0] == 'd':
                value *= 24 * 60 * 60
            else:
                raise AssertionError("Unknown unit %s" % unit)
            self.max_age = int(value)

    _valid_key_characters = ''.join(
        chr(i) for i in range(33, 127) if i != ord(':'))

    # For use with str.translate to sanitize keys. No control characters
    # allowed, and we skip ':' too since it is a magic separator.
    _key_translate_map = (
        '_'*33 + ''.join(chr(i) for i in range(33, ord(':'))) + '_'
        + ''.join(chr(i) for i in range(ord(':')+1, 127)) + '_' * 129)

    def getKey(self, econtext):
        """We need to calculate a unique key for this cached chunk.

        To ensure content is uniquely identified, we must include:
            - a user id if this chunk is not 'public'
            - the template source file name
            - the position in the source file
            - a counter to cope with cached chunks in loops
            - the revision number of the source tree
            - the config in use
            - the URL and query string
        """
        # We include the URL and query string in the key.
        # We use the full, unadulterated url to calculate a hash.
        # We use a sanitized version in the human readable chunk of
        # the key.
        request = econtext.getValue('request')
        url = str(request.URL) + '?' + request['QUERY_STRING']
        url = url.encode('utf8') # Ensure it is a byte string.
        sanitized_url = url.translate(self._key_translate_map)

        # We include the source file and position in the source file in
        # the key.
        source_file = os.path.abspath(econtext.source_file)
        source_file = source_file[
            len(os.path.commonprefix([source_file, config.root + '/lib']))+1:]

        # We include the visibility in the key so private information
        # is not leaked. We use 'p' for public information, 'a' for
        # unauthenticated user information, or Person.id for private
        # information.
        if self.visibility == 'public':
            uid = 'p'
        else:
            logged_in_user = getUtility(ILaunchBag).user
            if logged_in_user is None:
                uid = 'a'
            else:
                uid = str(logged_in_user.id)

        # We include a counter in the key, reset at the start of the
        # request, to ensure we get unique but repeatable keys inside
        # tal:repeat loops.
        counter_key = 'lp.services.memcache.tales.counter'
        counter = request.annotations.get(counter_key, 0) + 1
        request.annotations[counter_key] = counter

        # We use pt: as a unique prefix to ensure no clashes with other
        # components using the memcached servers. The order of components
        # below only matters for human readability and memcached reporting
        # tools - it doesn't really matter provided all the components are
        # included and separators used.
        key = "pt:%s:%s,%s:%s:%d,%d:%d,%s" % (
            config.instance_name,
            source_file, versioninfo.revno, uid,
            econtext.position[0], econtext.position[1], counter,
            sanitized_url,
            )

        # Memcached max key length is 250, so truncate but ensure uniqueness
        # with a hash. A short hash is good, provided it is still unique,
        # to preserve readability as much as possible. We include the
        # unsanitized URL in the hash to ensure uniqueness.
        key_hash = base(int(md5(key + url).hexdigest(), 16), 62)
        key = key[:250-len(key_hash)] + key_hash

        return key

    def __call__(self, econtext):

        # If we have an 'anonymous' visibility chunk and are logged in,
        # we don't cache. Return the 'default' magic token to interpret
        # the contents.
        request = econtext.getValue('request')
        if (self.visibility == 'anonymous'
            and getUtility(ILaunchBag).user is not None):
            return econtext.getDefault()

        # Calculate a unique key so we serve the right cached information.
        key = self.getKey(econtext)

        cached_chunk = getUtility(IMemcacheClient).get(key)

        if cached_chunk is None:
            logging.debug("Memcache miss for %s", key)
            return MemcacheMiss(key, self.max_age)
        else:
            logging.debug("Memcache hit for %s", key)
            return MemcacheHit(cached_chunk)

    def __str__(self):
        return 'memcache expression (%s)' % self._s

    def __repr__(self):
        return '<MemcacheExpr %s>' % self._s


class MemcacheMiss:
    """Callback for the customized TALInterpreter to invoke.

    If the memcache hit failed, the TALInterpreter interprets the
    tag contents and invokes this callback, which will store the
    result in memcache against the key calculated by the MemcacheExpr.
    """
    def __init__(self, key, max_age):
        self._key = key
        self._max_age = max_age

    def __call__(self, value):
        if getUtility(IMemcacheClient).set(
            self._key, value, self._max_age):
            logging.debug("Memcache set succeeded for %s", self._key)
        else:
            logging.warn("Memcache set failed for %s", self._key)

    def __repr__(self):
        return "<MemcacheCallback %s %d>" % (self._key, self._max_age)


class MemcacheHit:
    """A prerendered chunk retrieved from cache.

    We use a special object so the TALInterpreter knows that this
    information should not be quoted.
    """
    def __init__(self, value):
        self.value = value

    def __unicode__(self):
        return self.value


# Oh my bleeding eyes! Monkey patching & cargo culting seems the sanest
# way of installing our extensions, which makes me sad.

def do_insertText_tal(self, stuff):
    text = self.engine.evaluateText(stuff[0])
    if text is None:
        return
    if text is self.Default:
        self.interpret(stuff[1])
        return
    # Start Launchpad customization
    if isinstance(text, MemcacheMiss):
        # We got a MemcacheCallback instance. This means we hit a
        # content="memcache:..." attribute but there was no valid
        # data in memcache. So we need to interpret the enclosed
        # chunk of template and stuff it in the cache for next time.
        callback = text
        self.pushStream(self.StringIO())
        self.interpret(stuff[1])
        text = self.stream.getvalue()
        self.popStream()
        # Now we have generated the chunk, cache it for next time.
        callback(text)
        # And output it to the currently rendered page, unquoted.
        self.stream_write(text)
        return
    if isinstance(text, MemcacheHit):
        # Got a hit. Include the contents directly into the
        # rendered page, unquoted.
        self.stream_write(text.value)
        return
    # End Launchpad customization
    if isinstance(text, I18nMessageTypes):
        # Translate this now.
        text = self.translate(text)
    self._writeText(text)
TALInterpreter.bytecode_handlers_tal["insertText"] = do_insertText_tal


# Just like the original, except MemcacheHit and MemcacheMiss
# instances are also passed through unharmed.
def evaluateText(self, expr):
    text = self.evaluate(expr)
    if (text is None
        or isinstance(text, (basestring, MemcacheHit, MemcacheMiss))
        or text is self.getDefault()):
        return text
    return unicode(text)
import zope.pagetemplate.engine
zope.pagetemplate.engine.ZopeContextBase.evaluateText = evaluateText

