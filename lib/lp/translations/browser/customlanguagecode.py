# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'CustomLanguageCodeAddView',
    'CustomLanguageCodeBreadcrumb',
    'CustomLanguageCodesIndexView',
    'CustomLanguageCodeRemoveView',
    'CustomLanguageCodeView',
    'HasCustomLanguageCodesNavigation',
    'HasCustomLanguageCodesTraversalMixin',
	]


import re

from canonical.lazr.utils import smartquote

from lp.translations.interfaces.customlanguagecode import (
    ICustomLanguageCode, IHasCustomLanguageCodes)

from canonical.launchpad.webapp import (
    action, canonical_url, LaunchpadFormView, LaunchpadView, Navigation,
    stepthrough)
from canonical.launchpad.webapp.breadcrumb import Breadcrumb
from canonical.launchpad.webapp.interfaces import NotFoundError
from canonical.launchpad.webapp.menu import structured


# Regex for allowable custom language codes.
CODE_PATTERN = "[a-zA-Z0-9_-]+$"


def check_code(custom_code):
    """Is this custom language code well-formed?"""
    return re.match(CODE_PATTERN, custom_code) is not None


class CustomLanguageCodeBreadcrumb(Breadcrumb):
    """Breadcrumb for a `CustomLanguageCode`."""
    @property
    def text(self):
        return smartquote(
            'Custom language code "%s"' % self.context.language_code)


class CustomLanguageCodesIndexView(LaunchpadView):
    """Listing of `CustomLanguageCode`s for a given context."""

    page_title = "Custom language codes"

    @property
    def label(self):
        return "Custom language codes for %s" % self.context.displayname


class CustomLanguageCodeAddView(LaunchpadFormView):
    """Create a new custom language code."""
    schema = ICustomLanguageCode
    field_names = ['language_code', 'language']
    page_title = "Add new code"

    create = False

    @property
    def label(self):
        return (
            "Add a custom language code for %s" % self.context.displayname)

    def validate(self, data):
        self.language_code = data.get('language_code')
        self.language = data.get('language')
        if self.language_code is not None:
            self.language_code = self.language_code.strip()

        if not self.language_code:
            self.setFieldError('language_code', "No code was entered.")
            return

        if not check_code(self.language_code):
            self.setFieldError('language_code', "Invalid language code.")
            return

        existing_code = self.context.getCustomLanguageCode(self.language_code)
        if existing_code is not None:
            if existing_code.language != self.language:
                self.setFieldError(
                    'language_code',
                    structured(
                        "There already is a custom language code '%s'." %
                            self.language_code))
                return
        else:
            self.create = True

    @action('Add', name='add')
    def add_action(self, action, data):
        if self.create:
            self.context.createCustomLanguageCode(
                self.language_code, self.language)

    @property
    def action_url(self):
        return "%s/+add-custom-language-code" % canonical_url(self.context)

    @property
    def next_url(self):
        """See `LaunchpadFormView`."""
        return "%s/+custom-language-codes" % canonical_url(self.context)

    @property
    def cancel_url(self):
        return self.next_url


class CustomLanguageCodeView(LaunchpadView):
    schema = ICustomLanguageCode


class CustomLanguageCodeRemoveView(LaunchpadFormView):
    """View for removing a `CustomLanguageCode`."""
    schema = ICustomLanguageCode
    field_names = []

    page_title = "Remove"

    @property
    def code(self):
        """The custom code."""
        return self.context.language_code

    @property
    def label(self):
        return "Remove custom language code '%s'" % self.code

    @action("Remove")
    def remove(self, action, data):
        """Remove this `CustomLanguageCode`."""
        code = self.code
        self.context.translation_target.removeCustomLanguageCode(self.context)
        self.request.response.addInfoNotification(
            "Removed custom language code '%s'." % code)

    @property
    def next_url(self):
        return "%s/+custom-language-codes" % canonical_url(
            self.context.translation_target)

    @property
    def cancel_url(self):
        return self.next_url


class HasCustomLanguageCodesTraversalMixin:
    """Navigate from an `IHasCustomLanguageCodes` to a `CustomLanguageCode`.
    """
    @stepthrough('+customcode')
    def traverseCustomCode(self, name):
        """Traverse +customcode URLs."""
        if not check_code(name):
            raise NotFoundError("Invalid custom language code.")

        return self.context.getCustomLanguageCode(name)


class HasCustomLanguageCodesNavigation(Navigation,
                                       HasCustomLanguageCodesTraversalMixin):
    """Generic navigation for `IHasCustomLanguageCodes`."""
    usedfor = IHasCustomLanguageCodes
