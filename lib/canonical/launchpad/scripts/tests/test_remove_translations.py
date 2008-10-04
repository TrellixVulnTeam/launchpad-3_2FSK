#! /usr/bin/python2.4
# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Test `remove_translations` and the `RemoveTranslations` script."""

__metaclass__ = type

from datetime import datetime
from optparse import OptionParser, OptionValueError
from pytz import timezone
from unittest import TestLoader

from zope.component import getUtility

from storm.store import Store

from canonical.launchpad.ftests import sync
from canonical.launchpad.database.translationrelicensingagreement import (
    TranslationRelicensingAgreement)
from canonical.launchpad.interfaces import (
    IPersonSet, RosettaTranslationOrigin)
from canonical.launchpad.scripts.base import LaunchpadScriptFailure
from canonical.launchpad.scripts.remove_translations import (
    RemoveTranslations, remove_translations)
from canonical.launchpad.testing import LaunchpadObjectFactory, TestCase
from canonical.testing import LaunchpadZopelessLayer


def make_script(args=None):
    """Create a `RemoveTranslations` script with given options."""
    if isinstance(args, basestring):
        args = [args]
    return RemoveTranslations('remove-translations-test', test_args=args)


class TestRemoveTranslationsConstraints(TestCase):
    """Test safety net for translations removal options."""
    layer = LaunchpadZopelessLayer

    def _test_options(self, opts):
        """Get `_check_constraints_safety`'s answer for given options."""
        return make_script(opts)._check_constraints_safety()

    def disabled_test_RecklessRemoval(self):
        # The script will refuse to run if no specific person or id is
        # targeted.  Operator error is more likely than a use case for
        # casually deleting lots of loosely-specified translations.
        opts = [
            '--language=pa',
            '--not-language',
            '--is-current=False',
            '--is-imported=true',
            '--msgid=foo',
            '--origin=1',
            '--force',
            ]
        script = make_script(opts)
        self.assertRaises(LaunchpadScriptFailure, script.run)

        # The same removal will work if we add, say, a submitter id.
        opts.append('--submitter=8134719')
        make_script(opts).run()

    def test_RemoveBySubmitter(self):
        # Removing all translations by one submitter is allowed.
        approval, message = self._test_options('--submitter=1')
        self.assertTrue(approval)

    def test_RemoveByReviewer(self):
        # Removing all translations by one reviewer is allowed.
        approval, message = self._test_options('--reviewer=1')
        self.assertTrue(approval)

    def test_RemoveById(self):
        # Removing by ids is allowed.
        approval, message = self._test_options(['--id=1', '--id=2', '--id=3'])
        self.assertTrue(approval)

    def test_RemoveByPOFile(self):
        # Removing all translations for a template is not allowed by default.
        opts = ['--potemplate=1']
        approval, message = self._test_options(opts)
        self.assertFalse(approval)

        # The --force option overrides the safety check.
        opts.append('--force')
        approval, message = self._test_options(opts)
        self.assertIn("Safety override in effect", message)
        self.assertTrue(approval)

    def test_remove_unlicensed(self):
        # Can't just remove _all_ translations by people who rejected
        # the licensing agreement.
        approval, message = self._test_options(['--reject-license'])
        self.assertFalse(approval)

        # We can do that for the non-imported ones, however...
        approval, message = self._test_options([
            '--reject-license', '--is-imported=False'])

        self.assertTrue(approval)
        # ...though not for the imported ones.
        approval, message = self._test_options([
            '--reject-license', '--is-imported=True'])
        self.assertFalse(approval)

        # Similar for ones submitted directly in Launchpad.
        approval, message = self._test_options([
            '--reject-license', '--origin=ROSETTAWEB'])
        self.assertTrue(approval)
        approval, message = self._test_options([
            '--reject-license', '--origin=SCM'])
        self.assertFalse(approval)

        # We can bypass the check using --force.
        approval, message = self._test_options([
            '--reject-license', '--force'])
        self.assertTrue(approval)


class OptionChecker(OptionParser):
    """`OptionParser` that doesn't abort the whole program on error."""
    def error(self, msg):
        """See `OptionParser`.  Raises exception instead of exiting."""
        raise OptionValueError(msg)


def parse_opts(opts):
    """Simulate options being parsed by `LaunchpadScript`."""
    if isinstance(opts, basestring):
        opts = [opts]

    parser = OptionChecker()
    parser.add_options(RemoveTranslations.my_options)
    options, arguments = parser.parse_args(args=opts)
    return options


class TestRemoveTranslationsOptionsHandling(TestCase):
    """Test `RemoveTranslations`' options parsing and type checking."""
    layer = LaunchpadZopelessLayer

    def setUp(self):
        self.factory = LaunchpadObjectFactory()

    def test_WithNativeArgs(self):
        # Options can be passed as the string representations of the
        # types the script wants them in.
        options = parse_opts([
            '--submitter=1',
            '--reviewer=2',
            '--id=3',
            '--id=4',
            '--potemplate=5',
            '--language=te',
            '--not-language',
            '--is-current=True',
            '--is-imported=False',
            '--msgid=Hello',
            '--origin=1',
            '--force',
            ])
        self.assertEqual(options.submitter, 1)
        self.assertEqual(options.reviewer, 2)
        self.assertEqual(options.ids, [3, 4])
        self.assertEqual(options.potemplate, 5)
        self.assertEqual(options.language, 'te')
        self.assertEqual(options.not_language, True)
        self.assertEqual(options.is_current, True)
        self.assertEqual(options.is_imported, False)
        self.assertEqual(options.is_imported, False)
        self.assertEqual(options.origin, 1)
        self.assertEqual(options.force, True)

    def test_WithLookups(self):
        # The script can also look up some items from different
        # representations: person names, numbers or different case
        # settings for booleans, and translation origin identifiers.
        submitter = self.factory.makePerson()
        reviewer = self.factory.makePerson()

        options = parse_opts([
            '--submitter=%s' % submitter.name,
            '--reviewer=%s' % reviewer.name,
            '--is-current=0',
            '--is-imported=true',
            '--origin=SCM'
            ])
        self.assertEqual(options.submitter, submitter.id)
        self.assertEqual(options.reviewer, reviewer.id)
        self.assertEqual(options.is_current, False)
        self.assertEqual(options.is_imported, True)
        self.assertEqual(options.origin, RosettaTranslationOrigin.SCM.value)

    def test_BadBool(self):
        self.assertRaises(Exception, parse_opts, '--is-current=None')

    def test_UnknownPerson(self):
        self.assertRaises(
            Exception, parse_opts, '--reviewer=unknownnonexistentpersonbird')

    def test_UnknownOrigin(self):
        self.assertRaises(Exception, parse_opts, '--origin=GAGA')


class TestRemoveTranslations(TestCase):
    """Test `remove_translations`."""
    layer = LaunchpadZopelessLayer

    def setUp(self):
        # Acquire privileges to delete TranslationMessages.  That's not
        # something we normally do.  Actually we should test under
        # rosettaadmin, but that user does not have all the privileges
        # needed to set up this test.  A separate doctest
        # remove-translations-by.txt tests a realistic run of the
        # remove-translations-by.py script under the actual rosettaadmin
        # db user.
        self.layer.switchDbUser('postgres')

        # Set up a template with Dutch and German translations.  The
        # messages we set up here are invariant; they remain untouched
        # by deletions done in the test case.
        self.factory = LaunchpadObjectFactory()
        self.nl_pofile = self.factory.makePOFile('nl')
        self.potemplate = self.nl_pofile.potemplate
        self.de_pofile = self.factory.makePOFile(
            'de', potemplate=self.potemplate)

        self.nl_message, self.de_message = self._makeMessages(
            "This message is not to be deleted.",
            "Dit bericht mag niet worden verwijderd.",
            "Diese Nachricht soll nicht erloescht werden.")

        self.untranslated_message = self.factory.makePOTMsgSet(
            self.potemplate, 'This message is untranslated.')

        self._checkInvariant()

    def _setTranslation(self, potmsgset, pofile, text, submitter=None,
                        is_imported=False):
        """Set translation for potmsgset in pofile to text."""
        if submitter is None:
            submitter = self.potemplate.owner
        return potmsgset.updateTranslation(
            pofile, submitter, {0: text},
            is_imported=is_imported,
            lock_timestamp=datetime.now(timezone('UTC')))

    def _makeMessages(self, template_text, nl_text, de_text,
                      submitter=None, is_imported=False):
        """Create message, and translate it to Dutch & German."""
        message = self.factory.makePOTMsgSet(self.potemplate, template_text)
        owner = self.potemplate.owner
        new_nl_message = self._setTranslation(
            message, self.nl_pofile, nl_text, submitter=submitter,
            is_imported=is_imported)
        new_de_message = self._setTranslation(
            message, self.de_pofile, de_text, submitter=submitter,
            is_imported=is_imported)
        return new_nl_message, new_de_message

    def _getContents(self, pofile):
        return sorted(
            message.msgstr0.translation
            for message in pofile.translation_messages
            if message.msgstr0 is not None
            )

    def _checkInvariant(self):
        """Check that our translations are in their original state.

        Tests in this test case don't work in the usual way, by making
        changes and then testing for them.  Instead they make changes by
        creating new messages, and then using `remove_translations` to
        undo those changes.
        
        We see that a removal worked correctly by verifying that the
        invariant is restored.
        """
        # First make sure we're not reading out of cache.
        sync(self.nl_pofile)
        sync(self.de_pofile)

        self.assertEqual(
            self._getContents(self.nl_pofile),
            ["Dit bericht mag niet worden verwijderd."])
        self.assertEqual(
            self._getContents(self.de_pofile),
            ["Diese Nachricht soll nicht erloescht werden."])

    def _remove(self, **kwargs):
        """Front-end for `remove_translations`.  Flushes changes first."""
        Store.of(self.potemplate).flush()
        return remove_translations(**kwargs)

    def test_RemoveNone(self):
        # If no messages match the given constraints, nothing is
        # deleted.
        rowcount = self._remove(
            submitter=1, ids=[self.de_message.id], language_code='br')
        self.assertEqual(rowcount, 0)
        self._checkInvariant()

    def test_RemoveById(self):
        # We can remove messages by id.  Other messages are not
        # affected.
        new_nl_message1 = self._setTranslation(
            self.untranslated_message, self.nl_pofile, "A Dutch translation")
        new_nl_message2 = self._setTranslation(
            self.untranslated_message, self.nl_pofile, "Double Dutch")
        self.assertEqual(
            self._getContents(self.nl_pofile), [
                "A Dutch translation",
                "Dit bericht mag niet worden verwijderd.",
                "Double Dutch",
                ])

        rowcount = self._remove(ids=[new_nl_message1.id, new_nl_message2.id])

        self.assertEqual(rowcount, 2)
        self._checkInvariant()

    def test_RemoveBySubmitter(self):
        # Remove messages by submitter id.
        carlos = getUtility(IPersonSet).getByName('carlos')
        (new_nl_message, new_de_message) = self._makeMessages(
            "Submitted by Carlos", "Ingevoerd door Carlos",
            "Von Carlos eingefuehrt", submitter=carlos)

        # Ensure that at least one message's reviewer is not the same
        # as the submitter, so we know we're not accidentally matching
        # on reviewer instead.
        new_nl_message.reviewer = self.potemplate.owner

        rowcount = self._remove(submitter=carlos)

        self._checkInvariant()

    def test_RemoveByReviewer(self):
        # Remove messages by reviewer id.
        carlos = getUtility(IPersonSet).getByName('carlos')
        (new_nl_message, new_de_message) = self._makeMessages(
            "Submitted by Carlos", "Ingevoerd door Carlos",
            "Von Carlos eingefuehrt")
        new_nl_message.reviewer = carlos
        new_de_message.reviewer = carlos

        rowcount = self._remove(reviewer=carlos)

        self._checkInvariant()

    def test_RemoveByTemplate(self):
        # Remove messages by template.  Limit this deletion by ids as
        # well to avoid breaking the test invariant.  To show that the
        # template limitation really does add a limit on top of the ids
        # themselves, we also pass the id of another message in a
        # different template.  That message is not deleted.
        (new_nl_message, new_de_message) = self._makeMessages(
            "Foo", "Foe", "Fu")

        unrelated_nl_pofile = self.factory.makePOFile('nl')
        potmsgset = self.factory.makePOTMsgSet(
            unrelated_nl_pofile.potemplate, 'Foo')
        unrelated_nl_message = potmsgset.updateTranslation(
            unrelated_nl_pofile, unrelated_nl_pofile.potemplate.owner,
            {0: "Foe"}, is_imported=False,
            lock_timestamp=datetime.now(timezone('UTC')))

        ids = [new_nl_message.id, new_de_message.id, unrelated_nl_message.id]
        rowcount = self._remove(ids=ids, potemplate=self.potemplate.id)

        self._checkInvariant()
        self.assertEqual(self._getContents(unrelated_nl_pofile), ["Foe"])

    def test_RemoveByLanguage(self):
        # Remove messages by language.  Pass the ids of one Dutch
        # message and one German message, but specify Dutch as the
        # language to delete from; only the Dutch message is deleted.
        potmsgset = self.factory.makePOTMsgSet(self.potemplate, 'Bar')
        message = self._setTranslation(potmsgset, self.nl_pofile, 'Cafe')

        self._remove(ids=[message.id, self.de_message.id], language_code='nl')

        self._checkInvariant()

    def test_RemoveByNotLanguage(self):
        # Remove messages, but spare otherwise matching messages that
        # are in German.
        potmsgset = self.factory.makePOTMsgSet(self.potemplate, 'Hi')
        message = self._setTranslation(potmsgset, self.nl_pofile, 'Hoi')

        self._remove(
            ids=[message.id, self.de_message.id], language_code='de',
            not_language=True)

        self._checkInvariant()

    def test_RemoveCurrent(self):
        # Remove current messages, but not non-current messages.
        (new_nl_message, new_de_message) = self._makeMessages(
            "translate", "vertalen", "uebersetzen")
        self.nl_message.is_current = False

        ids = [self.nl_message.id, new_nl_message.id, new_de_message.id]
        self._remove(ids=ids, is_current=True)

        self.nl_message.is_current = True
        self._checkInvariant()

    def test_RemoveNotCurrent(self):
        # Remove current messages, but not non-current messages.
        (new_nl_message, new_de_message) = self._makeMessages(
            "write", "schrijven", "schreiben")
        new_nl_message.is_current = False
        new_de_message.is_current = False

        ids = [self.nl_message.id, new_nl_message.id, new_de_message.id]
        self._remove(ids=ids, is_current=False)

        self._checkInvariant()

    def test_RemoveImported(self):
        # Remove current messages, but not non-current messages.
        (new_nl_message, new_de_message) = self._makeMessages(
            "book", "boek", "Buch")
        new_nl_message.is_imported = True
        new_de_message.is_imported = True

        ids = [self.nl_message.id, new_nl_message.id, new_de_message.id]
        self._remove(ids=ids, is_imported=True)

        self._checkInvariant()

    def test_RemoveNotImported(self):
        # Remove current messages, but not non-current messages.
        (new_nl_message, new_de_message) = self._makeMessages(
            "helicopter", "helikopter", "Hubschauber")
        self.nl_message.is_imported = True

        ids = [self.nl_message.id, new_nl_message.id, new_de_message.id]
        self._remove(ids=ids, is_imported=False)

        self.nl_message.is_imported = False
        self._checkInvariant()

    def test_RemoveMsgId(self):
        # Remove translations by msgid_singular.
        (new_nl_message, new_de_message) = self._makeMessages(
            "save", "bewaren", "speichern")

        self._remove(msgid_singular="save")

        self._checkInvariant()

    def test_RemoveOrigin(self):
        # Remove translations by origin.
        self.assertEqual(
            self.nl_message.origin, RosettaTranslationOrigin.ROSETTAWEB)
        (new_nl_message, new_de_message) = self._makeMessages(
            "new", "nieuw", "neu", is_imported=True)
        self.assertEqual(new_nl_message.origin, RosettaTranslationOrigin.SCM)
        self.assertEqual(new_de_message.origin, RosettaTranslationOrigin.SCM)

        self._remove(
            potemplate=self.potemplate, origin=RosettaTranslationOrigin.SCM)

        self._checkInvariant()

    def test_remove_unlicensed(self):
        # Remove translations submitted by users who rejected the
        # licensing agreement.
        refusenik = self.factory.makePerson()
        TranslationRelicensingAgreement(
            person=refusenik, allow_relicensing=False)

        new_nl_message, new_de_message = self._makeMessages(
            "Don't download this song", "Niet delen", "Nicht teilen",
            submitter=refusenik)

        self._remove(reject_license=True)

        self._checkInvariant()

    def test_remove_unlicensed_none(self):
        # Removing translations whose submitters rejected our
        # translations license does not affect translations by those who
        # haven't answered the question yet.
        self._remove(reject_license=True)

        self._checkInvariant()

    def test_remove_unlicensed_when_licensed(self):
        # Removing translations whose submitters rejected our
        # translations license does not affect translations by those who
        # agreed to license.
        answer = TranslationRelicensingAgreement(
            person=self.nl_message.submitter, allow_relicensing=True)

        self._remove(reject_license=True)

        self._checkInvariant()

        answer.destroySelf()

    def test_remove_unlicensed_restriction(self):
        # When removing unlicensed translations, other restrictions
        # still apply.
        answer = TranslationRelicensingAgreement(
            person=self.nl_message.submitter, allow_relicensing=False)
        self.nl_message.is_imported = True
        self.de_message.is_imported = True

        self._remove(reject_license=True, is_imported=False)

        self._checkInvariant()

        answer.destroySelf()


class TestRemoveTranslationsUnmasking(TestCase):
    """Test that `remove_translations` "unmasks" imported messages.

    When a current, non-imported message is deleted, the deletion code
    checks whether there is also an imported translation.  If there was,
    it makes sense to make the imported message the current one (as it
    would have been if the deleted message had never been there in the
    first place).
    """
    layer = LaunchpadZopelessLayer

    def setUp(self):
        self.layer.switchDbUser('postgres')

        # Set up a template with a Laotian translation file.  There's
        # one message to be translated.
        factory = LaunchpadObjectFactory()
        self.pofile = factory.makePOFile('lo')
        potemplate = self.pofile.potemplate
        self.potmsgset = factory.makePOTMsgSet(potemplate, 'foo')

    def _setTranslation(self, text, is_imported=False):
        return self.potmsgset.updateTranslation(
            self.pofile, self.pofile.owner, {0: text},
            is_imported=is_imported,
            lock_timestamp=datetime.now(timezone('UTC')))

    def test_unmask_imported_message(self):
        # Basic use case: imported message is unmasked.
        imported = self._setTranslation('imported', is_imported=True)
        current = self._setTranslation('current', is_imported=False)
        self.assertFalse(imported.is_current)
        self.assertTrue(imported.is_imported)
        self.assertTrue(current.is_current)
        self.assertFalse(current.is_imported)
        Store.of(current).flush()

        remove_translations(ids=[current.id])

        sync(imported)
        self.assertTrue(imported.is_imported)
        self.assertTrue(imported.is_current)

        # Clean up.
        remove_translations(ids=[imported.id])

    def test_unmask_right_message(self):
        # Unmasking picks the right message, and doesn't try to violate
        # the unique constraint on is_imported.
        inactive = self._setTranslation('inactive')
        imported = self._setTranslation('imported', is_imported=True)
        current = self._setTranslation('current', is_imported=False)
        self.assertFalse(inactive.is_current)
        self.assertFalse(inactive.is_imported)
        Store.of(current).flush()

        remove_translations(ids=[current.id])

        sync(imported)
        sync(inactive)
        self.assertTrue(imported.is_current)
        self.assertFalse(inactive.is_current)

        # Clean up.
        remove_translations(ids=[imported.id, inactive.id])


def test_suite():
    # Removing TranslationMessage rows requires special database privileges.
    return TestLoader().loadTestsFromName(__name__)
