from zope.interface import Attribute, implements, Interface
from zope.app import zapi
from zope.app.form.browser.interfaces import ISimpleInputWidget
from zope.app.form.browser.itemswidgets import ItemsWidgetBase, SingleDataHelper
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.app.schema.vocabulary import IVocabularyFactory

from canonical.lp.z3batching import Batch
from canonical.lp.batching import BatchNavigator
from canonical.launchpad.vocabularies import IHugeVocabulary


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
        'List of tokens matching the current input'


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

    def _old_getFormValue(self):
        # Check to see if there is only one possible match. If so, use it.
        matches = self.matches()
        if len(matches) == 1:
            return matches[0].token

        # Otherwise, return the invalid value the user entered
        return super(SinglePopupWidget, self)._getFormValue()

    def _getFormInput(self):
        '''See zope.app.form.browser.widget.SimpleWidget'''
        matches = self.matches()
        if len(matches) == 1:
            return matches[0].token
        else:
            return super(SinglePopupWidget, self)._getFormInput()

    _matches = None
    def matches(self):
        '''Return a list of matches (as ITokenizedTerm) to whatever the
           user currently has entered in the form.

        '''
        # Use a cached version if we have it to avoid repeating expensive
        # searches
        if self._matches is not None:
            return self._matches

        # Pull form value using the parent class to avoid loop
        formValue = super(SinglePopupWidget, self)._getFormInput()
        if not formValue:
            return []

        # Special case - if the entered value is valid, it is an object
        # rather than a string (I think this is a bug somewhere)
        if not isinstance(formValue, basestring):
            self._matches = [self.vocabulary.getTerm(formValue)]
            return self._matches

        # Cache and return the search
        self._matches = list(self.vocabulary.search(formValue))
        return self._matches

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
            '''vocabulary=%s&field=%s','''
            ''''500','400')'''
            ) % (self.context.vocabularyName, self.name)
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
        start = int(self.request.get('batch_start', 0))
        search_text = self.request.get('search', None)
        batch = Batch(
            list=self.vocabulary().search(search_text),
            start=start, size=self._batchsize)
        self.batch = BatchNavigator(batch=batch, request=self.request)
        return self.batch

    def hasMoreThanOnePage(self):
        """See ISinglePopupView"""
        return len(self.batch.batchPageURLs()) > 1

    def currentTokenizedBatch(self):
        """See ISinglePopupView"""
        vocabulary = self.vocabulary()
        return [vocabulary.toTerm(item) for item in self.batch.currentBatch()]

