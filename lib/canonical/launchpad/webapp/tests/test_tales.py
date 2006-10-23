# Copyright 2004 Canonical Ltd.  All rights reserved.
#

import unittest
from zope.testing.doctestunit import DocTestSuite

def test_requestapi():
    """
    >>> from canonical.launchpad.webapp.tales import IRequestAPI, RequestAPI
    >>> from canonical.launchpad.interfaces import IPerson
    >>> from zope.interface.verify import verifyObject

    >>> class FakePrincipal:
    ...     def __conform__(self, protocol):
    ...         if protocol is IPerson:
    ...             return "This is a person"
    ...

    >>> class FakeApplicationRequest:
    ...    principal = FakePrincipal()
    ...

    Let's make a fake request, where request.principal is a FakePrincipal
    object.  We can use a class or an instance here.  It really doesn't
    matter.

    >>> request = FakeApplicationRequest
    >>> adapter = RequestAPI(request)

    >>> verifyObject(IRequestAPI, adapter)
    True

    >>> adapter.person
    'This is a person'

    """

def test_dbschemaapi():
    """
    >>> from canonical.launchpad.webapp.tales import DBSchemaAPI
    >>> from canonical.lp.dbschema import ManifestEntryType

    The syntax to get the title is: number/lp:DBSchemaClass

    >>> (str(DBSchemaAPI(4).traverse('ManifestEntryType', []))
    ...  == ManifestEntryType.TAR.title)
    True

    Using an inappropriate number should give a KeyError.

    >>> DBSchemaAPI(99).traverse('ManifestEntryType', [])
    Traceback (most recent call last):
    ...
    KeyError: 99

    Using a dbschema name that doesn't exist should give a TraversalError

    >>> DBSchemaAPI(99).traverse('NotADBSchema', [])
    Traceback (most recent call last):
    ...
    TraversalError: 'NotADBSchema'

    We should also test names that are in the dbschema module, but are
    not DBSchemas.

    >>> import canonical.lp.dbschema
    >>> from canonical.lp.dbschema import Item
    >>> DBSchemaAPI(1).traverse('Item', [])
    Traceback (most recent call last):
    ...
    TraversalError: 'Item'

    """

def test_re_substitute():
    """
    When formatting text, we want to replace portions with links.
    re.sub() works fairly well for this, but doesn't give us much
    control over the non-matched text.  The re_substitute() function
    lets us do that.

    >>> import re
    >>> from canonical.launchpad.webapp.tales import re_substitute

    >>> def match_func(match):
    ...     return '[%s]' % match.group()
    >>> def nomatch_func(text):
    ...     return '{%s}' % text

    >>> pat = re.compile('a{2,6}')
    >>> print re_substitute(pat, match_func, nomatch_func,
    ...                     'aaaabbbbaaaaaaa aaaaaaaa')
    [aaaa]{bbbb}[aaaaaa]{a }[aaaaaa][aa]
    """

def test_add_word_breaks():
    """
    Long words can cause page layout problems, so we insert manual
    word breaks into long words.  Breaks are added at least once every
    15 characters, but will break on as little as 7 characters if
    there is a suitable non-alphanumeric character to break after.

      >>> from canonical.launchpad.webapp.tales import add_word_breaks

      >>> print add_word_breaks('abcdefghijklmnop')
      abcdefghijklmno<wbr></wbr>p

      >>> print add_word_breaks('abcdef/ghijklmnop')
      abcdef/<wbr></wbr>ghijklmnop

      >>> print add_word_breaks('ab/cdefghijklmnop')
      ab/cdefghijklmn<wbr></wbr>op

    The string can contain HTML entities, which do not get split:
    
      >>> print add_word_breaks('abcdef&anentity;hijklmnop')
      abcdef&anentity;<wbr></wbr>hijklmnop
    """

def test_break_long_words():
    """
    If we have a long HTML string, break_long_words() can be used to
    add word breaks to the long words.  It will not add breaks inside HTML
    tags.  Only words longer than 20 characters will have breaks added.

      >>> from canonical.launchpad.webapp.tales import break_long_words

      >>> print break_long_words('1234567890123456')
      1234567890123456

      >>> print break_long_words('12345678901234567890')
      123456789012345<wbr></wbr>67890

      >>> print break_long_words('<tag a12345678901234567890="foo"></tag>')
      <tag a12345678901234567890="foo"></tag>

      >>> print break_long_words('12345678901234567890 1234567890.1234567890')
      123456789012345<wbr></wbr>67890 1234567890.<wbr></wbr>1234567890

      >>> print break_long_words('1234567890&abcdefghi;123')
      1234567890&abcdefghi;123
    """

def test_suite():
    suite = DocTestSuite()
    return suite


if __name__ == '__main__':
    unittest.main()
