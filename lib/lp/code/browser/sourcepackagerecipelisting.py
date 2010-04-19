# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Base class view for sourcepackagerecipe listings."""

__metaclass__ = type

__all__ = [
    'BranchRecipeListingView',
    'HasRecipesMenuMixin',
    'PersonRecipeListingView',
    'ProductRecipeListingView',
    ]

from lazr.enum import EnumeratedType, Item
from zope.interface import Interface
from zope.schema import Choice

from canonical.config import config
from canonical.launchpad import _
from canonical.launchpad.browser.feeds import FeedsMixin
from canonical.launchpad.webapp import LaunchpadView, Link
from lp.code.interfaces.branch import IBranch
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.product import IProduct


class HasRecipesMenuMixin:
    """A mixin for context menus for objects that implement IHasRecipes."""

    def view_recipes(self):
        text = 'View source package recipes'
        enabled = False
        if self.context.getRecipes().count():
            enabled = True
        if not config.build_from_branch.enabled:
            enabled = False
        return Link(
            '+recipes', text, icon='info', enabled=enabled)


class RecipeListingView(LaunchpadView, FeedsMixin):

    feed_types = ()
    product_enabled = True
    branch_enabled = True
    owner_enabled = True

    @property
    def page_title(self):
        return 'Source Package Recipes for %(displayname)s' % {
            'displayname': self.context.displayname}


class BranchRecipeListingView(RecipeListingView):

    __used_for__ = IBranch

    branch_enabled = False


class PersonRecipeListingView(RecipeListingView):

    __used_for__ = IPerson

    owner_enabled = False


class ProductRecipeListingView(RecipeListingView):

    __used_for__ = IProduct

    product_enabled = False
