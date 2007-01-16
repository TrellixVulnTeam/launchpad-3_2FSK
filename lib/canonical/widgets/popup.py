# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Single selection widget using a popup to select one item from a huge number.
"""

__metaclass__ = type

from zope.interface import Attribute, implements, Interface
from zope.app import zapi
from zope.app.form.browser.interfaces import ISimpleInputWidget
from zope.app.form.browser.itemswidgets import ItemsWidgetBase, SingleDataHelper
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.app.schema.vocabulary import IVocabularyFactory

from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.vocabulary import IHugeVocabulary
from canonical.cachedproperty import cachedproperty


class ISinglePopupWidget(ISimpleInputWidget):
    # I chose to use onKeyPress because onChange only fires when focus
    # leaves the element, and that's very inconvenient.
    onKeyPress = Attribute('''Optional javascript code to be executed
                              as text in input is changed''')
    cssClass = Attribute('''CSS class to be assigned to the input widget''')
    style = Attribute('''CSS style to be applied to the input widget''')
    def formToken():
        'The token representing the value to display, possibly invalid'
    def popupHref():
        'The contents to go into the href tag used to popup the select window'
    def matches():
        """List of tokens matching the current input.

        An empty list should be returned if 'too many' results are found.
        """

class SinglePopupWidget(SingleDataHelper, ItemsWidgetBase):
    """Window popup widget for single item choices from a huge vocabulary.

    The huge vocabulary must be registered by name in the vocabulary registry.
    """
    implements(ISinglePopupWidget)

    # ZPT that renders our widget

    __call__ = ViewPageTemplateFile('templates/popup.pt')

    default = ''
    displayWidth = 20
    displayMaxWidth = None

    onKeyPress = ''
    style = None
    cssClass = None

    @cachedproperty
    def matches(self):
        """Return a list of matches (as ITokenizedTerm) to whatever the
        user currently has entered in the form.
        """
        # Pull form value using the parent class to avoid loop
        formValue = super(SinglePopupWidget, self)._getFormInput()
        if not formValue:
            return []

        vocab = self.vocabulary
        # Special case - if the entered value is valid, it is an object
        # rather than a string (I think this is a bug somewhere)
        if not isinstance(formValue, basestring):
            return [vocab.getTerm(formValue)]

        # Search
        search_results = vocab.search(formValue)

        # If we have too many results to be useful in a list,
        # return an empty list.
        if search_results.count() > 25:
            return []

        # Or convert to a list
        return [vocab.toTerm(item) for item in vocab.search(formValue)]

    @cachedproperty
    def formToken(self):
        val = self._getFormValue()

        # We have a valid object - return the corresponding token
        if not isinstance(val, basestring):
            return self.vocabulary.getTerm(val).token

        # Just return the existing invalid token
        return val

    def popupHref(self):
        template = (
            '''javascript:'''
            '''popup_window('@@popup-window?'''
            '''vocabulary=%s&field=%s&search='''
            ''''+escape(document.getElementById('%s').value),'''
            ''''500','400')'''
            ) % (self.context.vocabularyName, self.name, self.name)
        if self.onKeyPress:
            # XXX: I suspect onkeypress() here is non-standard, but it
            # works for me, and enough researching for tonight. It may
            # be better to use dispatchEvent or a compatibility function
            # -- kiko, 2005-09-27
            template += ("; document.getElementById('%s').onkeypress()" %
                         self.name)
        return template


class ISinglePopupView(Interface):

    batch = Attribute('The BatchNavigator of the current results to display')

    def title():
        """Title to use on the popup page"""

    def vocabulary():
        """Return the IHugeVocabulary to display in the popup window"""

    def search():
        """Return the BatchNavigator of the current results to display"""

    def hasMoreThanOnePage(self):
        """Return True if there's more than one page with results."""

    def currentTokenizedBatch(self):
        """Return the ITokenizedTerms for the current batch."""


class SinglePopupView(object):
    implements(ISinglePopupView)

    _batchsize = 15
    batch = None

    def title(self):
        """See ISinglePopupView"""
        return self.vocabulary().displayname

    def vocabulary(self):
        """See ISinglePopupView"""
        factory = zapi.getUtility(IVocabularyFactory,
            self.request.form['vocabulary'])
        vocabulary = factory(self.context)
        assert IHugeVocabulary.providedBy(vocabulary), (
            'Invalid vocabulary %s' % self.request.form['vocabulary'])
        return vocabulary

    def search(self):
        """See ISinglePopupView"""
        search_text = self.request.get('search', None)
        self.batch = BatchNavigator(self.vocabulary().search(search_text),
                                    self.request, size=self._batchsize)
        return self.batch

    def hasMoreThanOnePage(self):
        """See ISinglePopupView"""
        return len(self.batch.batchPageURLs()) > 1

    def currentTokenizedBatch(self):
        """See ISinglePopupView"""
        vocabulary = self.vocabulary()
        return [vocabulary.toTerm(item) for item in self.batch.currentBatch()]

