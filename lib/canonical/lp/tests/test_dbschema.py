# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Tests for classes in canonical.lp.dbschema."""

import unittest
from zope.testing.doctestunit import DocTestSuite

def test_sorting():
    """
    DBSchema items sort themselves based on the order they are defined in the
    class.  That order can be changed by using the sortkey parameter.


    >>> from canonical.launchpad.webapp.enum import Item, DBSchema
    >>> class SortingTest(DBSchema):
    ...
    ...     lobster = Item(9, 'A lobster', 'signifies completion')
    ...     crayfish = Item(2, 'A crayfish', 'signifies good taste in women', sortkey=14)
    ...     langoustine = Item(12, 'A langoustine', 'signifies emptiness')

    >>> SortingTest.lobster < SortingTest.langoustine < SortingTest.crayfish
    True
    >>> SortingTest.crayfish > SortingTest.langoustine > SortingTest.lobster
    True

    """

def test_constructor():
    """
    We're definitely intending to do something that we should be warned
    about: compare an Item to an int.  So, disable these warnings for just
    this module.

    >>> import warnings
    >>> warnings.filterwarnings("ignore", "comparison of DBSchema",
    ...     module=__name__)

    We can import Item.

    >>> from canonical.launchpad.webapp.enum import Item

    An Item can be created only within a class suite, and its first arg
    must be an int.

    >>> item = Item(2, 'a foo', 'description of a foo')
    Traceback (most recent call last):
    ...
    TypeError: Item can be used only from a class definition.
    >>> class SomeClass:
    ...    attribute = Item('foo', 'a foo', 'description of a foo')
    ...
    Traceback (most recent call last):
    ...
    TypeError: value must be an int, not 'foo'
    >>> class SomeClass:
    ...    description = "Description of some class"
    ...    attribute = Item(2, 'a foo', 'description of a foo')
    ...    attr3 = Item(3, '''
    ...        Some item title
    ...
    ...        Description.
    ...        ''')
    ...
    >>> SomeClass.attribute.value
    2
    >>> SomeClass.attribute.name
    'attribute'
    >>> SomeClass.attribute.title
    'a foo'
    >>> SomeClass.attribute.description
    'description of a foo'

    An Item can be cast into an int or a string, for use as a replacement in
    SQL statements.

    >>> print "SELECT * from Foo where Foo.id = '%d';" % (
    ...     SomeClass.attribute.value)
    SELECT * from Foo where Foo.id = '2';
    >>> print "SELECT * from Foo where Foo.id = '%s';" % SomeClass.attribute
    SELECT * from Foo where Foo.id = '2';
    >>> int(SomeClass.attribute)
    Traceback (most recent call last):
    ...
    TypeError: Cannot cast Item to int.  Use item.value instead.

    An Item is not particularly comparable to ints.  It always compares
    unequal.

    >>> 1 == SomeClass.attribute
    False
    >>> 1 != SomeClass.attribute
    True
    >>> 2 == SomeClass.attribute
    False
    >>> SomeClass.attribute == 1
    False
    >>> SomeClass.attribute == 2
    False
    >>> hash(SomeClass.attribute)
    2
    >>> SomeClass._items[2] is SomeClass.attribute
    True

    An Item compares properly when security proxied.

    >>> item = SomeClass.attribute
    >>> from zope.security.checker import ProxyFactory, NamesChecker
    >>> checker = NamesChecker(['value', 'schema'])
    >>> proxied_item = ProxyFactory(item, checker=checker)
    >>> proxied_item is item
    False
    >>> proxied_item == item
    True
    >>> item == proxied_item
    True
    >>> item.__ne__(proxied_item)
    False

    An Item has an informative representation.

    >>> print repr(SomeClass.attribute)
    <Item attribute (2) from canonical.lp.tests.test_dbschema.SomeClass>

    An Item can tell you its class.

    >>> SomeClass.attribute.schema is SomeClass
    True

    An Item knows how to represent itself for use in SQL queries by SQLObject.
    The 'None' value passed in is the database type (I think).

    >>> SomeClass.attribute.__sqlrepr__(None)
    '2'

    An Item will not compare equal to an Item from a different schema.

    To test this, we'll create another schema, then compare items.

    >>> class SomeOtherClass:
    ...    description = "Description of some other class"
    ...    attr3 = Item(3, 'an other foo', 'description of an other foo')
    ...
    >>> SomeClass.attr3.value == SomeOtherClass.attr3.value
    True
    >>> SomeOtherClass.attr3 == SomeClass.attr3
    False

    An Item can be used as a key in a dict.

    >>> d = {SomeClass.attribute: 'some class attribute',
    ...      SomeClass.attr3: 'some other class attriubte'}
    >>> d[SomeClass.attr3]
    'some other class attriubte'

    """

def test_decorator():
    """
    >>> from canonical.lp.dbschema import BugTaskImportance
    >>> from canonical.launchpad.webapp.enum import Item

    We can iterate over the Items in a DBSchema class

    >>> for s in BugTaskImportance.items:
    ...     assert isinstance(s, Item)
    ...     print s.name
    ...
    UNDECIDED
    WISHLIST
    LOW
    MEDIUM
    HIGH
    CRITICAL
    UNKNOWN

    We can retrieve an Item by value

    >>> BugTaskImportance.items[50].name
    'CRITICAL'

    We can also retrieve an Item by name.

    >>> BugTaskImportance.items['CRITICAL'].title
    'Critical'

    If we don't ask for the item by its name or its value, we get a KeyError.

    >>> BugTaskImportance.items['foo']
    Traceback (most recent call last):
    ...
    KeyError: 'foo'

    """

def test_suite():
    suite = DocTestSuite()
    suite.addTest(DocTestSuite('canonical.lp.dbschema'))
    return suite

def _test():
    import doctest, test_dbschema
    return doctest.testmod(test_dbschema)

if __name__ == "__main__":
    _test()
    unittest.main()
