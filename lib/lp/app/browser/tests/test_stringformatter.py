# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for the string TALES formatter."""

__metaclass__ = type

from textwrap import dedent
import unittest

from zope.component import getUtility
from zope.testing.doctestunit import DocTestSuite

from canonical.config import config
from canonical.launchpad.testing.pages import find_tags_by_class
from canonical.launchpad.webapp.interfaces import ILaunchBag
from canonical.testing import DatabaseFunctionalLayer
from lp.app.browser.stringformatter import FormattersAPI
from lp.testing import TestCase


def test_split_paragraphs():
    r"""
    The split_paragraphs() method is used to split a block of text
    into paragraphs, which are separated by one or more blank lines.
    Paragraphs are yielded as a list of lines in the paragraph.

      >>> from lp.app.browser.stringformatter import split_paragraphs
      >>> for paragraph in split_paragraphs('\na\nb\n\nc\nd\n\n\n'):
      ...     print paragraph
      ['a', 'b']
      ['c', 'd']
    """


def test_re_substitute():
    """
    When formatting text, we want to replace portions with links.
    re.sub() works fairly well for this, but doesn't give us much
    control over the non-matched text.  The re_substitute() function
    lets us do that.

      >>> import re
      >>> from lp.app.browser.stringformatter import re_substitute

      >>> def match_func(match):
      ...     return '[%s]' % match.group()
      >>> def nomatch_func(text):
      ...     return '{%s}' % text

      >>> pat = re.compile('a{2,6}')
      >>> print re_substitute(pat, match_func, nomatch_func,
      ...                     'bbaaaabbbbaaaaaaa aaaaaaaab')
      {bb}[aaaa]{bbbb}[aaaaaa]{a }[aaaaaa][aa]{b}
    """


def test_add_word_breaks():
    """
    Long words can cause page layout problems, so we insert manual
    word breaks into long words.  Breaks are added at least once every
    15 characters, but will break on as little as 7 characters if
    there is a suitable non-alphanumeric character to break after.

      >>> from lp.app.browser.stringformatter import add_word_breaks

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

      >>> from lp.app.browser.stringformatter import break_long_words

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

      >>> print break_long_words('<tag>1234567890123456</tag>')
      <tag>1234567890123456</tag>
    """


class TestDiffFormatter(TestCase):
    """Test the string formtter fmt:diff."""
    layer = DatabaseFunctionalLayer

    def test_emptyString(self):
        # An empty string gives an empty string.
        self.assertEqual(
            '', FormattersAPI('').format_diff())

    def test_almostEmptyString(self):
        # White space doesn't count as empty, and is formtted.
        self.assertEqual(
            '<table class="diff"><tr><td class="line-no">1</td>'
            '<td class="text"> </td></tr></table>',
            FormattersAPI(' ').format_diff())

    def test_format_unicode(self):
        # Sometimes the strings contain unicode, those should work too.
        self.assertEqual(
            u'<table class="diff"><tr><td class="line-no">1</td>'
            u'<td class="text">Unicode \u1010</td></tr></table>',
            FormattersAPI(u'Unicode \u1010').format_diff())

    def test_cssClasses(self):
        # Different parts of the diff have different css classes.
        diff = dedent('''\
            === modified file 'tales.py'
            --- tales.py
            +++ tales.py
            @@ -2435,6 +2435,8 @@
                 def format_diff(self):
            -        removed this line
            +        added this line
            -------- a sql style comment
            ++++++++ a line of pluses
            ########
            # A merge directive comment.
            ''')
        html = FormattersAPI(diff).format_diff()
        line_numbers = find_tags_by_class(html, 'line-no')
        self.assertEqual(
            ['1','2','3','4','5','6','7','8','9', '10', '11'],
            [tag.renderContents() for tag in line_numbers])
        text = find_tags_by_class(html, 'text')
        self.assertEqual(
            ['diff-file text',
             'diff-header text',
             'diff-header text',
             'diff-chunk text',
             'text',
             'diff-removed text',
             'diff-added text',
             'diff-removed text',
             'diff-added text',
             'diff-comment text',
             'diff-comment text'],
            [str(tag['class']) for tag in text])

    def test_config_value_limits_line_count(self):
        # The config.diff.max_line_format contains the maximum number of lines
        # to format.
        diff = dedent('''\
            === modified file 'tales.py'
            --- tales.py
            +++ tales.py
            @@ -2435,6 +2435,8 @@
                 def format_diff(self):
            -        removed this line
            +        added this line
            ########
            # A merge directive comment.
            ''')
        self.pushConfig("diff", max_format_lines=3)
        html = FormattersAPI(diff).format_diff()
        line_count = html.count('<td class="line-no">')
        self.assertEqual(3, line_count)


class TestOOPSFormatter(TestCase):
    """A test case for the oops_id() string formatter."""

    layer = DatabaseFunctionalLayer

    def test_doesnt_linkify_for_non_developers(self):
        # OOPS IDs won't be linkified for non-developers.
        oops_id = 'OOPS-12345TEST'
        formatter = FormattersAPI(oops_id)
        formatted_string = formatter.oops_id()

        self.assertEqual(
            oops_id, formatted_string,
            "Formatted string should be '%s', was '%s'" % (
                oops_id, formatted_string))

    def _setDeveloper(self):
        """Override ILaunchBag.developer for testing purposes."""
        launch_bag = getUtility(ILaunchBag)
        launch_bag.setDeveloper(True)

    def test_linkifies_for_developers(self):
        # OOPS IDs will be linkified for Launchpad developers.
        oops_id = 'OOPS-12345TEST'
        formatter = FormattersAPI(oops_id)

        self._setDeveloper()
        formatted_string = formatter.oops_id()

        expected_string = '<a href="%s">%s</a>' % (
            config.launchpad.oops_root_url + oops_id, oops_id)

        self.assertEqual(
            expected_string, formatted_string,
            "Formatted string should be '%s', was '%s'" % (
                expected_string, formatted_string))


def test_suite():
    suite = unittest.TestSuite()
    suite.addTests(DocTestSuite())
    suite.addTests(unittest.TestLoader().loadTestsFromName(__name__))
    return suite
