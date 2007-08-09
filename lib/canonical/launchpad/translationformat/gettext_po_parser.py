# Copyright 2004-2007 Canonical Ltd.  All rights reserved.
#
# Contains code from msgfmt.py (available from python source code),
#     written by Martin v. Loewis <loewis@informatik.hu-berlin.de>
#     changed by Christian 'Tiran' Heimes <ch@comlounge.net>

__metaclass__ = type

__all__ = [
    'POMessage',
    'POHeader',
    'POParser',
    ]

import re
import codecs
import logging
import doctest
import unittest

from zope.interface import implements
from zope.app import datetimeutils

from canonical.launchpad.interfaces import (
    ITranslationMessage, ITranslationHeader, IPOParser, EXPORT_DATE_HEADER,
    TranslationFormatInvalidInputError, TranslationFormatSyntaxError,
    UnknownTranslationRevisionDate)


class POSyntaxWarning(Warning):
    """ Syntax warning in a po file """

    def __init__(self, lno=0, msg=None):
        self.lno = lno
        self.msg = msg

    def __str__(self):
        if self.msg:
            return self.msg
        elif self.lno is None:
            return 'PO file: syntax warning on unknown line'
        else:
            return 'Po file: syntax warning on entry at line %d' % self.lno


class POMessage(object):

    implements(ITranslationMessage)

    def __init__(self, **kw):
        self._check(**kw)
        self.msgid = kw.get('msgid', '')
        self.msgid_plural = kw.get('msgid_plural', '')
        self.msgstr = kw.get('msgstr', '')
        self.comment = kw.get('comment', '')
        self.source_comment = kw.get('source_comment', '')
        self.file_references = kw.get('file_references', '').strip()
        self.flags = kw.get('flags', set())
        self.msgstr_plurals = kw.get('msgstr_plurals', [])
        self.obsolete = kw.get('obsolete', False)
        self._lineno = kw.get('_lineno')

    @property
    def translations(self):
        """See `ITranslationMessage`."""
        if self.msgstr_plurals:
            # There are plural forms.
            return self.msgstr_plurals
        elif self.msgstr:
            # There is a single form translation.
            return [self.msgstr]
        else:
            # There are no translations.
            return []

    def _check(self, **kw):
        """Log warning messages about non critical problems in the message."""
        if kw.get('msgstr_plurals'):
            if 'header' not in kw or type(kw['header'].nplurals) is not int:
                logging.warning(POSyntaxWarning(
                    msg="File has plural forms, but plural-forms header entry"
                        " is missing or invalid."
                    ))
            if len(kw['msgstr_plurals']) > kw['header'].nplurals:
                logging.warning(POSyntaxWarning(
                    lno=kw.get('_lineno'),
                    msg="Bad number of plural-forms in entry '%s' (line %s)."
                        % (kw['msgid'], str(kw.get('_lineno')))
                    ))

    def is_obsolete(self):
        return self.obsolete

    def __nonzero__(self):
        return bool(self.msgid)

    def flagsText(self, flags=None, withHash=True):
        if flags is None:
            flags = self.flags
        if not flags:
            return ''
        flags = list(flags)
        flags.sort()
        if 'fuzzy' in flags:
            flags.remove('fuzzy')
            flags.insert(0, 'fuzzy')
        if withHash:
            prefix = u'#, '
        else:
            prefix = u''
        return prefix + u', '.join(flags)

    class _fake_wrapper(object):
        width = None
        initial_indent = subsequent_indent = u'"'
        def wrap(self, text):
            return [self.initial_indent + text]

    def __unicode__(self, wrap=77):
        r'''
        Text representation of the message.  Should wrap correctly.
        For some of these examples to work (the ones with plural forms),
        we need a header that looks valid.
        '
        >>> header = POHeader()

        >>> header.nplurals = 2

        (end of initialization)

        >>> unicode(POMessage(msgid="foo", msgstr="bar"))
        u'msgid "foo"\nmsgstr "bar"'

        obsolete entries are prefixed with #~
        >>> unicode(POMessage(msgid="foo", msgstr="bar", flags=("fuzzy",), obsolete=True))
        u'#, fuzzy\n#~ msgid "foo"\n#~ msgstr "bar"'

        plural forms automatically trigger the correct syntax
        >>> unicode(
        ...     POMessage(header=header, msgid="foo", msgid_plural="foos",
        ...               msgstr_plurals=["bar", "bars"]))
        u'msgid "foo"\nmsgid_plural "foos"\nmsgstr[0] "bar"\nmsgstr[1] "bars"'

        backslashes are escaped (doubled) and quotes are backslashed
        >>> unicode(POMessage(msgid='foo"bar\\baz', msgstr='z'))
        u'msgid "foo\\"bar\\\\baz"\nmsgstr "z"'

        tabs are backslashed too, with standard C syntax
        >>> unicode(POMessage(msgid="\tServer name: %s", msgstr=""))
        u'msgid "\\tServer name: %s"\nmsgstr ""'

        '''
        return '\n'.join([
            self._comments_representation(),
            self._msgids_representation(wrap),
            self._msgstrs_representation(wrap),
            ]).strip()

    def _comments_representation(self):
        r'''
        Text representation of the comments.
        '

        >>> unicode(POMessage(msgid="foo", msgstr="bar",flags=("fuzzy",)))
        u'#, fuzzy\nmsgid "foo"\nmsgstr "bar"'
        >>> unicode(POMessage(msgid="a", msgstr="b", comment=" blah\n"))
        u'# blah\nmsgid "a"\nmsgstr "b"'
        >>> unicode(POMessage(msgid="%d foo", msgstr="%d bar", flags=('fuzzy', 'c-format')))
        u'#, fuzzy, c-format\nmsgid "%d foo"\nmsgstr "%d bar"'

        '(this single-quote is here to appease emacs)
        '''
        text = []
        # comment and source_comment always end in a newline, so
        # splitting by \n always results in an empty last element
        if self.comment:
            for line in self.comment.split('\n')[:-1]:
                text.append(u'#' + line)
        if self.source_comment and not self.obsolete:
            # If it's an obsolete entry, the source comments are not exported.
            for line in self.source_comment.split('\n')[:-1]:
                text.append(u'#. ' + line)
        # not so for references - we strip() it
        if self.file_references and not self.obsolete:
            # If it's an obsolete entry, the references are not exported.
            for line in self.file_references.split('\n'):
                text.append(u'#: ' + line)
        if self.flags:
            text.append(self.flagsText())
        return u'\n'.join(text)

    def _msgids_representation(self, wrap_width):
        text = self._wrap(self.msgid, u'msgid', wrap_width)
        if self.msgid_plural:
            text.extend(
                self._wrap(self.msgid_plural, u'msgid_plural', wrap_width))
        if self.obsolete:
            text = ['#~ ' + l for l in text]
        return u'\n'.join(text)

    def _msgstrs_representation(self, wrap_width):
        text = []
        if self.msgstr_plurals:
            for i, s in enumerate(self.msgstr_plurals):
                text.extend(self._wrap(s, u'msgstr[%s]' % i, wrap_width))
        elif self.msgid_plural:
            # It's a plural form but we don't have any translation for it.
            text = ([u'msgstr[0] ""', u'msgstr[1] ""'])
        else:
            # It's a singular form.
            text = self._wrap(self.msgstr, u'msgstr', wrap_width)
        if self.obsolete:
            text = ['#~ ' + l for l in text]
        return u'\n'.join(text)

    def _wrap(self, text, prefix, wrap_width):
        r'''
        This method does the actual wrapping.

        >>> POMessage(msgid="abcdefghijkl", msgstr="z").__unicode__(20)
        u'msgid "abcdefghijkl"\nmsgstr "z"'
        >>> POMessage(msgid="abcdefghijklmnopqr", msgstr="z").__unicode__(20)
        u'msgid ""\n"abcdefghijklmnopqr"\nmsgstr "z"'
        >>> POMessage(msgid="abcdef hijklm", msgstr="z").__unicode__(20)
        u'msgid ""\n"abcdef hijklm"\nmsgstr "z"'
        >>> POMessage(msgid="abcdefghijklmnopqr st", msgstr="z").__unicode__(20)
        u'msgid ""\n"abcdefghijklmnopqr "\n"st"\nmsgstr "z"'
        >>> POMessage(msgid="abc\ndef", msgstr="z").__unicode__(20)
        u'msgid ""\n"abc\\n"\n"def"\nmsgstr "z"'

        newlines in the text interfere with wrapping
        >>> unicode(POMessage(msgid="abc\ndef", msgstr="z"))
        u'msgid ""\n"abc\\n"\n"def"\nmsgstr "z"'

        but not when it's just a line that ends with a newline char
        >>> unicode(POMessage(msgid="abc\n", msgstr="def\n"))
        u'msgid "abc\\n"\nmsgstr "def\\n"'

        It's time to test the wrapping with the '-' char:
        >>> pomsg = POMessage(
        ...     msgid="WARNING: unsafe enclosing directory permissions on homedir `%s'\n",
        ...     msgstr="WARNUNG: Unsichere Zugriffsrechte des umgebenden Verzeichnisses des Home-Verzeichnisses `%s'\n"
        ...     )
        >>> print unicode(pomsg)
        msgid "WARNING: unsafe enclosing directory permissions on homedir `%s'\n"
        msgstr ""
        "WARNUNG: Unsichere Zugriffsrechte des umgebenden Verzeichnisses des Home-"
        "Verzeichnisses `%s'\n"

        When we changed the wrapping code, we got a bug with this string.
        >>> pomsg = POMessage(
        ...     msgid="The location and hierarchy of the Evolution contact folders has changed since Evolution 1.x.\n\n",
        ...     msgstr="")
        >>> print unicode(pomsg)
        msgid ""
        "The location and hierarchy of the Evolution contact folders has changed "
        "since Evolution 1.x.\n"
        "\n"
        msgstr ""

        When the wrapping size was exactly gotten past by in the middle of
        escape sequence like \" or \\, it got cut off in there, thus
        creating a broken PO message.  This is bug #46156.
        >>> pomsg = POMessage(
        ...     msgid="1234567890abcde word\"1234567890abcdefghij",
        ...     msgstr="")
        >>> print pomsg.__unicode__(20)
        msgid ""
        "1234567890abcde "
        "word\"1234567890abcd"
        "efghij"
        msgstr ""

        Lets also make sure that the unconditional break is not occurring
        inside a single long word in the middle of the escape sequence
        like \" or \\:

        >>> pomsg = POMessage(
        ...     msgid="1234567890abcdefghij\\klmno",
        ...     msgstr="")
        >>> print pomsg.__unicode__(20)
        msgid ""
        "1234567890abcdefghij"
        "\\klmno"
        msgstr ""
        >>> pomsg = POMessage(
        ...     msgid="1234567890abcdefgh\\ijklmno",
        ...     msgstr="")
        >>> print pomsg.__unicode__(20)
        msgid ""
        "1234567890abcdefgh\\"
        "ijklmno"
        msgstr ""
        >>> pomsg = POMessage(
        ...     msgid="1234567890abcdefg\\\\hijklmno",
        ...     msgstr="")
        >>> print pomsg.__unicode__(20)
        msgid ""
        "1234567890abcdefg\\"
        "\\hijklmno"
        msgstr ""


        For compatibility with msgcat -w, it also wraps on \\ properly.

        >>> pomsg = POMessage(
        ...     msgid="\\\\\\\\\\",
        ...     msgstr="")
        >>> print pomsg.__unicode__(5)
        msgid ""
        "\\\\"
        "\\\\"
        "\\"
        msgstr ""
        >>> print pomsg.__unicode__(6)
        msgid ""
        "\\\\\\"
        "\\\\"
        msgstr ""

        '''
        def local_escape(text):
            ret = text.replace(u'\\', u'\\\\')
            ret = ret.replace(ur'"', ur'\"')
            ret = ret.replace(u'\t', u'\\t')
            return ret.replace(u'\n', u'\\n')

        # Quickly get escaped character byte widths using
        #   escaped_length.get(char, 1)
        escaped_length = {
            '\\': 2,
            '\"': 2,
            '\t': 2,
            '\n': 2}

        # What characters to wrap at
        wrap_at = [' ', '\t', '\n', '-', '\\']

        if wrap_width is None:
            raise AssertionError('wrap_width should not be None')
        wrapped_lines = [u'%s%s' % (prefix, u' ""')]
        if not text:
            return wrapped_lines
        if '\n' not in text[:-1]:
            # If there are no new-lines, or it's at the end of string.
            unwrapped_line = u'%s "%s"' % (prefix, local_escape(text))
            if len(unwrapped_line) <= wrap_width:
                return [unwrapped_line]
            del unwrapped_line
        paragraphs = text.split('\n')
        end = len(paragraphs) - 1
        for i, paragraph in enumerate(paragraphs):
            if i == end:
                if not paragraph:
                    break
            else:
                paragraph += '\n'

            if len(local_escape(paragraph)) <= wrap_width:
                wrapped_line = [paragraph]
            else:
                line = u''
                escaped_line_len = 0
                new_block = u''
                escaped_new_block_len = 0
                wrapped_line = []
                for char in paragraph:
                    escaped_char_len = escaped_length.get(char, 1)
                    if (escaped_line_len + escaped_new_block_len
                        + escaped_char_len <= wrap_width):
                        if char in wrap_at:
                            line += u'%s%s' % (new_block, char)
                            escaped_line_len += (escaped_new_block_len
                                                 + escaped_char_len)
                            new_block = u''
                            escaped_new_block_len = 0
                        else:
                            new_block += char
                            escaped_new_block_len += escaped_char_len
                    else:
                        if escaped_line_len == 0:
                            # Word is too long to fit into single line,
                            # break it carefully, watching not to break
                            # in the middle of the escape
                            line = new_block
                            line_len = len(line)
                            escaped_line_len = escaped_new_block_len
                            while escaped_line_len > wrap_width:
                                escaped_line_len -= (
                                    escaped_length.get(line[line_len-1], 1))
                                line_len -= 1
                            line = line[:line_len]
                            new_block = new_block[line_len:]
                            escaped_new_block_len -= escaped_line_len
                        wrapped_line.append(line)
                        line = u''
                        escaped_line_len = 0
                        new_block += char
                        escaped_new_block_len += escaped_char_len
                if line or new_block:
                    wrapped_line.append(u'%s%s' % (line, new_block))
            for line in wrapped_line:
                wrapped_lines.append(u'"%s"' % (local_escape(line)))
        return wrapped_lines


class POHeader(dict, POMessage):

    implements(ITranslationHeader, ITranslationMessage)

    def __init__(self, **kw):
        dict.__init__(self)

        # the charset is not known til the header has been parsed.
        # Scan for the charset in the same way that gettext does.
        self.charset = 'CHARSET'
        if 'msgstr' in kw:
            match = re.search(r'charset=([^\s]+)', kw['msgstr'])
            if match:
                self.charset = match.group(1)
        if self.charset == 'CHARSET':
            self.charset = 'US-ASCII'

        for attr in ('msgid', 'msgstr', 'comment', 'source_comment'):
            if attr in kw:
                if isinstance(kw[attr], str):
                    kw[attr] = unicode(kw[attr], self.charset, 'replace')

        POMessage.__init__(self, **kw)
        self._casefold = {}
        self.header = self
        self.messages = kw.get('messages', [])
        self.nplurals = None
        self.pluralExpr = '0'


    def updateDict(self):
        """Sync the msgstr content with the dict like object that represents
        this object.
        """
        for key in self.keys():
            # Remove any previous dict entry.
            dict.__delitem__(self, key)

        for attr in ('msgid_plural', 'msgstr_plurals', 'file_references'):
            if getattr(self, attr):
                logging.warning(POSyntaxWarning(
                    msg='PO file header entry should have no %s' % attr))
                setattr(self, attr, u'')

        for line in self.msgstr.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                field, value = line.split(':', 1)
            except ValueError:
                logging.warning(POSyntaxWarning(
                    msg='PO file header entry has a bad entry: %s' % line))
                continue
            field, value = field.strip(), value.strip()
            if field.lower() == 'plural-forms':
                try:
                    self.__setitem__(field, value, False)
                except ValueError:
                    raise TranslationFormatInvalidInputError(
                            message='Malformed plural-forms header entry')
            else:
                self.__setitem__(field, value, False)
        if 'content-type' not in self:
            logging.warning(POSyntaxWarning(
                msg='PO file header entry has no content-type field'))
            self['Content-Type'] = 'text/plain; charset=ASCII'

    def _decode(self, v):
        try:
            v = unicode(v, self.charset)
        except UnicodeError:
            logging.warning(POSyntaxWarning(
                self._lineno,
                'string is not in declared charset %r' % self.charset
                ))
            v = unicode(v, self.charset, 'replace')
        except LookupError:
            raise TranslationFormatInvalidInputError(
                message='Unknown charset %r' % self.charset)

        return v

    def get(self, item, default=None):
        v = None
        try:
            v = dict.__getitem__(self, item)
        except KeyError:
            try:
                v = self._casefold[item.lower()]
            except KeyError:
                if default == []:
                    raise KeyError, item
                else:
                    return default
        if type(v) is str:
            v = self._decode(v)
        return v

    def __getitem__(self, item):
        # XXX CarlosPerelloMarin 2007-06-13: Instead of an empty list
        # we should raise NotFoundException.
        return self.get(item, [])

    def has_key(self, item):
        try:
            self[item]
        except KeyError:
            return False
        else:
            return True

    __contains__ = has_key

    def __setitem__(self, item, value, update_msgstr=True):
        if not self.has_key(item) and self._casefold.has_key(item.lower()):
            for key in self.keys():
                if key.lower() == item.lower():
                    item = key
        oldvalue = self.get(item)
        dict.__setitem__(self, item, value)
        self._casefold[item.lower()] = value

        if item.lower() == 'content-type':
            parts = parse_assignments(self['content-type'], skipfirst=True)
            if 'charset' in parts:
                if parts['charset'] != 'CHARSET':
                    self.charset = parts['charset']
                else:
                    self.charset = 'ASCII'
            # Convert attributes to unicode
            for attr in ('msgid', 'msgstr', 'comment', 'source_comment'):
                v = getattr(self, attr)
                if type(v) is str:
                    v = self._decode(v)
                setattr(self, attr, v)

        # Plural forms logic
        elif item.lower() == 'plural-forms':
            parts = parse_assignments(self['plural-forms'])
            if parts.get('nplurals') == 'INTEGER':
                # sure hope it's a template.
                self.nplurals = 2
            else:
                nplurals = parts.get('nplurals')
                try:
                    self.nplurals = int(nplurals)
                except TypeError:
                    # There are some po files with bad headers that have a non
                    # numeric value here and sometimes an empty value. In that
                    # case, set the default value.
                    logging.warning(POSyntaxWarning(
                        self._lineno,
                        "The plural form header has an unknown error. Using"
                        " the default value..."
                        ))
                    self.nplurals = 2
                self.pluralExpr = parts.get('plural', '0')

        # Update msgstr
        if update_msgstr:
            text = []
            printed = set()
            for l in self.msgstr.strip().split('\n'):
                l = l.strip()
                if not l:
                    continue
                try:
                    field, value = l.split(':', 1)
                except ValueError:
                    # The header has an entry without ':' that's an error in
                    # the header, log it and continue with next entry.
                    logging.warning(
                        POSyntaxWarning(self._lineno, 'Invalid header entry.'))
                    continue
                field = field.strip()
                try:
                    value = self[field]
                except KeyError:
                    # The header has an entry with ':' but otherwise
                    # unrecognized: it happens with plural form formulae
                    # split into two lines, yet containing C-style ':' operator
                    # log it and continue with next entry.
                    logging.warning(
                        POSyntaxWarning(self._lineno, 'Invalid header entry.'))
                    continue
                text.append(u'%s: %s' % (field, self[field]))
                printed.add(field)
            for field in self.keys():
                if field not in printed:
                    value = self[field]
                    text.append(u'%s: %s' % (field, self[field]))
            text.append('')
            self.msgstr = u'\n'.join(text)

    def __delitem__(self, item):
        # Update the msgstr entry
        # XXX: CarlosPerelloMarin 2005-09-01: This parser sucks too much!
        text = []
        for l in self.msgstr.strip().split('\n'):
            l = l.strip()
            if not l:
                continue
            try:
                field, value = l.split(':', 1)
            except ValueError:
                # The header has an entry without ':' that's an error in
                # the header, log it and continue with next entry.
                logging.warning(
                    POSyntaxWarning(self._lineno, 'Invalid header entry.'))
                continue
            field = field.strip()
            if field.lower() != item.lower():
                text.append(l)
        text.append('')
        self.msgstr = u'\n'.join(text)

        # And now, the dict part of the object needs to be rebuilt...
        self.updateDict()

    def update(self, other):
        for key in other:
            # not using items() because this way we get decoding
            self[key] = other[key]

    def copy(self):
        cp = POHeader(self)
        cp.updateDict()
        # copy any changes made by user-code
        cp.update(self)
        return cp

    def recode(self, charset):
        "A copy with a different charset"
        cp = self.copy()
        cp.charset = charset
        ct_flags = ['text/plain']
        for o in self['content-type'].split(';')[1:]:
            try:
                name, value = o.split('=')
            except ValueError:
                ct_flags.append(o.strip())
                continue
            name, value = name.strip(), value.strip()
            if name.lower() == 'charset':
                value = charset
            ct_flags.append('%s=%s' % (name, value))
        cp['Content-Type'] = '; '.join(ct_flags)
        return cp

    def __nonzero__(self):
        return bool(self.keys())

    def getTranslationRevisionDate(self):
        """See ITranslationHeader."""

        date_string = self.get('PO-Revision-Date')
        if date_string is None:
            raise UnknownTranslationRevisionDate, (
                'There is no revision date information available.')

        try:
            return datetimeutils.parseDatetimetz(date_string)
        except datetimeutils.DateTimeError:
            raise UnknownTranslationRevisionDate, (
                'Found an invalid date representation: %r' % date_string)

    def getLaunchpadExportDate(self):
        """See ITranslationHeader."""

        date_string = self.get(EXPORT_DATE_HEADER, None)
        if date_string is None:
            date = None
        else:
            try:
                date = datetimeutils.parseDatetimetz(date_string)
            except datetimeutils.DateTimeError:
                # invalid date format
                date = None

        return date

    def getPluralFormExpression(self):
        """See ITranslationHeader."""
        plural = self.get('Plural-Forms')
        if not plural:
            return None
        parts = parse_assignments(plural)
        if parts.has_key("plural"):
            return parts["plural"]
        else:
            return None

    def getRawContent(self):
        """See ITranslationHeader."""
        return self.msgstr


class POParser(object):

    implements(IPOParser)

    def __init__(self, translation_factory=POMessage, header_factory=POHeader):
        self.translation_factory = translation_factory
        self.header_factory = header_factory
        self.header = None
        self.messages = []
        self._messageids = {}
        self._pending_chars = ''
        self._pending_unichars = u''
        self._lineno = 0
        self._make_dataholder()
        self._section = None
        self._plural_case = None

    def _convert_chars(self):
        # is there anything to convert?
        if not self._pending_chars:
            return

        # if the PO header hasn't been parsed, then we don't know the
        # encoding yet
        if not self.header:
            return

        decode = codecs.getdecoder(self.header.charset)
        # decode as many characters as we can:
        try:
            newchars, length = decode(self._pending_chars, 'strict')
        except UnicodeDecodeError, exc:
            # XXX: James Henstridge 2006-03-16:
            # If the number of unconvertable chars is longer than a
            # multibyte sequence to be, the UnicodeDecodeError indicates
            # a real error, rather than a partial read.
            # I don't know what the longest multibyte sequence in the
            # encodings we need to support, but it shouldn't be more
            # than 10 bytes ...
            if len(self._pending_chars) - exc.start > 10:
                raise TranslationFormatInvalidInputError(
                    line_number=self._lineno,
                    message="could not decode input from %s" % (
                        self.header.charset))
            newchars, length = decode(self._pending_chars[:exc.start],
                                      'strict')
        self._pending_unichars += newchars
        self._pending_chars = self._pending_chars[length:]

    def _get_header_line(self):
        if self.header:
            # We know what charset the data is in, as we've already
            # parsed the header.  However, we're going to handle this
            # more efficiently, so we don't want to use _get_header_line
            # except for parsing the header.
            raise AssertionError(
                'using _get_header_line after header is parsed')

        # We don't know what charset the data is in, so we parse it one line
        # at a time until we have the header, and then we'll know how to
        # treat the rest of the data.
        parts = re.split(r'\n|\r\n|\r', self._pending_chars, 1)
        if len(parts) == 1:
            # only one line
            return None
        line, self._pending_chars = parts
        return line

    def write(self, string):
        """Parse string as a PO file fragment."""
        self._pending_chars += string
        if self.header:
            self._convert_chars()
            return

        # Header not parsed yet. Do that first, inefficiently.
        # It ought to be short, so this isn't disastrous.
        line = self._get_header_line()
        while line is not None:
            self.parse_line(line)
            if self.header:
                break
            line = self._get_header_line()

        if line is None:
            # There is nothing left to parse.
            return

        # Parse anything left all in one go.
        lines = re.split(r'\n|\r\n|\r', self._pending_unichars)
        if lines:
            # If we have any lines, the last one should be the empty string,
            # if we have a properly-formed po file with a new line at the
            # end.  So, put the last line into _pending_unichars so the rest
            # of the parser gets what's expected.
            self._pending_unichars = lines[-1]
            lines = lines[:-1]
        for line in lines:
            self.parse_line(line)

    def _make_dataholder(self):
        self._partial_transl = {}
        self._partial_transl['msgid'] = ''
        self._partial_transl['msgid_plural'] = ''
        self._partial_transl['msgstr'] = ''
        self._partial_transl['comment'] = ''
        self._partial_transl['source_comment'] = ''
        self._partial_transl['file_references'] = ''
        self._partial_transl['flags'] = set()
        self._partial_transl['msgstr_plurals'] = []
        self._partial_transl['obsolete'] = False
        self._partial_transl['_lineno'] = self._lineno

    def append(self):
        if self._partial_transl:
            if self._messageids.has_key(self._partial_transl['msgid']):
                lineno = self._partial_transl['_lineno']
                # XXX kiko 2005-10-06 bug=2896: I changed the exception
                # below to use %r because the original %d returned
                # "<unprintable instance object>"
                raise TranslationFormatInvalidInputError(
                    message='Po file: duplicate msgid ending on line %r' % (
                        lineno))
            try:
                transl = self.translation_factory(header=self.header,
                                                  **self._partial_transl)
            except (TranslationFormatSyntaxError,
                    TranslationFormatInvalidInputError), e:
                if e.line_number is None:
                    e.line_number = self._partial_transl['_lineno']
                raise
            self.messages.append(transl)
            self._messageids[self._partial_transl['msgid']] = True
        self._partial_transl = None

    def _make_header(self):
        try:
            self.header = self.header_factory(messages=self.messages, 
                                              **self._partial_transl)
            self.header.updateDict()
        except (TranslationFormatSyntaxError,
                TranslationFormatInvalidInputError), e:
            if e.line_number is None:
                e.line_number = self._partial_transl['_lineno']
            raise
        if self.messages:
            logging.warning(POSyntaxWarning(self._lineno,
                                          'Header entry is not first entry'))

        # convert buffered input to the encoding specified in the PO header
        self._convert_chars()

    def _parse_quoted_string(self, string):
        r"""Parse a quoted string, interpreting escape sequences.

          >>> parser = POParser()
          >>> parser._parse_quoted_string(u'\"abc\"')
          u'abc'
          >>> parser._parse_quoted_string(u'\"abc\\ndef\"')
          u'abc\ndef'
          >>> parser._parse_quoted_string(u'\"ab\x63\"')
          u'abc'
          >>> parser._parse_quoted_string(u'\"ab\143\"')
          u'abc'

          After the string has been converted to unicode, the backslash
          escaped sequences are still in the encoding that the charset header
          specifies. Such quoted sequences will be converted to unicode by
          this method.

          We don't know the encoding of the escaped characters and cannot be
          just recoded as Unicode so it's a TranslationFormatInvalidInputError
          >>> utf8_string = u'"view \\302\\253${version_title}\\302\\273"'
          >>> parser._parse_quoted_string(utf8_string)
          Traceback (most recent call last):
          ...
          TranslationFormatInvalidInputError: could not decode escaped string: (\302\253)

          Now, we note the original encoding so we get the right Unicode
          string.

          >>> class FakeHeader:
          ...     charset = 'UTF-8'
          >>> parser.header = FakeHeader()
          >>> parser._parse_quoted_string(utf8_string)
          u'view \xab${version_title}\xbb'

          Let's see that we raise a TranslationFormatInvalidInputError exception when we
          have an escaped char that is not valid in the declared encoding
          of the original string:

          >>> iso8859_1_string = u'"foo \\xf9"'
          >>> parser._parse_quoted_string(iso8859_1_string)
          Traceback (most recent call last):
          ...
          TranslationFormatInvalidInputError: could not decode escaped string as UTF-8: (\xf9)

          An error will be raised if the entire string isn't contained in
          quotes properly:

          >>> parser._parse_quoted_string(u'abc')
          Traceback (most recent call last):
            ...
          TranslationFormatSyntaxError: string is not quoted
          >>> parser._parse_quoted_string(u'\"ab')
          Traceback (most recent call last):
            ...
          TranslationFormatSyntaxError: string not terminated
          >>> parser._parse_quoted_string(u'\"ab\"x')
          Traceback (most recent call last):
            ...
          TranslationFormatSyntaxError: extra content found after string: (x)
        """
        if string[0] != '"':
            raise TranslationFormatSyntaxError(
                line_number=self._lineno, message="string is not quoted")

        escape_map = {
            'a': '\a',
            'b': '\b',
            'f': '\f',
            'n': '\n',
            'r': '\r',
            't': '\t',
            'v': '\v',
            '"': '"',
            '\'': '\'',
            '\\': '\\',
            }

        # Remove initial quote char
        string = string[1:]
        output = ''
        while string:
            if string[0] == '"':
                # Reached the end of the quoted string.  It's rare, but there
                # may be another quoted string on the same line.  It should be
                # suffixed to what we already have, with any whitespace
                # between the strings removed.
                string = string[1:].lstrip()
                if not string:
                    # End of line, end of string: the normal case
                    break
                if string[0] == '"':
                    # Start of a new string.  We've already swallowed the
                    # closing quote and any intervening whitespace; now
                    # swallow the re-opening quote and go on as if the string
                    # just went on normally
                    string = string[1:]
                    continue

                # if there is any non-string data afterwards, raise an
                # exception
                if string and not string.isspace():
                    raise TranslationFormatSyntaxError(
                        line_number=self._lineno,
                        message="extra content found after string: (%s)" % string)
                break
            elif string[0] == '\\' and string[1] in escape_map:
                # We got one of the special escaped chars we know about, we
                # unescape them using the mapping table we have.
                output += escape_map[string[1]]
                string = string[2:]
                continue

            escaped_string = ''
            while string[0] == '\\':
                # Let's handle any normal char escaped. This kind of chars are
                # still in the original encoding so we need to extract the
                # whole block of escaped chars to recode them later into
                # Unicode.
                if string[1] == 'x':
                    # hexadecimal escape
                    escaped_string += string[:4]
                    string = string[4:]
                elif string[1].isdigit():
                    # octal escape
                    escaped_string += string[:2]
                    string = string[2:]
                    # up to two more octal digits
                    for i in range(2):
                        if string[0].isdigit():
                            escaped_string += string[0]
                            string = string[1:]
                        else:
                            break
                elif string[1] in escape_map:
                    # It's part of our mapping table, we ignore it here.
                    break
                else:
                    raise TranslationFormatSyntaxError(
                        line_number=self._lineno,
                        message="unknown escape sequence %s" % string[:2])
            if escaped_string:
                # We found some text escaped that should be recoded to
                # Unicode.
                # First, we unescape it.
                unescaped_string = escaped_string.decode('string-escape')

                if self.header is not None:
                    # There is a header, so we know the original encoding for
                    # the given string.
                    try:
                        output += unescaped_string.decode(self.header.charset)
                    except UnicodeDecodeError:
                        raise TranslationFormatInvalidInputError(
                            line_number=self._lineno,
                            message=(
                                "could not decode escaped string as %s: (%s)"
                                    % (self.header.charset, escaped_string)))
                else:
                    # We don't know the original encoding of the imported file
                    # so we cannot get the right values. We store the string
                    # assuming that is a valid ASCII escape sequence.
                    try:
                        output += unescaped_string.decode('ascii')
                    except UnicodeDecodeError:
                        raise TranslationFormatInvalidInputError(
                            line_number=self._lineno,
                            message=(
                                "could not decode escaped string: (%s)" % (
                                    escaped_string)))
            else:
                # It's a normal char, we just store it and jump to next one.
                output += string[0]
                string = string[1:]
        else:
            # We finished parsing the string without finding the ending quote
            # char.
            raise TranslationFormatSyntaxError(
                line_number=self._lineno, message="string not terminated")

        return output

    def parse_line(self, l):
        self._lineno += 1
        # Skip empty lines
        l = l.strip()

        obsolete = False
        if l[:2] == '#~':
            obsolete = True
            l = l[2:].lstrip()

        if not l:
            return
        # If we get a comment line after a msgstr or a line starting with
        # msgid, this is a new entry
        # l.startswith('msgid') is needed because not all msgid/msgstr
        # pairs have a leading comment
        if ((l.startswith('#') or l.startswith('msgid')) and
            self._section == 'msgstr'):
            if self._partial_transl is None:
                # first entry - do nothing
                pass
            elif self._partial_transl['msgid']:
                self.append()
            elif not self.header:
                # this is the potfile header
                self._make_header()
            self._make_dataholder()
            self._section = None
        # Record that the message is known obsolete
        if obsolete:
            self._partial_transl['obsolete'] = True

        if l[0] == '#':
            # Record flags
            if l[:2] == '#,':
                new_flags = [flag.strip() for flag in l[2:].split(',')]
                self._partial_transl['flags'].update(new_flags)
                return
            # Record file references
            if l[:2] == '#:':
                self._partial_transl['file_references'] += l[2:].strip() + '\n'
                return
            # Record source comments
            if l[:2] == '#.':
                self._partial_transl['source_comment'] += l[2:].strip() + '\n'
                return
            # Record comments
            self._partial_transl['comment'] += l[1:] + '\n'
            return
        # Now we are in a msgid section, output previous section
        if l.startswith('msgid_plural'):
            if self._section != 'msgid':
                raise TranslationFormatSyntaxError(line_number=self._lineno)
            self._section = 'msgid_plural'
            l = l[12:]
        elif l.startswith('msgid'):
            if self._section and self._section.startswith('msgid'):
                raise TranslationFormatSyntaxError(line_number=self._lineno)
            self._section = 'msgid'
            l = l[5:]
            self._plural_case = None
        # Now we are in a msgstr section
        elif l.startswith('msgstr'):
            self._section = 'msgstr'
            l = l[6:]
            # XXX kiko 2005-08-19: if l is empty, it means we got an msgstr
            # followed by a newline; that may be critical, but who knows?
            if l and l[0] == '[':
                # plural case
                new_plural_case, l = l[1:].split(']', 1)
                new_plural_case = int(new_plural_case)
                if (self._plural_case is not None) and (
                        new_plural_case != self._plural_case + 1):
                    logging.warning(POSyntaxWarning(self._lineno,
                                                  'bad plural case number'))
                if new_plural_case != self._plural_case:
                    self._partial_transl['msgstr_plurals'].append('')
                    self._plural_case = new_plural_case
                else:
                    logging.warning(POSyntaxWarning(
                        self._lineno, 'msgstr[] but same plural case number'))
            else:
                self._plural_case = None

        l = l.strip()
        if not l:
            logging.warning(POSyntaxWarning(
                self._lineno,
                'line has no content; this is not supported by '
                'some implementations of msgfmt'))
            return

        l = self._parse_quoted_string(l)

        if self._section == 'msgid':
            self._partial_transl['msgid'] += l
        elif self._section == 'msgid_plural':
            self._partial_transl['msgid_plural'] += l
        elif self._section == 'msgstr':
            if self._plural_case is None:
                self._partial_transl['msgstr'] += l
            else:
                self._partial_transl['msgstr_plurals'][-1] += l
        else:
            raise TranslationFormatSyntaxError(line_number=self._lineno)

    def finish(self):
        """Indicate that the PO data has come to an end.
        Throws an exception if the parser was in the
        middle of a message."""
        # handle remaining buffered data:
        if self.header:
            if self._pending_chars:
                raise TranslationFormatInvalidInputError(
                    line_number=self._lineno,
                    message='could not decode input from %s' % (
                        self.header.charset))
            if self._pending_unichars:
                logging.warning(POSyntaxWarning(
                    self._lineno, 'No newline at end of file'))
                self.parse_line(self._pending_unichars)
        else:
            if self._pending_chars:
                logging.warning(POSyntaxWarning(
                    self._lineno, 'No newline at end of file'))
                self.parse_line(self._pending_chars)

        if self._section and self._section.startswith('msgid'):
            raise TranslationFormatSyntaxError(line_number=self._lineno)

        if self._partial_transl and self._partial_transl['msgid']:
            self.append()
        elif self._partial_transl is not None:
            if self._partial_transl and (self._section is None):
                # input ends in a comment -- should this always be an error?
                raise TranslationFormatSyntaxError(line_number=self._lineno)
            elif not self.header:
                # header is last entry... in practice this should
                # only happen when the file is empty
                self._make_header()

        if not self.header:
            raise TranslationFormatSyntaxError(
                message='No header found in this pofile')


# convenience function to parse "assignment" expressions like
# the plural-form header

def parse_assignments(text, separator=';', assigner='=', skipfirst=False):
    parts = {}
    if skipfirst:
        start=1
    else:
        start=0
    for assignment in text.split(separator)[start:]:
        if not assignment.strip():
            # empty
            continue
        if assigner in assignment:
            name, value = assignment.split(assigner, 1)
        else:
            logging.warning(POSyntaxWarning(
                msg="Found an error in the header content: %s" % text
                ))
            continue

        parts[name.strip()] = value.strip()
    return parts

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    runner.run(doctest.DocTestSuite())
