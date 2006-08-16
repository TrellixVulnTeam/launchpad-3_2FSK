# Copyright 2004 Canonical Ltd.  All rights reserved.

"""Karma interfaces."""

__metaclass__ = type

__all__ = [
    'IKarma',
    'IKarmaAction',
    'IKarmaActionSet',
    'IKarmaCache',
    'IKarmaPersonCategoryCacheView',
    'IKarmaTotalCache',
    'IKarmaCategory',
    'IKarmaContext',
    ]

from zope.app.form.browser.interfaces import IAddFormCustomization
from zope.schema import Int, Datetime, Choice, Text, TextLine
from zope.interface import Interface, Attribute
from canonical.launchpad import _



class IKarma(Interface):
    """The Karma of a Person."""

    id = Int(title=_("Database ID"), required=True, readonly=True)

    person = Int(
        title=_("Person"), required=True, readonly=True,
        description=_("The user which this karma is assigned to."))

    action = Int(
        title=_("Action"), required=True,
        description=_("The action which gives the karma to the user."))

    datecreated = Datetime(
        title=_("Date Created"), required=True, readonly=True,
        description=_("The date this karma was assigned to the user."))

    product = Attribute(_("Product"))

    distribution = Attribute(_("Distribution"))

    sourcepackagename = Attribute(_("Source Package"))


class IKarmaAction(Interface):
    """The Action that gives karma to a Person."""

    id = Int(title=_("Database ID"), required=True, readonly=True)
    name = TextLine(
        title=_("Name"), required=True, readonly=False)
    category = Choice(
        title=_("Category"), required=True, readonly=False,
        vocabulary='KarmaCategory')
    title = TextLine(title=_("Title"), required=True)
    summary = Text(title=_("Summary"), required=True)
    points = Int(
        title=_("Points"), required=True, readonly=False,
        description=_("The number of points we give to a user which performs "
                      "this action."))


class IKarmaActionSet(IAddFormCustomization):
    """The set of actions that gives karma to a Person."""

    title = Attribute('Title')

    def __iter__():
        """Iterate over all Karma Actions."""

    def getByName(name, default=None):
        """Return the KarmaAction with the given name.

        Return the default value if there's no such KarmaAction.
        """

    def selectByCategory(category):
        """Return all KarmaAction objects of the given category."""

    def selectByCategoryAndPerson(category, person, orderBy=None):
        """Return all KarmaAction objects of the given category if <person>
        performed these actions at least once.

        <orderBy> can be either a string with the column name you want to sort
        or a list of column names as strings.
        If no orderBy is specified the results will be ordered using the
        default ordering specified in KarmaAction._defaultOrder.
        """


class IKarmaCache(Interface):
    """A cached value of a person's karma, grouped by category and context.
    
    Context, in this case, means the Product/Distribution on which the person
    performed an action that in turn caused the karma to be assigned.

    The karmavalue stored here is not a simple sum, it's calculated based on
    the date the Karma was assigned. That's why we want to cache it here.
    (See https://launchpad.canonical.com/KarmaCalculation for more information
     on how the value here is obtained)
    """

    person = Int(
        title=_("Person"), required=True, readonly=True,
        description=_("The person which performed the actions of this "
                      "category, and thus got the karma."))

    category = Choice(
        title=_("Category"), required=True, readonly=True,
        vocabulary='KarmaCategory')

    karmavalue = Int(
        title=_("Karma Points"), required=True, readonly=True,
        description=_("The karma points of all actions of this category "
                      "performed by this person."))

    product = Attribute(_("Product"))

    distribution = Attribute(_("Distribution"))

    sourcepackagename = Attribute(_("Source Package"))


class IKarmaPersonCategoryCacheView(Interface):
    """A cached value of a person's karma, grouped by category."""

    person = Int(
        title=_("Person"), required=True, readonly=True,
        description=_("The person which performed the actions of this "
                      "category, and thus got the karma."))

    category = Choice(
        title=_("Category"), required=True, readonly=True,
        vocabulary='KarmaCategory')

    karmavalue = Int(
        title=_("Karma Points"), required=True, readonly=True,
        description=_("The karma points of all actions of this category "
                      "performed by this person."))


class IKarmaTotalCache(Interface):
    """A cached value of the total of a person's karma (all categories)."""

    id = Int(title=_("Database ID"), required=True, readonly=True)

    person = Int(
            title=_("Person"), required=True, readonly=True,
            description=_("The person who has the karma.")
            )

    karma_total = Int(
            title=_("Karma"), required=True, readonly=True,
            description=_("The total karma points scored by the person.")
            )


class IKarmaCategory(Interface):
    """A catgory of karma events."""

    name = Attribute("The name of the category.")
    title = Attribute("The title of the karma category.")
    summary = Attribute("A brief summary of this karma category.")

    karmaactions = Attribute("All the karma actions in this category.")


class IKarmaContext(Interface):
    """A Launchpad context to which we track karma."""

    def getTopContributorsGroupedByCategory(limit=None):
        """Return a dict mapping categories to the top contributors (and their
        karma) of this context on that specific category.

        This context must implement either IProduct or IDistribution.

        For each category, limit the number of contributors returned to the
        given limit, if it's not None.

        The results are sorted descending by karma.
        """

    def getTopContributors(category=None, limit=None):
        """Return the people with the highest amount of Karma, and their
        karma, on this context.

        The given context must implement either IProduct or IDistribution.

        The number of people returned is limited to the given limit, if it's
        not None.

        If the given category is not None, then return the people with the
        highest amount of karma of the given category on this context.

        The results are sorted descending by karma.
        """

