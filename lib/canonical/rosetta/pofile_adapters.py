from canonical.rosetta.ipofile import IPOHeader, IPOMessage
from canonical.rosetta.pofile import POHeader, POMessage, POParser, POInvalidInputError
from canonical.rosetta.interfaces import IPOTemplate, IPOFile
from zope.interface import implements
import sets

class DatabaseConstraintError(Exception):
    pass
class UnknownUserError(Exception):
    pass


# XXX: if you *modify* the adapted pofile "object", it assumes you're updating
#      it from the latest revision (for the purposes of inLastRevision fields).
#      That should probably be optional.


class WatchedSet(sets.Set):
    """ Mutable set class that "warns" a callable when changed."""
    # (Used for bridging flags/flagsComment)

    # need __slots__ because sets.Set says we do
    __slots__ = ['_watcher']

    def __init__(self, watcher, iterable=None):
        """Construct a set from an optional iterable.
        Watcher is called, with self as an argument, whenever
        our contents change."""
        self._data = {}
        self._watcher = watcher
        if iterable is not None:
            sets.Set._update(self, iterable)

    def _update(self, iterable):
        sets.Set._update(self, iterable)
        self._watcher(self)

    def __ior__(self, other):
        sets.Set.__ior__(self, other)
        self._watcher(self)

    def __iand__(self, other):
        sets.Set.__iand__(self, other)
        self._watcher(self)

    def intersection_update(self, other):
        sets.Set.intersection_update(self, other)
        self._watcher(self)

    def symmetric_difference_update(self, other):
        sets.Set.symmetric_difference_update(self, other)
        self._watcher(self)

    def difference_update(self, other):
        sets.Set.difference_update(self, other)
        self._watcher(self)

    def clear(self):
        sets.Set.clear(self)
        self._watcher(self)

    def add(self, element):
        sets.Set.add(self, element)
        self._watcher(self)

    def remove(self, element):
        sets.Set.remove(self, element)
        self._watcher(self)

    def pop(self):
        sets.Set.pop(self)
        self._watcher(self)


class TranslationsList(object):
    """Special list-like object to bridge translations.  It pretends to
    be a list of strings, but it actually fetches values from the database,
    using translation sightings associated with the passed message set."""
    def __init__(self, messageset, person):
        # message set we'll use to access the database
        self._msgset = messageset
        # a person - in case we need to create rows
        self._who = person
        # cache the number of plural forms, as we use that value a lot
        if messageset.poFile is None:
            # allow pot-sets to have 2 msgstrs, since some efforts
            # seem to like it that way
            self._nplurals = len(list(messageset.messageIDs()))
        else:
            # find the correct number of forms - fortunately we
            # have a method that does just that
            self._nplurals = messageset.pluralForms()

    # XXX: this list implementation is incomplete.  Dude, if you want to do
    # del foo.msgstrs[2]
    # or
    # foo.msgstrs.pop()
    # then you're probably on crack anyway.

    def __setitem__(self, index, value):
        "one single item is being set; index is the plural form"
        # an empty value is interpreted by Rosetta as not having
        # translation for this form; we don't have sightings for
        # the empty translation.
        if not value:
            # if our message set is a template set, then it's *supposed*
            # to not have any translations
            if self._msgset.poFile is None:
                return
            # if it's a pofile set, then check if there was already a
            # translation in the DB which needs to be outdated
            try:
                sighting = self._msgset.getTranslationSighting(index, allowOld=False)
            except IndexError:
                # nothing passed, nothing in the DB, then it's ok
                return
            # there is one in the DB; mark it as historic
            sighting.inLastRevision = False
            # we're done
            return

        # value is not empty; there is actually a translation
        # check that the plural form index makes sense
        if index > self._nplurals:
            raise IndexError, index
        # if we're a template set, we can't have translations
        if self._msgset.poFile is None:
            raise pofile.POSyntaxError(msg="PO Template has translations!")
        # if we don't have a Person instance, we can't create rows
        if self._who is None:
            raise UnknownUserError, \
                  "Tried to create objects but have no Person to associate it with"
        # create a translation sighting, or update an existing one
        self._msgset.makeTranslationSighting(self._who, value, index,
                                             update=True, fromPOFile=True)

    def __getitem__(self, index):
        "one single item is being requested; index is the plural form"
        # first check if it is in the database
        try:
            return self._msgset.getTranslationSighting(index, allowOld=False).poTranslation.translation
        except KeyError:
            # it's not; but if it's a valid plural form, we should return
            # an empty string
            if index < self._nplurals:
                return ''
            # otherwise, raise an exception
            raise IndexError, index

    def __len__(self):
        "return the number of actual translations."
        # XXX shouldn't it maybe return self._nplurals since this is the
        # number of items __getitem__ will return?
        return len(list(self._msgset.translations()))

    def append(self, value):
        "add a new item at the end of the list"
        # only valid if we're not already complete
        if len(self) >= self._nplurals:
            raise ValueError, "Too many plural forms"
        # and if we have an associated Person object
        if self._who is None:
            raise UnknownUserError, \
                  "Tried to create objects but have no Person to associate it with"
        # XXX: should probably check if value is not empty/None
        # create (or update) a translation sighting
        self._msgset.makeTranslationSighting(self._who, value, len(self),
                                             update=True, fromPOFile=True)


# marker value used as default in the constructor, to detect the fact
# that an actual parameter was not passed in
_marker = []

class MessageProxy(POMessage):
    implements(IPOMessage)

    def __init__(self, msgset, template_msgset=_marker, person=None):
        """Initialize a proxy.  We pretend to be a POMessage (and
        in fact shamelessly leech its methods), but our *data* is
        acquired from the database.  We get the data associated with
        msgset; optionally, we can have a "master" msgset which will
        be used for some authoritative information - tipically, when
        msgset is a pofile-set, the corresponding template-set will
        be used as master_msgset.  The person object is used in case
        we need to create rows (for translations, sightings, etc)."""
        self._msgset = msgset
        self._override_obsolete = False
        if master_msgset is _marker:
            self._master_msgset = msgset
        elif master_msgset is None:
            self._master_msgset = msgset
            self._override_obsolete = True
        else:
            self._master_msgset = master_msgset
        self._who = person
        # create and store the TranslationsList object; since it's
        # fully dynamic, we can have a single one troughout our
        # lifetime
        self._translations = TranslationsList(msgset, person)
        self._pending_writes = {}

    def flush(self):
        self._msgset.set(**self._pending_writes)

    def _get_msgid(self):
        return self._msgset.primeMessageID_.msgid
    def _set_msgid(self):
        raise DatabaseConstraintError("The primary message ID of a messageset can't be changed"
                                      " once it's in the database.  Create a new messageset"
                                      " instead.")
    msgid = property(_get_msgid, _set_msgid)

    def _get_msgidPlural(self):
        msgids = self._master_msgset.messageIDs()
        if len(list(msgids)) >= 2:
            return msgids[1].msgid
        return None
    def _set_msgidPlural(self, value):
        # do we already have one?
        old_plural = self.msgidPlural
        if old_plural is not None:
            old_plural = self._msgset.getMessageIDSighting(1)
            old_plural.inPOFile = False
        if value:
            self._msgset.makeMessageIDSighting(value, 1, update=True)
    msgidPlural = property(_get_msgidPlural, _set_msgidPlural)

    def _get_msgstr(self):
        if self._msgset.poFile is None:
            return None
        translations = list(self._msgset.translations())
        if len(translations) == 1:
            return translations[0]
    def _set_msgstr(self, value):
        # let's avoid duplication of code
        self._translations[0] = value
    msgstr = property(_get_msgstr, _set_msgstr)

    def _get_msgstrPlurals(self):
        if self._msgset.poFile is None:
            return None
        translations = list(self._msgset.translations())
        if len(translations) > 1:
            # test is necessary because the interface says when
            # there are no plurals, msgstrPlurals is None
            return self._translations
    def _set_msgstrPlurals(self, value):
        for index, item in enumerate(value):
            self._translations[index] = item
    msgstrPlurals = property(_get_msgstrPlurals, _set_msgstrPlurals)

    def _get_commentText(self):
        if not self._msgset.commentText:
            return None
        return self._msgset.commentText + '\n'
    def _set_commentText(self, value):
        if value and value[-1] == '\n':
            value = value[:-1]
        self._pending_writes['commentText'] = value
    commentText = property(_get_commentText, _set_commentText)

    def _get_sourceComment(self):
        if not self._master_msgset.sourceComment:
            return None
        return self._master_msgset.sourceComment + '\n'
    def _set_sourceComment(self, value):
        if value and value[-1] == '\n':
            value = value[:-1]
        self._pending_writes['sourceComment'] = value
    sourceComment = property(_get_sourceComment, _set_sourceComment)

    def _get_fileReferences(self):
        return self._master_msgset.fileReferences
    def _set_fileReferences(self, value):
        self._pending_writes['fileReferences'] = value
    fileReferences = property(_get_fileReferences, _set_fileReferences)

    def _get_flags(self):
        flags = self._master_msgset.flagsComment or ''
        if flags:
            fl = [flag.strip() for flag in flags.split(',')]
        else:
            fl = []
        if self._msgset.fuzzy:
            fl.append('fuzzy')
        return WatchedSet(self._set_flags, fl)
    def _set_flags(self, value):
        value = list(value)
        if 'fuzzy' in value:
            value.remove('fuzzy')
            self._pending_writes['fuzzy'] = True
        else:
            self._pending_writes['fuzzy'] = False
        self._pending_writes['flagsComment'] = self.flagsText(value, withHash=False)
    flags = property(_get_flags, _set_flags)

    def _get_obsolete(self):
        if self._override_obsolete:
            return True
        elif self._msgset is self._master_msgset:
            return self._msgset.obsolete
        else:
            return self._master_msgset.sequence == 0
    def _set_obsolete(self, value):
        self._pending_writes['obsolete'] = value
    obsolete = property(_get_obsolete, _set_obsolete)


class TemplateImporter(object):
    __used_for__ = IPOTemplate

    def __init__(self, potemplate, person):
        self.potemplate = potemplate
        self.len = 0
        self.parser = POParser(translation_factory=self)
        self.person = person

    def doImport(self, filelike):
        "Import a file (or similar object)"
        self.potemplate.expireAllMessages()
        # what policy here? small bites? lines? how much memory do we want to eat?
        self.parser.write(filelike.read())
        self.parser.finish()
        if not self.parser.header:
            raise POInvalidInputError('PO template has no header', 0)

    def __call__(self, msgid, **kw):
        "Instantiate a single message/messageset"
        try:
            msgset = self.potemplate.messageSet(msgid)
        except KeyError:
            msgset = self.potemplate.createMessageSetFromText(msgid)
        else:
            msgset.getMessageIDSighting(0, allowOld=True).dateLastSeen = "NOW"
        self.len += 1
        msgset.sequence = self.len
        proxy = MessageProxy(msgset, person=self.person)
        try:
            proxy.msgidPlural = kw.get('msgidPlural', None)
            if kw.get('msgstr'):
                raise POInvalidInputError('PO template has msgstrs', 0)
            proxy.commentText = kw.get('commentText', '')
            proxy.sourceComment = kw.get('sourceComment', '')
            proxy.fileReferences = kw.get('fileReferences', '').strip()
            proxy.flags = kw.get('flags', ())
            plurals = []
            for inp_plural in kw.get('msgstrPlurals', ()):
                if inp_plural:
                    raise POInvalidInputError('PO template has msgstrs', 0)
                plurals.append(inp_plural)
            proxy.msgstrPlurals = plurals
            proxy.obsolete = kw.get('obsolete', False)
            proxy.flush()
        except:
            from canonical.rosetta.pofile import DEBUG
            if DEBUG:
                import traceback
                traceback.print_exc()
            raise POInvalidInputError
        return proxy


class POFileImporter(object):
    __used_for__ = IPOFile

    def __init__(self, pofile, person):
        self.pofile = pofile
        self.len = 0
        self.parser = POParser(translation_factory=self)
        self.person = person
        self.header_stored = False

    def store_header(self):
        if self.header_stored or not self.parser.header:
            return
        self.pofile.set(
            topComment=self.parser.header.commentText.encode('utf-8'),
            header=self.parser.header.msgstr.encode('utf-8'),
            headerFuzzy='fuzzy' in self.parser.header.flags,
            pluralForms=self.parser.header.nplurals)
        self.header_stored = True

    def doImport(self, filelike):
        "Import a file (or similar object)"
        self.pofile.expireAllMessages()
        # what policy here? small bites? lines? how much memory do we want to eat?
        self.parser.write(filelike.read())
        self.parser.finish()
        self.store_header()
        if not self.header_stored:
            raise POInvalidInputError('PO file has no header', 0)

    def __call__(self, msgid, **kw):
        "Instantiate a single message/messageset"
        self.store_header()
        try:
            msgset = self.pofile[msgid]
        except KeyError:
            msgset = self.pofile.createMessageSetFromText(msgid)
        else:
            msgset.getMessageIDSighting(0, allowOld=True).dateLastSeen = "NOW"
        self.len += 1
        msgset.sequence = self.len
        msgset.getMessageIDSighting(0, allowOld=True).inLastRevision = True
        proxy = MessageProxy(msgset, person=self.person)
        try:
            proxy.msgidPlural = kw.get('msgidPlural', None)
            if kw.get('msgstr'):
                proxy.msgstr = kw['msgstr']
            proxy.commentText = kw.get('commentText', '')
            proxy.sourceComment = kw.get('sourceComment', '')
            proxy.fileReferences = kw.get('fileReferences', '').strip()
            proxy.flags = kw.get('flags', ())
            if kw.get('msgstrPlurals'):
                proxy.msgstrPlurals = kw['msgstrPlurals']
            proxy.obsolete = kw.get('obsolete', False)
            proxy.flush()
        except:
            from canonical.rosetta.pofile import DEBUG
            if DEBUG:
                import traceback
                traceback.print_exc()
            raise POInvalidInputError
        return proxy
