# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Browser code for PO files."""

__metaclass__ = type

__all__ = ['POFileView', 'ExportCompatibilityView', 'POExportView']

import popen2
import os
import gettextpo
import urllib
from datetime import datetime

from zope.component import getUtility
from zope.publisher.browser import FileUpload
from zope.exceptions import NotFoundError

from canonical.lp.dbschema import RosettaFileFormat
from canonical.launchpad.interfaces import (ILaunchBag, ILanguageSet,
    RawFileAttachFailed, IPOExportRequestSet)
from canonical.launchpad.components.poparser import POHeader
from canonical.launchpad import helpers
from canonical.launchpad.browser.pomsgset import POMsgSetView
#from canonical.launchpad.browser.potemplate import BaseExportView

class BaseExportView:
    """Base class for PO export views."""

    def formats(self):
        """Return a list of formats available for translation exports."""

        class BrowserFormat:
            def __init__(self, title, value):
                self.title = title
                self.value = value

        formats = [
            RosettaFileFormat.PO,
            RosettaFileFormat.MO,
        ]

        for format in formats:
            yield BrowserFormat(format.title, format.name)


class POFileView:

    DEFAULT_COUNT = 10
    MAX_COUNT = 100
    DEFAULT_SHOW = 'all'

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.user = getUtility(ILaunchBag).user
        self.form = self.request.form
        self.language_name = self.context.language.englishname
        self.status_message = None
        self.header = POHeader(msgstr=context.header)
        self.URL = '%s/+translate' % self.context.language.code
        self.header.finish()
        self._table_index_value = 0
        self.pluralFormCounts = None
        self.alerts = []
        potemplate = context.potemplate
        self.is_editor = context.canEditTranslations(self.user)
        self.second_lang_pofile = None
        self.second_lang_code = self.form.get('alt', None)
        if self.second_lang_code:
            self.second_lang_pofile = potemplate.queryPOFileByLang(self.second_lang_code)
        self.submitted = False
        self.errorcount = 0


        # Get pagination information.
        self.offset = 0
        try:
            self.offset = int(self.form.get('offset', 0))
        except (TypeError, ValueError):
            # The value is not an integer, stick with 0
            pass

        self.count = self.DEFAULT_COUNT
        try:
            self.count = int(self.form.get('count', self.DEFAULT_COUNT))
        except (TypeError, ValueError):
            # It's not an integer, stick with DEFAULT_COUNT
            pass

        # Never show more than self.MAX_COUNT items in a form.
        if self.count > self.MAX_COUNT:
            self.count = self.MAX_COUNT

        # Get message display settings.
        self.show = self.form.get('show')

        if self.show not in ('translated', 'untranslated', 'all'):
            self.show = self.DEFAULT_SHOW

    def lang_selector(self):
        second_lang_code = self.second_lang_code
        all_languages = getUtility(ILanguageSet)
        html = '<select name="alt" title="Make suggestions from...">\n<option value=""'
        if self.second_lang_pofile is None:
            html += ' selected="yes"'
        html += '></option>\n'
        for lang in all_languages:
            html += '<option value="' + lang.code + '"'
            if second_lang_code == lang.code:
                html += ' selected=""'
            html += '>' + lang.englishname + '</option>\n'
        html += '</select>\n'
        return html

    def computeLastOffset(self):
        """Return higher integer multiple of self.count and less than length.

        It's used to calculate the self.offset to reference last page of the
        translation form.
        """
        length = len(self.context.potemplate)
        if length % self.count == 0:
            return length - self.count
        else:
            return length - (length % self.count)

    def pluralFormExpression(self):
        plural = self.header['Plural-Forms']
        return plural.split(';', 1)[1].split('=',1)[1].split(';', 1)[0].strip()

    def untranslated(self):
        return self.context.untranslatedCount()

    def has_translators(self):
        """We need to have this to tell us if there are any translators."""
        for translator in self.context.translators:
            return True
        return False

    def submitForm(self):
        """Called from the page template to do any processing needed if a form
        was submitted with the request."""

        if self.request.method == 'POST':
            if 'UPLOAD' in self.request.form:
                self.upload()
            elif "EDIT" in self.request.form:
                self.edit()

    def upload(self):
        """Handle a form submission to change the contents of the pofile."""

        file = self.form['file']

        if not isinstance(file, FileUpload):
            if file == '':
                self.status_message = 'Please, select a file to upload.'
            else:
                # XXX: Carlos Perello Marin 2004/12/30
                # Epiphany seems to have an aleatory bug with upload forms (or
                # perhaps it's launchpad because I never had problems with
                # bugzilla). The fact is that some uploads don't work and we
                # get a unicode object instead of a file-like object in
                # "file". We show an error if we see that behaviour. For more
                # info, look at bug #116.
                self.status_message = (
                    'There was an unknown error in uploading your file.')
            return

        filename = file.filename

        if not filename.endswith('.po'):
            self.status_message = (
                'The file you uploaded was not recognised as a file that '
                'can be imported.')
            return

        # We only set the 'published' flag if the upload is marked as an
        # upstream upload.
        if self.form.get('upload_type') == 'upstream':
            published = True
        else:
            published = False

        pofile = file.read()
        try:
            self.context.attachRawFileData(pofile, published, self.user)
            self.status_message = (
                'Thank you for your upload. The translation content will'
                ' appear in Rosetta in a few minutes.')
        except RawFileAttachFailed, error:
            # We had a problem while uploading it.
            self.status_message = (
                'There was a problem uploading the file: %s.' % error)

    def edit(self):
        self.header['Plural-Forms'] = 'nplurals=%s; plural=%s;' % (
            self.request.form['pluralforms'],
            self.request.form['expression'])
        self.context.header = self.header.msgstr.encode('utf-8')
        self.context.pluralforms = int(self.request.form['pluralforms'])

        self.status_message = "Updated on %s" % datetime.utcnow()

    def completeness(self):
        return '%.0f%%' % self.context.translatedPercentage()

    def processTranslations(self):
        """Process the translation form."""
        # This sets up the following instance variables:
        #
        #  pluralFormCounts:
        #    Number of plural forms.
        #  lacksPluralFormInformation:
        #    If the translation form needs plural form information.
        assert self.user is not None, 'This view is for logged-in users only.'

        form = self.request.form

        # Submit any translations.
        submitted = self.submitTranslations()

        # Get plural form information.
        #
        # For each language:
        #
        # - If there exists a PO file for that language, and it has plural
        #   form information, use the plural form information from that PO
        #   file.
        #
        # - Otherwise, if there is general plural form information for that
        #   language in the database, use that.
        #
        # - Otherwise, we don't have any plural form information for that
        #   language.
        #
        all_languages = getUtility(ILanguageSet)
        pofile = self.context
        potemplate = pofile.potemplate
        code = pofile.language.code

        # Prepare plural form information.
        if potemplate.hasPluralMessage:
            # The template has plural forms.
            if pofile.pluralforms is None:
                # We get the default information for the current language if
                # the PO file does not have it.
                self.pluralFormCounts = all_languages[code].pluralforms
            else:
                self.pluralFormCounts = pofile.pluralforms

            self.lacksPluralFormInformation = self.pluralFormCounts is None

        # Get the message sets.
        if submitted:
            self.submitted = True

        if self.errorcount > 0:
            # there was an error, so we will re-show the existing
            # messagesets, with error messages for correction.
            self.messageSets = [
                POMsgSetView(message_set['pot_set'], code,
                             self.pluralFormCounts,
                             message_set['translations'],
                             message_set['fuzzy'],
                             message_set['error'],
                             self.second_lang_pofile)
                for message_set in submitted.values()
                if message_set['error'] is not None]
        else:
            # get the next set of message sets
            # if there were submitted message, and no error, we want to
            # increase the offset by count first
            if self.submitted:
                self.offset = self.getNextOffset()

            # setup the slice so we know which translations we are
            # interested in
            slice_arg = slice(self.offset, self.offset+self.count)

            # The set of message sets we get is based on the selection of kind
            # of strings we have in our form.
            if self.show == 'all':
                filtered_potmsgsets = \
                    potemplate.getPOTMsgSets(slice=slice_arg)
            elif self.show == 'translated':
                filtered_potmsgsets = \
                    pofile.getPOTMsgSetTranslated(slice=slice_arg)
            elif self.show == 'need-review':
                filtered_potmsgsets = \
                    pofile.getPOTMsgSetFuzzy(slice=slice_arg)
            elif self.show == 'untranslated':
                filtered_potmsgsets = \
                    pofile.getPOTMsgSetUntranslated(slice=slice_arg)
            elif self.show == 'errors':
                filtered_potmsgsets = \
                    pofile.getPOTMsgSetWithErrors(slice=slice_arg)
            else:
                raise AssertionError('show = "%s"' % self.show)

            self.messageSets = [
                POMsgSetView(potmsgset, code, self.pluralFormCounts,
                    second_lang_pofile=self.second_lang_pofile)
                for potmsgset in filtered_potmsgsets]

            # commented out in support of the theory that we should be able
            # to render directly, without resubmission
            #if 'SUBMIT' in form:
            #    # We did a submit without errors, we should redirect to next
            #    # page.
            #    self.request.response.redirect(self.createURL(offset=self.getNextOffset()))

    def makeTabIndex(self):
        """Return the tab index value to navigate the form."""
        self._table_index_value += 1
        return self._table_index_value

    def atBeginning(self):
        """Say if we are at the beginning of the form."""
        return self.offset == 0

    def atEnd(self):
        """Say if we are at the end of the form."""
        return self.offset + self.count >= len(self.context.potemplate)

    def onlyOneForm(self):
        """Say if we have all POTMsgSets in one form.

        That will only be true when we are atBeginning and atEnd at the same
        time.
        """
        return self.atBeginning() and self.atEnd()

    def createURL(self, count=None, show=None, offset=None):
        """Build the current URL based on the arguments."""
        parameters = {}

        # Parameters to copy from args or form.
        parameters = {'count':count, 'show':show, 'offset':offset,
            'alt':self.second_lang_code}

        # Update with current values from self
        if parameters['count'] is None:
            parameters['count'] = self.count

        if parameters['show'] is None:
            parameters['show'] = self.show

        if parameters['offset'] is None:
            parameters['offset'] = self.offset

        # Remove the arguments if are the same as the defaults or None
        if (parameters['show'] == self.DEFAULT_SHOW or
            parameters['show'] is None):
            del parameters['show']

        if parameters['offset'] == 0 or parameters['offset'] is None:
            del parameters['offset']

        if (parameters['count'] == self.DEFAULT_COUNT or
            parameters['count'] is None):
            del parameters['count']

        if parameters['alt'] is None:
            del parameters['alt']

        # add the alternative language parameter
        if self.second_lang_code:
            parameters['alt'] = self.second_lang_code
        
        # now build the query
        if parameters:
            keys = parameters.keys()
            keys.sort()
            query_portion = urllib.urlencode(parameters)
            return '%s?%s' % (self.request.getURL(), query_portion)
        else:
            return self.request.getURL()

    def beginningURL(self):
        """Return the URL to be at the beginning of the translation form."""
        return self.createURL(offset=0)

    def endURL(self):
        """Return the URL to be at the end of the translation form."""
        return self.createURL(offset=self.computeLastOffset())

    def previousURL(self):
        """Return the URL to get previous self.count number of message sets.
        """
        return self.createURL(offset=max(self.offset-self.count, 0))

    def nextURL(self):
        """Return the URL to get next self.count number of message sets."""
        pot_length = len(self.context.potemplate)
        if self.offset + self.count >= pot_length:
            raise IndexError('Only have %d messages, requested %d' %
                                (pot_length, self.offset + self.count))
        return self.createURL(offset=(self.offset + self.count))

    def getFirstMessageShown(self):
        """Return the first POTMsgSet number shown in the form."""
        return self.offset + 1

    def getLastMessageShown(self):
        """Return the last POTMsgSet number shown in the form."""
        return min(len(self.context.potemplate), self.offset + self.count)

    def getNextOffset(self):
        """Return the offset needed to jump current set of messages."""
        return self.offset + self.count

    def submitTranslations(self):
        """Handle a form submission for the translation form.

        The form contains translations, some of which will be unchanged, some
        of which will be modified versions of old translations and some of
        which will be new. Returns a dictionary mapping sequence numbers to
        submitted message sets, where each message set will have information
        on any validation errors it has.
        """
        if not "SUBMIT" in self.request.form:
            return {}

        messageSets = helpers.parse_translation_form(self.request.form)
        bad_translations = []

        pofile = self.context
        potemplate = pofile.potemplate

        # Put the translations in the database.

        for messageSet in messageSets.values():
            pot_set = potemplate.getPOTMsgSetByID(messageSet['msgid'])
            if pot_set is None:
                # This should only happen if someone tries to POST his own
                # form instead of ours, and he uses a POTMsgSet id that does
                # not exist for this POTemplate.
                raise RuntimeError(
                    "Got translation for POTMsgID %d which is not in the"
                    " template." % messageSet['msgid'])

            msgid_text = pot_set.primemsgid_.msgid

            messageSet['pot_set'] = pot_set
            messageSet['error'] = None
            new_translations = messageSet['translations']
            fuzzy = messageSet['fuzzy']

            has_translations = False
            for new_translation_key in new_translations.keys():
                if new_translations[new_translation_key] != '':
                    has_translations = True
                    break

            if has_translations and not fuzzy:
                # The submit has translations to validate and are not set as
                # fuzzy.

                msgids_text = [messageid.msgid
                               for messageid in list(pot_set.messageIDs())]

                # Validate the translation we got from the translation form
                # to know if gettext is unhappy with the input.
                try:
                    helpers.validate_translation(msgids_text,
                                                 new_translations,
                                                 pot_set.flags())
                except gettextpo.error, e:
                    # Save the error message gettext gave us to show it to the
                    # user and jump to the next entry so this messageSet is
                    # not stored into the database.
                    messageSet['error'] = str(e)
                    self.errorcount += 1
                    continue

            # Get hold of an appropriate message set in the PO file,
            # creating it if necessary.
            try:
                po_set = pofile[msgid_text]
            except NotFoundError:
                po_set = pofile.createMessageSetFromText(msgid_text)

            try:
                po_set.updateTranslationSet(
                    person=self.user,
                    new_translations=new_translations,
                    fuzzy=fuzzy,
                    published=False,
                    is_editor=self.is_editor)
            except gettextpo.error, e:
                # Save the error message gettext gave us to show it to the
                # user.
                messageSet['error'] = str(e)
                number_errors += 1

        # update the statistis for this po file
        pofile.updateStatistics()

        return messageSets

class ExportCompatibilityView:
    """View class for old export URLs which redirects to new export URLs."""

    def __call__(self):
        return self.request.response.redirect('+export')

class POExportView(BaseExportView):
    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.user = getUtility(ILaunchBag).user
        self.formProcessed = False

    def processForm(self):
        if self.request.method != 'POST':
            return

        format_name = self.request.form.get('format')

        try:
            format = RosettaFileFormat.items[format_name]
        except KeyError:
            raise RuntimeError("Unsupported format")

        request_set = getUtility(IPOExportRequestSet)
        request_set.addRequest(
            self.user, pofiles=[self.context], format=format)
        self.formProcessed = True

