# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['POMsgSet', 'DummyPOMsgSet']

import gettextpo

from zope.interface import implements, providedBy
from zope.event import notify
from sqlobject import (ForeignKey, IntCol, StringCol, BoolCol,
                       SQLMultipleJoin, SQLObjectNotFound)

from canonical.launchpad.event.sqlobjectevent import (SQLObjectCreatedEvent,
    SQLObjectModifiedEvent)
from canonical.database.sqlbase import (SQLBase, sqlvalues,
                                        flush_database_updates)
from canonical.lp.dbschema import (RosettaTranslationOrigin,
    TranslationValidationStatus)
from canonical.launchpad import helpers
from canonical.launchpad.interfaces import IPOMsgSet

from canonical.launchpad.webapp.snapshot import Snapshot

from canonical.launchpad.database.poselection import POSelection
from canonical.launchpad.database.posubmission import POSubmission
from canonical.launchpad.database.potranslation import POTranslation


def _get_pluralforms(pomsgset):
    if pomsgset.potmsgset.getPOMsgIDs().count() > 1:
        if pomsgset.pofile.language.pluralforms is not None:
            entries = pomsgset.pofile.language.pluralforms
        elif pomsgset.pofile.pluralforms is not None:
            entries = pomsgset.pofile.pluralforms
        else:
            # Don't know anything about plural forms for this
            # language, fallback to the most common case, 2
            entries = 2
    else:
        # It's a singular form
        entries = 1
    return entries

class DummyPOMsgSet:
    """Represents a POMsgSet where we do not yet actually HAVE a POMsgSet for
    that POFile and POTMsgSet.
    """
    implements(IPOMsgSet)

    def __init__(self, pofile, potmsgset):
        self.pofile = pofile
        self.potmsgset = potmsgset
        self.isfuzzy = False
        self.commenttext = None

    # XXX CarlosPerelloMarin 20060425: This should be a cachedproperty, but
    # tests fail, for more information take a look to bug #41268
    @property
    def pluralforms(self):
        """See IPOMsgSet."""
        return _get_pluralforms(self)

    @property
    def active_texts(self):
        """See IPOMsgSet."""
        return [None] * self.pluralforms

    def getSuggestedSubmissions(self, pluralform):
        """See IPOMsgSet."""
        return []

    def getCurrentSubmissions(self, pluralform):
        """See IPOMsgSet."""
        return []

    def getWikiSubmissions(self, pluralform):
        """See IPOMsgSet."""
        return []


class POMsgSet(SQLBase):
    implements(IPOMsgSet)

    _table = 'POMsgSet'

    sequence = IntCol(dbName='sequence', notNull=True)
    pofile = ForeignKey(foreignKey='POFile', dbName='pofile', notNull=True)
    iscomplete = BoolCol(dbName='iscomplete', notNull=True, default=False)
    publishedcomplete = BoolCol(dbName='publishedcomplete', notNull=True,
        default=False)
    isfuzzy = BoolCol(dbName='isfuzzy', notNull=True, default=False)
    publishedfuzzy = BoolCol(dbName='publishedfuzzy', notNull=True,
        default=False)
    isupdated = BoolCol(notNull=True, default=False)
    commenttext = StringCol(dbName='commenttext', notNull=False, default=None)
    potmsgset = ForeignKey(foreignKey='POTMsgSet', dbName='potmsgset',
        notNull=True)
    obsolete = BoolCol(dbName='obsolete', notNull=True)

    selections = SQLMultipleJoin('POSelection', joinColumn='pomsgset',
        orderBy='pluralform')
    submissions = SQLMultipleJoin('POSubmission', joinColumn='pomsgset')

    # XXX CarlosPerelloMarin 20060425: This should be a cachedproperty, but
    # tests fail, for more information take a look to bug #41268
    @property
    def pluralforms(self):
        """See IPOMsgSet."""
        return _get_pluralforms(self) 

    @property
    def published_texts(self):
        pluralforms = self.pluralforms
        if pluralforms is None:
            raise RuntimeError(
                "Don't know the number of plural forms for this PO file!")
        results = list(POSubmission.select(
            "POSubmission.id = POSelection.publishedsubmission AND "
            "POSelection.pomsgset = %s" % sqlvalues(self.id),
            clauseTables=['POSelection'],
            orderBy='pluralform'))
        translations = []
        for form in range(pluralforms):
            if results and results[0].pluralform == form:
                translations.append(results.pop(0).potranslation.translation)
            else:
                translations.append(None)
        return translations

    @property
    def active_texts(self):
        pluralforms = self.pluralforms
        if pluralforms is None:
            raise RuntimeError(
                "Don't know the number of plural forms for this PO file!")
        results = list(POSubmission.select(
            """POSubmission.id = POSelection.activesubmission AND
               POSelection.pomsgset = %d""" % self.id,
            clauseTables=['POSelection'],
            orderBy='pluralform'))
        translations = []
        for form in range(pluralforms):
            if results and results[0].pluralform == form:
                translations.append(results.pop(0).potranslation.translation)
            else:
                translations.append(None)
        return translations

    def selection(self, pluralform):
        selection = POSelection.selectOne(
            "pomsgset = %s AND pluralform = %s" % sqlvalues(
                self.id, pluralform))
        return selection

    def getActiveSubmission(self, pluralform):
        """See IPOMsgSet."""
        return POSubmission.selectOne(
            """POSelection.pomsgset = %d AND
               POSelection.pluralform = %d AND
               POSelection.activesubmission = POSubmission.id
               """ % (self.id, pluralform),
               clauseTables=['POSelection'])

    def getPublishedSubmission(self, pluralform):
        """See IPOMsgSet."""
        return POSubmission.selectOne(
            """POSelection.pomsgset = %s AND
               POSelection.pluralform = %s AND
               POSelection.publishedsubmission = POSubmission.id
               """ % sqlvalues(self.id, pluralform),
               clauseTables=['POSelection'])

    def updateTranslationSet(self, person, new_translations, fuzzy,
        published, ignore_errors=False, force_edition_rights=False):
        """See IPOMsgSet."""
        # Is the person allowed to edit translations?
        is_editor = (force_edition_rights or
                     self.pofile.canEditTranslations(person))

        # First, check that the translations are correct.
        potmsgset = self.potmsgset
        msgids_text = [messageid.msgid
                       for messageid in potmsgset.getPOMsgIDs()]

        # By default all translations are correct.
        validation_status = TranslationValidationStatus.OK

        # Fix the trailing and leading whitespaces
        fixed_new_translations = {}
        for index, value in new_translations.items():
            fixed_new_translations[index] = potmsgset.applySanityFixes(value)

        # Validate the translation we got from the translation form
        # to know if gettext is unhappy with the input.
        try:
            helpers.validate_translation(msgids_text, fixed_new_translations,
                                         potmsgset.flags())
        except gettextpo.error:
            if fuzzy or ignore_errors:
                # The translations are stored anyway, but we set them as
                # broken.
                validation_status = TranslationValidationStatus.UNKNOWNERROR
            else:
                # Check to know if there is any translation.
                has_translations = False
                for key in fixed_new_translations.keys():
                    if fixed_new_translations[key] != '':
                        has_translations = True
                        break

                if has_translations:
                    # Partial translations cannot be stored unless the fuzzy
                    # flag is set, the exception is raised again and handled
                    # outside this method.
                    raise

        # keep track of whether or not this msgset is complete. We assume
        # it's complete and then flag it during the process if it is not
        complete = True
        new_translation_count = len(fixed_new_translations)
        if new_translation_count < self.pluralforms:
            # it's definitely not complete if it has too few translations
            complete = False
            # And we should reset the selection for the non updated plural forms.
            for pluralform in range(self.pluralforms)[new_translation_count:]:
                selection = self.selection(pluralform)
                if selection is None:
                    continue

                if published:
                    selection.publishedsubmission = None
                else:
                    selection.activesubmission = None

        # now loop through the translations and submit them one by one
        for index in fixed_new_translations.keys():
            newtran = fixed_new_translations[index]
            # replace any '' with None until we figure out
            # ResettingTranslations
            if newtran == '':
                newtran = None
            # see if this affects completeness
            if newtran is None:
                complete = False
            # make the new sighting or submission. note that this may not in
            # fact create a whole new submission
            submission = self._makeSubmission(
                person=person,
                text=newtran,
                pluralform=index,
                published=published,
                validation_status=validation_status,
                force_edition_rights=is_editor)

            # Flush the database cache
            flush_database_updates()

        # We set the fuzzy flag first, and completeness flags as needed:
        if is_editor:
            if published:
                self.publishedfuzzy = fuzzy
                self.publishedcomplete = complete
                # Now is time to check if the fuzzy flag should be copied to
                # the web flag
                matches = 0
                for pluralform in range(self.pluralforms):
                    if (self.getActiveSubmission(pluralform) ==
                        self.getPublishedSubmission(pluralform)):
                        matches += 1
                if matches == self.pluralforms:
                    # The active submission is exactly the same as the
                    # published one, so the fuzzy and complete flags should be
                    # also the same.
                    self.isfuzzy = self.publishedfuzzy
                    self.iscomplete = self.publishedcomplete
            else:
                self.isfuzzy = fuzzy
                self.iscomplete = complete

        # update the pomsgset flags
        self.updateFlags()

    def _makeSubmission(self, person, text, pluralform, published,
            validation_status=TranslationValidationStatus.UNKNOWN,
            force_edition_rights=False):
        """Record a translation submission by the given person.

        If "published" then this is a submission noticed in the published po
        file, otherwise it is a rosetta submission. It is assumed that any
        new submission will become the active translation (branding?), and
        if published is true then it will also become the published
        submission.

        This is THE KEY method in the whole of rosetta. It deals with the
        sighting or submission of a translation for a pomsgset and plural
        form, either online or in the published po file. It has to decide
        exactly what to do with that submission or sighting: whether to
        record it or ignore it, whether to make it the active or published
        translation, etc.

        It takes all the key information in the sighting/submission and
        records that in the db. It returns either the record of the
        submission, a POSubmission, or None if it decided to record
        nothing at all. Note that it may return a submission that was
        created previously, if it decides that there is not enough new
        information in this submission to justify recording it.

        The "published" field indicates whether or not this has come from
        the published po file. It should NOT be set for an arbitrary po
        file upload, it should ONLY be set if this is genuinely the
        published po file.

        The "validation_status" field is a value of
        TranslationValidationStatus that indicates the status of the
        translation.

        The "force_edition_rights" is a flag that 'forces' that this submition
        is handled as coming from an editor, no matter if it's really an
        editor or not
        """
        # Is the person allowed to edit translations?
        is_editor = (force_edition_rights or
                     self.pofile.canEditTranslations(person))

        # It makes no sense to have a "published" submission from someone
        # who is not an editor, so let's sanity check that first
        if published and not is_editor:
            raise AssertionError(
                'published translations are ALWAYS from an editor')

        # first we must deal with the situation where someone has submitted
        # a NULL translation. This only affects the published or active data
        # set, there is no crossover. So, for example, if upstream loses a
        # translation, we do not remove it from the rosetta active set.

        # we should also be certain that we don't get an empty string. that
        # should be None by this stage
        assert text != '', 'Empty string received, should be None'

        # Now get hold of any existing translation selection
        selection = self.selection(pluralform)

        # submitting an empty (None) translation gets rid of the published
        # or active selection for that translation. But a null published
        # translation does not remove the active submission.
        if text is None and selection is not None:
            # Remove the existing active/published selection
            # XXX sabdfl now we have no record of WHO made the translation
            # null, if it was not null previously. This needs to be
            # addressed in ResettingTranslations. 27/05/05
            if published:
                selection.publishedsubmission = None
            elif (is_editor and
                  validation_status == TranslationValidationStatus.OK):
                # activesubmission is updated only if the translation is
                # valid and it's an editor.
                selection.activesubmission = None

        # If nothing was submitted, return None
        if text is None:
            # make a note that the translation is not complete
            if published:
                self.publishedcomplete = False
            else:
                if is_editor:
                    self.iscomplete = False
            # we return because there is nothing further to do. Perhaps when
            # ResettingTranslations is implemented we will continue to
            # record the submission of the NULL translation.
            return None

        # Find or create a POTranslation for the specified text
        try:
            translation = POTranslation.byTranslation(text)
        except SQLObjectNotFound:
            translation = POTranslation(translation=text)

        # create the selection if there wasn't one
        if selection is None:
            selection = POSelection(
                pomsgsetID=self.id,
                pluralform=pluralform)

        # find or create the relevant submission. We always create a
        # translation submission, unless this translation is already active
        # (or published in the case of one coming in from a po file).

        # start by trying to see if the existing one is active or if
        # needed, published. If so, we can return, because the db already
        # reflects this selection in all the right ways and does not need to
        # be updated. Note that this will result in a submission for a new
        # person ("Joe") returning a POSubmission created in the name of
        # someone else, the person who first made this translation the
        # active / published one.

        # test if we are working with the published pofile, and if this
        # translation is already published
        if published and selection.publishedsubmission is not None:
            if selection.publishedsubmission.potranslation == translation:
                # Sets the validation status to the current status.
                # We do it always so the changes in our validation code will
                # apply automatically.
                selection.publishedsubmission.validationstatus = \
                    validation_status

                # return the existing submission that made this translation
                # the published one in the db
                return selection.publishedsubmission
        # if we are working with the active submission, see if the selection
        # of this translation is already active
        if not published and selection.activesubmission:
            if selection.activesubmission.potranslation == translation:
                # Sets the validation status to the current status.
                # If our validation code has been improved since the last
                # import we might detect new errors in previously validated
                # strings, so we always do this, regardless of the status in
                # the database.
                selection.activesubmission.validationstatus = \
                    validation_status
                # and return the active submission
                return selection.activesubmission

        # let's make a record of whether this translation was published
        # complete, was actively complete, and was an updated one

        # get the right origin for this translation submission
        if published:
            origin = RosettaTranslationOrigin.SCM
        else:
            origin = RosettaTranslationOrigin.ROSETTAWEB

        # and create the submission
        submission = POSubmission(
            pomsgsetID=self.id,
            pluralform=pluralform,
            potranslationID=translation.id,
            origin=origin,
            personID=person.id,
            validationstatus=validation_status)

        notify(SQLObjectCreatedEvent(submission))

        # Store the object status before the changes.
        object_before_modification = Snapshot(selection,
            providing=providedBy(selection))


        # next, we need to update the existing active and possibly also
        # published selections
        if published:
            selection.publishedsubmission = submission
        if is_editor and validation_status == TranslationValidationStatus.OK:
            # activesubmission is updated only if the translation is valid and
            # it's an editor.
            selection.activesubmission = submission

            # Same with the latestsubmission field.
            self.pofile.latestsubmission = submission

        # List of fields that would be updated.
        fields = ['publishedsubmission', 'activesubmission']

        notify(SQLObjectModifiedEvent(
            selection, object_before_modification, fields))

        # return the submission we have just made
        return submission

    def updateFlags(self):
        """See IPOMsgSet."""
        # make sure we are working with the very latest data
        flush_database_updates()

        # we only want to calculate the number of plural forms expected for
        # this pomsgset once
        pluralforms = self.pluralforms

        # calculate the number of published plural forms
        published_count = POSelection.select("""
            POSelection.pomsgset = %s AND
            POSelection.publishedsubmission IS NOT NULL AND
            POSelection.pluralform < %s
            """ % sqlvalues(self.id, pluralforms)).count()
        if published_count == pluralforms:
             self.publishedcomplete = True
        else:
             self.publishedcomplete = False

        if published_count == 0:
            # If we don't have translations, this entry cannot be fuzzy.
            self.publishedfuzzy = False

        # calculate the number of active plural forms
        active_count = POSelection.select("""
            POSelection.pomsgset = %s AND
            POSelection.activesubmission IS NOT NULL AND
            POSelection.pluralform < %s
            """ % sqlvalues(self.id, pluralforms)).count()
        if active_count == pluralforms:
            self.iscomplete = True
        else:
            self.iscomplete = False

        if active_count == 0:
            # If we don't have translations, this entry cannot be fuzzy.
            self.isfuzzy = False

        flush_database_updates()

        # Let's see if we got updates from Rosetta
        updated = POMsgSet.select("""
            POMsgSet.id = %s AND
            POMsgSet.isfuzzy = FALSE AND
            POMsgSet.publishedfuzzy = FALSE AND
            POMsgSet.iscomplete = TRUE AND
            POMsgSet.publishedcomplete = TRUE AND
            POSelection.pomsgset = POMsgSet.id AND
            POSelection.pluralform < %s AND
            ActiveSubmission.id = POSelection.activesubmission AND
            PublishedSubmission.id = POSelection.publishedsubmission AND
            ActiveSubmission.datecreated > PublishedSubmission.datecreated
            """ % sqlvalues(self.id, pluralforms),
            clauseTables=['POSelection',
                          'POSubmission AS ActiveSubmission',
                          'POSubmission AS PublishedSubmission']).count()
        if updated:
            # We found rows that change from what we got from upstream.
            self.isupdated = True
        else:
            # We have the same information as upstream gave us.
            self.isupdated = False

        flush_database_updates()

    def getWikiSubmissions(self, pluralform):
        """See IPOMsgSet."""
        posubmission_ids = self._connection.queryAll('''
            SELECT DISTINCT POSubmission.id
            FROM POSubmission
                JOIN POMsgSet ON (POSubmission.pomsgset = POMsgSet.id AND
                                  POMsgSet.isfuzzy = FALSE)
                JOIN POFile ON (POMsgSet.pofile = POFile.id AND
                                POFile.language = %s)
                JOIN POTMsgSet ON (POMsgSet.potmsgset = POTMsgSet.id AND
                                   POTMsgSet.primemsgid = %s)
            WHERE
                POSubmission.pluralform = %s
            ''' % sqlvalues(
                self.pofile.language.id, self.potmsgset.primemsgid_ID,
                pluralform))

        active_submission = self.getActiveSubmission(pluralform)

        if (active_submission is not None and
            active_submission.potranslation is not None):
            # We look for all the IPOSubmissions with the same translation.
            same_translation = POSubmission.select(
                "POSubmission.potranslation = %s" %
                    sqlvalues(active_submission.potranslation.id))

            # Remove it so we don't show as suggestion something that we
            # already have as active.
            for posubmission_id in same_translation:
                if posubmission_id in posubmission_ids:
                    posubmission_ids.remove(posubmission_id)

        if len(posubmission_ids) > 0:
            ids = [str(L[0]) for L in posubmission_ids]
            return POSubmission.select(
                'POSubmission.id IN (%s)' % ', '.join(ids),
                orderBy='-datecreated')
        else:
            return []

    def getSuggestedSubmissions(self, pluralform):
        """See IPOMsgSet."""
        selection = self.selection(pluralform)
        active = None
        if selection is not None and selection.activesubmission is not None:
            active = selection.activesubmission
        query = '''pomsgset = %s AND
                   pluralform = %s''' % sqlvalues(self.id, pluralform)
        if active is not None:
            # Don't show suggestions older than the current one.
            query += ''' AND datecreated > %s
                    ''' % sqlvalues(active.datecreated)
        return POSubmission.select(query, orderBy=['-datecreated'])

    def getCurrentSubmissions(self, pluralform):
        """See IPOMsgSet."""
        posubmission_ids = self.potmsgset.getCurrentSubmissionsIDs(
            self.pofile.language, pluralform)
        active = self.getActiveSubmission(pluralform)

        if active is not None and active.id in posubmission_ids:
            posubmission_ids.remove(active.id)

        if len(posubmission_ids) > 0:
            ids = [str(L[0]) for L in posubmission_ids]
            return helpers.shortlist(POSubmission.select(
                'POSubmission.id IN (%s)' % ', '.join(ids),
                orderBy='-datecreated'))
        else:
            return []

