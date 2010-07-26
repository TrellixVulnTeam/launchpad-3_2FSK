# Copyright 2009 Canonical Ltd.  This software is licensed under the
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

from zope.component import getUtility

from canonical.launchpad.webapp.interfaces import ILaunchBag
from lp.bugs.interfaces.malone import IMaloneApplication
from canonical.lazr.utils import smartquote

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


archive_admin = ContextDisplayName('Administer %s')

archive_activate = 'Activate Personal Package Archive'

archive_copy_packages = ContextDisplayName('Copy packages from %s')

archive_delete_packages = ContextDisplayName('Delete packages from %s')

archive_edit = ContextDisplayName('Edit %s')

bazaar_index = 'Launchpad Branches'

branch_bug_links = ContextDisplayName(smartquote('Bug links for %s'))

branch_index = ContextDisplayName(smartquote(
    '"%s" branch in Launchpad'))

def branchmergeproposal_index(context, view):
    return 'Proposal to merge %s' % context.source_branch.bzr_identity

bug_activity = ContextBugId('Bug #%s - Activity log')

bug_addsubscriber = LaunchbagBugID("Bug #%d - Add a subscriber")

bug_branch_add = LaunchbagBugID('Bug #%d - Add branch')

bug_edit = ContextBugId('Bug #%d - Edit')

bug_mark_as_duplicate = ContextBugId('Bug #%d - Mark as duplicate')

bug_mark_as_affecting_user = ContextBugId(
    'Bug #%d - does this bug affect you?')

bug_nominate_for_series = ViewLabel()

bug_secrecy = ContextBugId('Bug #%d - Set visibility')

bug_subscription = LaunchbagBugID('Bug #%d - Subscription options')

bugbranch_delete = 'Delete bug branch link'

buglinktarget_unlinkbugs = 'Remove links to bug reports'

buglisting_default = ContextTitle("Bugs in %s")

def buglisting_embedded_advanced_search(context, view):
    """Return the view's page heading."""
    return view.getSearchPageHeading()

def bugnomination_edit(context, view):
    """Return the title for the page to manage bug nominations."""
    return 'Manage nomination for bug #%d in %s' % (
        context.bug.id, context.target.bugtargetdisplayname)

bugtarget_bugs = ContextTitle('Bugs in %s')

def bugtarget_filebug_advanced(context, view):
    """Return the page title for reporting a bug."""
    if IMaloneApplication.providedBy(context):
        # We're generating a title for a top-level, contextless bug
        # filing page.
        return 'Report a bug'
    else:
        # We're generating a title for a contextual bug filing page.
        return 'Report a bug about %s' % context.title

bugtarget_filebug_search = bugtarget_filebug_advanced

bugtarget_filebug_submit_bug = bugtarget_filebug_advanced

bugtask_affects_new_product = LaunchbagBugID(
    'Bug #%d - Record as affecting another project')

bugtask_choose_affected_product = bugtask_affects_new_product

# This page is used for both projects/distros so we have to say 'software'
# rather than distro or project here.
bugtask_confirm_bugtracker_creation = LaunchbagBugID(
    'Bug #%d - Record as affecting another software')

bugtask_requestfix = LaunchbagBugID(
    'Bug #%d - Record as affecting another distribution/package')

bugtask_requestfix_upstream = LaunchbagBugID('Bug #%d - Confirm project')

code_in_branches = 'Projects with active branches'

codeimport_list = 'Code Imports'

codeimport_machines = ViewLabel()

def codeimport_machine_index(context, view):
    return smartquote('Code Import machine "%s"' % context.hostname)

codeimport_new = ViewLabel()

codeofconduct_admin = 'Administer Codes of Conduct'

codeofconduct_list = 'Ubuntu Codes of Conduct'

def contact_user(context, view):
    return view.specific_contact_title_text

cveset_all = 'All CVE entries registered in Launchpad'

cveset_index = 'Launchpad CVE tracker'

cve_index = ContextDisplayName('%s')

cve_linkbug = ContextDisplayName('Link %s to a bug report')

cve_unlinkbugs = ContextDisplayName('Remove links between %s and bug reports')

distribution_archive_list = ContextTitle('%s Copy Archives')

distribution_upstream_bug_report = ContextTitle('Upstream Bug Report for %s')

distribution_cvereport = ContextTitle('CVE reports for %s')

distribution_mirrors = ContextTitle("Mirrors of %s")

distribution_translations = ContextDisplayName('Translating %s')

distribution_search = ContextDisplayName(smartquote("Search %s's packages"))

distribution_index = ContextTitle('%s in Launchpad')

distributionsourcepackage_index = ContextTitle('%s')

distroarchseries_index = ContextTitle('%s in Launchpad')

distroarchseriesbinarypackage_index = ContextTitle('%s')

distroarchseriesbinarypackagerelease_index = ContextTitle('%s')

distroseries_cvereport = ContextDisplayName('CVE report for %s')

def distroseries_language_packs(context, view):
    return view.page_title

distroseries_translations = ContextTitle('Translations of %s in Launchpad')

distroseries_queue = ContextTitle('Queue for %s')

distroseriessourcepackagerelease_index = ContextTitle('%s')

hasannouncements_index = ContextDisplayName('%s news and announcements')

hassprints_sprints = ContextTitle("Events related to %s")

launchpad_feedback = 'Help improve Launchpad'

launchpad_forbidden = 'Forbidden'

def launchpad_search(context, view):
    """Return the page title corresponding to the user's search."""
    return view.page_title

launchpad_unexpectedformdata = 'Error: Unexpected form data'

launchpad_librarianfailure = "Sorry, you can't do this right now"

oauth_authorize = 'Authorize application to access Launchpad on your behalf'

object_templates = ContextDisplayName('Translation templates for %s')

oops = 'Oops!'

people_mergerequest_sent = 'Merge request sent'

person_answer_contact_for = ContextDisplayName(
    'Projects for which %s is an answer contact')

person_packagebugs = ContextDisplayName("%s's package bug reports")

person_packagebugs_overview = person_packagebugs

person_packagebugs_search = person_packagebugs

person_specfeedback = ContextDisplayName('Feature feedback requests for %s')

person_specworkload = ContextDisplayName('Blueprint workload for %s')

person_translations_to_review = ContextDisplayName(
    'Translations for review by %s')

poll_edit = ContextTitle(smartquote('Edit poll "%s"'))

poll_index = ContextTitle(smartquote('Poll: "%s"'))

poll_newoption = ContextTitle(smartquote('New option for poll "%s"'))

def polloption_edit(context, view):
    """Return the page title to edit a poll's option."""
    return 'Edit option: %s' % context.title

poll_vote_condorcet = ContextTitle(smartquote('Vote in poll "%s"'))

poll_vote_simple = ContextTitle(smartquote('Vote in poll "%s"'))

product_cvereport = ContextTitle('CVE reports for %s')

product_index = ContextTitle('%s in Launchpad')

product_purchase_subscription = ContextDisplayName(
    'Purchase Subscription for %s')

product_translations = ContextTitle('Translations of %s in Launchpad')

productseries_translations = ContextTitle('Translations overview for %s')

productseries_translations_settings = 'Settings for translations'

project_index = ContextTitle('%s in Launchpad')

project_translations = ContextTitle('Translatable projects for %s')

remotebug_index = ContextTitle('%s')

root_index = 'Launchpad'

rosetta_index = 'Launchpad Translations'

rosetta_products = 'Projects with Translations in Launchpad'

series_bug_nominations = ContextDisplayName('Bugs nominated for %s')

shipit_adminrequest = 'ShipIt admin request'

shipit_exports = 'ShipIt exports'

shipit_forbidden = 'Forbidden'

shipit_index = 'ShipIt'

shipit_index_edubuntu = 'Getting Edubuntu'

shipit_index_ubuntu = 'Request an Ubuntu CD'

shipit_login = 'ShipIt'

shipit_login_error = 'ShipIt - Unsuccessful login'

shipit_myrequest = "Your Ubuntu CD order"

shipit_oops = 'Error: Oops'

shipit_reports = 'ShipIt reports'

shipit_requestcds = 'Your Ubuntu CD Request'

shipit_survey = 'Ubuntu Server Edition survey'

shipitrequests_index = 'ShipIt requests'

shipitrequests_search = 'Search ShipIt requests'

shipitrequest_edit = 'Edit ShipIt request'

shipit_notfound = 'Error: Page not found'

signedcodeofconduct_index = ContextDisplayName('%s')

signedcodeofconduct_add = ContextTitle('Sign %s')

signedcodeofconduct_acknowledge = 'Acknowledge code of conduct signature'

signedcodeofconduct_activate = ContextDisplayName('Activating %s')

signedcodeofconduct_deactivate = ContextDisplayName('Deactivating %s')

standardshipitrequests_index = 'Standard ShipIt options'

standardshipitrequest_new = 'Create a new standard option'

standardshipitrequest_edit = 'Edit standard option'

team_newpoll = ContextTitle('New poll for team %s')

team_polls = ContextTitle('Polls for team %s')

token_authorized = 'Almost finished ...'

translationimportqueueentry_index = 'Translation import queue entry'

unauthorized = 'Error: Not authorized'
