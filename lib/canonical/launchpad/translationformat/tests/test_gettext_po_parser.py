# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

import unittest
import doctest

from canonical.launchpad.interfaces import (
    TranslationConstants, TranslationFormatInvalidInputError,
    TranslationFormatSyntaxError)
from canonical.launchpad.translationformat import gettext_po_parser
from canonical.launchpad.translationformat.gettext_po_parser import (
    PoParser, PoHeader)

DEFAULT_HEADER = '''
msgid ""
msgstr ""
"Content-Type: text/plain; charset=ASCII\\n"
'''

class POBasicTestCase(unittest.TestCase):

    def setUp(self):
        self.parser = PoParser()

    def testSingular(self):
        translation_file = self.parser.parse(
            '%smsgid "foo"\nmsgstr "bar"\n' % DEFAULT_HEADER)
        messages = translation_file.messages
        self.assertEqual(len(messages), 1, "incorrect number of messages")
        self.assertEqual(messages[0].msgid, "foo", "incorrect msgid")
        self.assertEqual(
            messages[0].translations[TranslationConstants.SINGULAR_FORM],
            "bar", "incorrect msgstr")
        assert 'fuzzy' not in messages[0].flags, "incorrect fuzziness"

    def testNoNewLine(self):
        # note, no trailing newline; this raises a warning
        translation_file = self.parser.parse(
            '%smsgid "foo"\nmsgstr "bar"' % DEFAULT_HEADER)
        messages = translation_file.messages
        self.assertEqual(messages[0].msgid, "foo", "incorrect msgid")
        self.assertEqual(
            messages[0].translations[TranslationConstants.SINGULAR_FORM],
            "bar", "incorrect translation")

    def testMissingQuote(self):
        try:
            self.parser.parse('%smsgid "foo"\nmsgstr "bar' % DEFAULT_HEADER)
        except TranslationFormatSyntaxError:
            pass
        else:
            self.fail("uncaught syntax error (missing quote)")

    def testBadNewline(self):
        try:
            self.parser.parse(
                '%smsgid "foo\n"\nmsgstr "bar"\n' % DEFAULT_HEADER)
        except TranslationFormatSyntaxError:
            pass
        else:
            self.fail("uncaught syntax error (misplaced newline)")

    def testBadBackslash(self):
        try:
            self.parser.parse(
                '%smsgid "foo\\"\nmsgstr "bar"\n' % DEFAULT_HEADER)
        except TranslationFormatSyntaxError:
            pass
        else:
            self.fail("uncaught syntax error (misplaced backslash)")

    def testMissingMsgstr(self):
        try:
            self.parser.parse('%smsgid "foo"\n' % DEFAULT_HEADER)
        except TranslationFormatSyntaxError:
            pass
        else:
            self.fail("uncaught syntax error (missing msgstr)")

    def testMissingMsgid1(self):
        try:
            self.parser.parse('%smsgid_plural "foos"\n' % DEFAULT_HEADER)
        except TranslationFormatSyntaxError:
            pass
        else:
            self.fail(
                "uncaught syntax error (missing msgid before msgid_plural)")

    def testFuzzy(self):
        translation_file = self.parser.parse(
            '%s#, fuzzy\nmsgid "foo"\nmsgstr "bar"\n' % DEFAULT_HEADER)
        messages = translation_file.messages
        assert 'fuzzy' in messages[0].flags, "missing fuzziness"

    def testComment(self):
        translation_file = self.parser.parse('''
            %s
            #. foo/bar.baz\n
            # cake not drugs\n
            msgid "a"\n
            msgstr "b"\n''' % DEFAULT_HEADER)
        messages = translation_file.messages
        self.assertEqual(messages[0].source_comment, "foo/bar.baz\n",
                "incorrect source comment")
        self.assertEqual(messages[0].comment, " cake not drugs\n",
                "incorrect comment text")
        assert 'fuzzy' not in messages[0].flags, "incorrect fuzziness"

    def testEscape(self):
        translation_file = self.parser.parse(
            '%smsgid "foo\\"bar\\nbaz\\\\xyzzy"\nmsgstr"z"\n' % (
                DEFAULT_HEADER))
        messages = translation_file.messages
        self.assertEqual(messages[0].msgid, 'foo"bar\nbaz\\xyzzy')

    # Lalo doesn't agree with this test
    # def badEscapeTest(self):
    #
    #     try:
    #         self.parser.parse('''msgid "foo\."\nmsgstr "bar"\n''')
    #     except TranslationFormatSyntaxError:
    #         pass
    #     else:
    #         self.fail("no exception on bad escape sequence")

    def testPlural(self):
        translation_file = self.parser.parse('''
            %s"Plural-Forms: nplurals=2; plural=foo;\\n"

            msgid "foo"
            msgid_plural "foos"
            msgstr[0] "bar"
            msgstr[1] "bars"''' % DEFAULT_HEADER)
        messages = translation_file.messages
        self.assertEqual(messages[0].msgid, "foo", "incorrect msgid")
        self.assertEqual(messages[0].msgid_plural, "foos",
            "incorrect msgid_plural")
        assert messages[0].translations, "missing translations."
        self.assertEqual(len(messages[0].translations), 2,
            "incorrect number of plural forms.")
        self.assertEqual(messages[0].translations[0], "bar",
            "incorrect plural form.")
        self.assertEqual(messages[0].translations[1], "bars",
            "incorrect plural form.")
        assert 'fuzzy' not in messages[0].flags, "incorrect fuzziness"

    def testObsolete(self):
        translation_file = self.parser.parse(
            '%s#, fuzzy\n#~ msgid "foo"\n#~ msgstr "bar"\n' % DEFAULT_HEADER)
        messages = translation_file.messages
        self.assertEqual(messages[0].msgid, "foo", "incorrect msgid")
        self.assertEqual(
            messages[0].translations[TranslationConstants.SINGULAR_FORM],
            "bar", "incorrect msgstr")
        assert messages[0].is_obsolete, "incorrect obsolescence"
        assert 'fuzzy' in messages[0].flags, "incorrect fuzziness"

    def testMultiLineObsolete(self):
        translation_file = self.parser.parse(
            '%s#~ msgid "foo"\n#~ msgstr ""\n#~ "bar"\n' % DEFAULT_HEADER)
        messages = translation_file.messages
        self.assertEqual(messages[0].msgid, "foo")
        self.assertEqual(
            messages[0].translations[TranslationConstants.SINGULAR_FORM],
            "bar")

    def testDuplicateMsgid(self):
        try:
            self.parser.parse('''
                %s
                msgid "foo"
                msgstr "bar1"

                msgid "foo"
                msgstr "bar2"''' % DEFAULT_HEADER)
        except TranslationFormatInvalidInputError:
            pass
        else:
            self.fail("no error when duplicate msgid encountered")

    def testSquareBracketAndPlural(self):
        try:
            self.parser.parse('''
                %s
                msgid "foo %%d"
                msgid_plural "foos %%d"
                msgstr[0] "foo translated[%%d]"
                msgstr[1] "foos translated[%%d]"
                ''' % DEFAULT_HEADER)
        except ValueError:
            self.fail("The SquareBracketAndPlural test failed")

    def testUpdateHeader(self):
        translation_file = self.parser.parse(
            'msgid ""\nmsgstr "foo: bar\\n"\n')
        translation_file.header.number_plurals = 2
        translation_file.header.plural_form_expression = 'random()'
        lines = translation_file.header.getRawContent().split('\n')
        expected = [
            u'Project-Id-Version: PACKAGE VERSION',
            u'Report-Msgid-Bugs-To:  ',
            u'POT-Creation-Date: ...',
            u'PO-Revision-Date: ...',
            u'Last-Translator: FULL NAME <EMAIL@ADDRESS>',
            u'Language-Team: LANGUAGE <LL@li.org>',
            u'MIME-Version: 1.0',
            u'Content-Type: text/plain; charset=ASCII',
            u'Content-Transfer-Encoding: 8bit',
            u'X-Launchpad-Export-Date: ...',
            u'X-Generator: Launchpad (build Unknown)',
            u'foo: bar'
            ]
        for index in range(len(expected)):
            if lines[index].startswith('POT-Creation-Date'):
                self.assertEqual(
                    expected[index].startswith('POT-Creation-Date'), True)
            elif lines[index].startswith('PO-Revision-Date'):
                self.assertEqual(
                    expected[index].startswith('PO-Revision-Date'), True)
            elif lines[index].startswith('X-Launchpad-Export-Date'):
                self.assertEqual(
                    expected[index].startswith('X-Launchpad-Export-Date'),
                    True)
            else:
                self.assertEqual(lines[index], expected[index])

    def testMultipartString(self):
        """Test concatenated message strings on the same line.

        There seems to be nothing in the PO file format that forbids closing
        a string and re-opening it on the same line.  One wouldn't normally
        want to make use of this, but in bug #49599 two lines in a message had
        been accidentally concatenated at column 80, possibly because the
        author's editor happened to break the line there and the missing line
        feed became unnoticeable.

        Make sure this works.  The strings should be concatenated.  If there
        is any whitespace between the lines, it should be ignored.  This is
        how the ability to close and re-open strings is normally used: to
        break up long strings into multiple lines in the PO file.
        """
        foos = 9
        translation_file = self.parser.parse('''
            %s
            msgid "foo1"
            msgstr ""
            "bar"

            msgid "foo2"
            msgstr "b"
            "ar"

            msgid "foo3"
            msgstr "b""ar"

            msgid "foo4"
            msgstr "ba" "r"

            msgid "foo5"
            msgstr "b""a""r"

            msgid "foo6"
            msgstr "bar"""

            msgid "foo7"
            msgstr """bar"

            msgid "foo8"
            msgstr "" "bar" ""

            msgid "foo9"
            msgstr "" "" "bar" """"
            ''' % DEFAULT_HEADER)
        messages = translation_file.messages
        self.assertEqual(len(messages), foos, "incorrect number of messages")
        for n in range(1,foos):
            msgidn = "foo%d" % n
            self.assertEqual(messages[n-1].msgid, msgidn, "incorrect msgid")
            self.assertEqual(
                messages[n-1].translations[TranslationConstants.SINGULAR_FORM],
                "bar", "incorrect msgstr")

    def testGetLastTranslator(self):
        """Tests whether we extract last translator information correctly."""
        template_file = self.parser.parse(DEFAULT_HEADER)
        # When it's the default one in Gettext (FULL NAME <EMAIL@ADDRESS>),
        # used in templates, we get a tuple with None values.
        name, email = template_file.header.getLastTranslator()
        self.failUnless(name is None,
            "Didn't detect default Last Translator name")
        self.failUnless(email is None,
            "Didn't detect default Last Translator email")

        translation_file = self.parser.parse('''
            msgid ""
            msgstr ""
            "Last-Translator: Carlos Perello Marin <carlos@canonical.com>\\n"
            "Content-Type: text/plain; charset=ASCII\\n"
            ''')
        # Let's try with the translation file, it has valid Last Translator
        # information.
        name, email = translation_file.header.getLastTranslator()
        self.assertEqual(name, 'Carlos Perello Marin')
        self.assertEqual(email, 'carlos@canonical.com')


def test_suite():
    # Run gettext PO parser doc tests.
    dt_suite = doctest.DocTestSuite(gettext_po_parser)
    loader = unittest.TestLoader()
    ut_suite = loader.loadTestsFromTestCase(POBasicTestCase)
    return unittest.TestSuite((ut_suite, dt_suite))
