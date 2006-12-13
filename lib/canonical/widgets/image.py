
from zope.app.form import CustomWidgetFactory
from zope.app.form.browser.widget import SimpleInputWidget
from zope.app.form.browser import FileWidget
from zope.app.form.interfaces import ValidationError, WidgetInputError
from zope.formlib import form
from zope.schema import Bytes, Choice
from zope.schema.vocabulary import SimpleVocabulary, SimpleTerm

from canonical.launchpad.interfaces.librarian import ILibraryFileAlias
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.widgets.itemswidgets import LaunchpadRadioWidget
from canonical.launchpad import _


class LaunchpadFileWidget(FileWidget):
    """A FileWidget which doesn't enclose itself in <div> tags."""

    def _div(self, cssClass, contents, **kw):
        return contents


class ImageUploadWidget(SimpleInputWidget):
    """Widget for uploading an image or deleting an existing one."""

    def __init__(self, context, request):
        SimpleInputWidget.__init__(self, context, request)
        fields = form.Fields(
            Choice(__name__='action', source=self._getActionsVocabulary(),
                   title=_('Action')),
            Bytes(__name__='image', title=_('Image')))
        fields['action'].custom_widget = CustomWidgetFactory(
            LaunchpadRadioWidget)
        fields['image'].custom_widget = CustomWidgetFactory(
            LaunchpadFileWidget, displayWidth=15)
        widgets = form.setUpWidgets(
            fields, self.name, context, request, ignore_request=False,
            data={'action': 'keep'})
        self.action_widget = widgets['action']
        self.image_widget = widgets['image']

    def _getCurrentImage(self):
        return getattr(self.context.context, self.context.__name__, None)

    def __call__(self):
        img = self._getCurrentImage()
        if img is not None:
            # This widget is meant to be used only by fields which expect an
            # object implementing ILibraryFileAlias as their values.
            assert ILibraryFileAlias.providedBy(img)
            # XXX: Need to use img.secure_url here. This branch shouldn't land
            # without this changed. -- Guilherme Salgado, 2006-12-12
            url = img.url
        else:
            url = self.context.default_image_resource
        html = ('<div><img src="%s" alt="%s" /></div>\n'
                % (url, self.context.title))
        html += "%s\n%s" % (self.action_widget(), self.image_widget())
        return html

    def hasInput(self):
        return self.action_widget.hasInput()

    def _getActionsVocabulary(self):
        if self._getCurrentImage() is not None:
            action_names = [('keep', 'Keep your selected image'),
                            ('delete', 'Change back to default image'),
                            ('change', 'Change to')]
        else:
            action_names = [('keep', 'Leave as default image'),
                            ('change', 'Change to')]
        terms = [SimpleTerm(name, name, label) for name, label in action_names]
        return SimpleVocabulary(terms)

    def getInputValue(self):
        self._error = None
        action = self.action_widget.getInputValue()
        form = self.request.form
        if action == 'change' and not form.get(self.image_widget.name):
            self._error = WidgetInputError(
                self.name, self.label,
                LaunchpadValidationError(
                    _('Please specify the image you want to use.')))
            raise self._error
        if action == "keep":
            return self.context.keep_image_marker
        elif action == "change":
            image = form.get(self.image_widget.name)
            try:
                self.context.validate(image)
            except ValidationError, v:
                self._error = WidgetInputError(self.name, self.label, v)
                raise self._error
            return image
        elif action == "delete":
            return None

