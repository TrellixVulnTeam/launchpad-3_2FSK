# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""*** PLEASE STOP ADDING TO THIS FILE ***

Use the page_title attribute of the view.

This module is used as a last resort by the Launchpad webapp to determine
titles for pages.

https://launchpad.canonical.com/LaunchpadTitles

** IMPORTANT ** (Brad Bollenbach, 2006-07-20) This module should not be
put in webapp, because webapp is not domain-specific, and should not be
put in browser, because this would make webapp depend on browser. SteveA
has a plan to fix this overall soon.

This module contains string or unicode literals assigned to names, or
functions such as this one:

  def bug_index(context, view):
      return 'Bug %s: %s' % (context.id, context.title)

The names of string or unicode literals and functions are the names of
the page templates, but with hyphens changed to underscores.  So, the
function bug_index given about is for the page template bug-index.pt.

If the function needs to include details from the request, this is
available from view.request.  However, these functions should not access
view.request.  Instead, the view class should make a function or
attribute available that provides the required information.

If the function returns None, it means that the default page title for
the whole of Launchpad should be used.  This is defined in the variable
DEFAULT_LAUNCHPAD_TITLE.

There are shortcuts for some common substitutions at the top of this
module.

The strings and functions for page titles are arranged in alphabetical
order after the helpers.

"""
__metaclass__ = type

from lazr.restful.utils import smartquote
from zope.component import getUtility

from canonical.launchpad.webapp.interfaces import ILaunchBag


DEFAULT_LAUNCHPAD_TITLE = 'Launchpad'

# Helpers.


class SubstitutionHelper:
    """An abstract class for substituting values into formatted strings."""
    def __init__(self, text):
        self.text = text

    def __call__(self, context, view):
        raise NotImplementedError


class ContextDisplayName(SubstitutionHelper):
    """Return the formatted string with context's displayname."""
    def __call__(self, context, view):
        return self.text % context.displayname


class ContextId(SubstitutionHelper):
    """Return the formatted string with context's id."""
    def __call__(self, context, view):
        return self.text % context.id


class ContextTitle(SubstitutionHelper):
    """Return the formatted string with context's title."""
    def __call__(self, context, view):
        return self.text % context.title


class LaunchbagBugID(SubstitutionHelper):
    """Return the formatted string with the bug's id from LaunchBag."""
    def __call__(self, context, view):
        return self.text % getUtility(ILaunchBag).bug.id


class ContextBugId(SubstitutionHelper):
    """Helper to include the context's bug id in the title."""

    def __call__(self, context, view):
        return self.text % context.bug.id


class ViewLabel:
    """Helper to use the view's label as the title."""
    def __call__(self, context, view):
        return view.label


bazaar_index = 'Launchpad Branches'

branch_bug_links = ContextDisplayName(smartquote('Bug links for %s'))

branch_index = ContextDisplayName(smartquote('"%s" branch in Launchpad'))


def branchmergeproposal_index(context, view):
    return 'Proposal to merge %s' % context.source_branch.bzr_identity

code_in_branches = 'Projects with active branches'

codeimport_list = 'Code Imports'

codeimport_machines = ViewLabel()


def codeimport_machine_index(context, view):
    return smartquote('Code Import machine "%s"' % context.hostname)

codeimport_new = ViewLabel()

distribution_archive_list = ContextTitle('%s Copy Archives')

distribution_translations = ContextDisplayName('Translating %s')

distribution_search = ContextDisplayName(smartquote("Search %s's packages"))

distroarchseries_index = ContextTitle('%s in Launchpad')

distroarchseriesbinarypackage_index = ContextTitle('%s')

distroarchseriesbinarypackagerelease_index = ContextTitle('%s')

distroseries_translations = ContextTitle('Translations of %s in Launchpad')

distroseries_queue = ContextTitle('Queue for %s')

distroseriessourcepackagerelease_index = ContextTitle('%s')

object_templates = ContextDisplayName('Translation templates for %s')

person_translations_to_review = ContextDisplayName(
    'Translations for review by %s')

product_translations = ContextTitle('Translations of %s in Launchpad')

productseries_translations = ContextTitle('Translations overview for %s')

productseries_translations_settings = 'Settings for translations'

project_translations = ContextTitle('Translatable projects for %s')

rosetta_index = 'Launchpad Translations'

rosetta_products = 'Projects with Translations in Launchpad'
