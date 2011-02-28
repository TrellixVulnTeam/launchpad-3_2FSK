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


from canonical.launchpad.browser.feeds import FeedsMixin
from canonical.launchpad.webapp import (
    canonical_url,
    LaunchpadView,
    Link,
    )
from lp.code.interfaces.sourcepackagerecipe import RECIPE_ENABLED_FLAG
from lp.services.features import getFeatureFlag


class HasRecipesMenuMixin:
    """A mixin for context menus for objects that implement IHasRecipes."""

    def view_recipes(self):
        text = 'View source package recipes'
        enabled = False
        if self.context.recipes.count():
            enabled = True
        if not getFeatureFlag(RECIPE_ENABLED_FLAG):
            enabled = False
        return Link(
            '+recipes', text, icon='info', enabled=enabled, site='code')


class RecipeListingView(LaunchpadView, FeedsMixin):

    feed_types = ()

    branch_enabled = True
    owner_enabled = True

    @property
    def page_title(self):
        return 'Source Package Recipes for %(displayname)s' % {
            'displayname': self.context.displayname}

    def initialize(self):
        super(RecipeListingView, self).initialize()
        recipes = self.context.recipes
        if recipes.count() == 1:
            recipe = recipes.one()
            self.request.response.redirect(canonical_url(recipe))


class BranchRecipeListingView(RecipeListingView):

    branch_enabled = False


class PersonRecipeListingView(RecipeListingView):

    owner_enabled = False


class ProductRecipeListingView(RecipeListingView):
    pass
