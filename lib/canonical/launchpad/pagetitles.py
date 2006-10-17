# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""This module is used by the Launchpad webapp to determine titles for pages.

https://launchpad.canonical.com/LaunchpadTitles

** IMPORTANT ** (Brad Bollenbach, 2006-07-20) This module should not be put in
webapp, because webapp is not domain-specific, and should not be put in browser,
because this would make webapp depend on browser. SteveA has a plan to fix this
overall soon.

This module contains string or unicode literals assigned to names, or functions
such as this one:

  def bug_index(context, view):
      return 'Bug %s: %s' % (context.id, context.title)

The names of string or unicode literals and functions are the names of
the page templates, but with hyphens changed to underscores.  So, the function
bug_index given about is for the page template bug-index.pt.

If the function needs to include details from the request, this is available
from view.request.  However, these functions should not access view.request.
Instead, the view class should make a function or attribute available that
provides the required information.

If the function returns None, it means that the default page title for the
whole of Launchpad should be used.  This is defined in the variable
DEFAULT_LAUNCHPAD_TITLE.

There are shortcuts for some common substitutions at the top of this module.

The strings and functions for page titles are arranged in alphabetical order
after the helpers.

"""
__metaclass__ = type

from zope.component import getUtility
from canonical.launchpad.interfaces import ILaunchBag
from canonical.launchpad.webapp import smartquote

DEFAULT_LAUNCHPAD_TITLE = 'Launchpad'

# Helpers.

class BugTaskPageTitle:
    def __call__(self, context, view):
        return smartquote('Bug #%d in %s: "%s"') % (
            context.bug.id, context.targetname, context.bug.title)


class BugTaskBackportingTitle:
    def __call__(self, context, view):
        return "Bug #%d in %s - Backport fix to releases" % (
            context.bug.id, context.targetname)


class SubstitutionHelper:
    def __init__(self, text):
        self.text = text

    def __call__(self, context, view):
        raise NotImplementedError


class ContextDisplayName(SubstitutionHelper):
    def __call__(self, context, view):
        return self.text % context.displayname


class ContextId(SubstitutionHelper):
    def __call__(self, context, view):
        return self.text % context.id


class ContextTitle(SubstitutionHelper):
    def __call__(self, context, view):
        return self.text % context.title


class ContextBrowsername(SubstitutionHelper):
    def __call__(self, context, view):
        return self.text % context.browsername


class LaunchbagBugID(SubstitutionHelper):
    def __call__(self, context, view):
        return self.text % getUtility(ILaunchBag).bug.id


# Functions and strings used as the titles of pages.

bazaar_all_branches = 'All branches in the Launchpad Bazaar'

bazaar_index = 'The Launchpad Bazaar'

bazaar_sync_review = 'Review upstream repositories for Launchpad Bazaar syncing'

def binarypackagerelease_index(context, view):
    return "%s binary package in Launchpad" % context.title

binarypackagenames_index = 'Binary package name set'

bounties_index = 'Bounties registered in Launchpad'

bounty_add = 'Register a bounty'

bounty_edit = ContextTitle(smartquote('Edit bounty "%s"'))

bounty_link = ContextTitle('Link a bounty to %s')

bounty_index = ContextTitle(smartquote('Bounty "%s" in Launchpad'))

bounty_subscription = ContextTitle(smartquote('Subscription to bounty "%s"'))

branch_edit = ContextTitle(smartquote('Change "%s" branch details'))

branch_index = ContextDisplayName(smartquote('Bazaar branch "%s"'))

branch_subscription = ContextTitle(smartquote('Subscription to branch "%s"'))

branchtarget_branchlisting = ContextTitle('Details of Branches for %s')

bug_activity = ContextId('Bug #%s - Activity log')

bug_addsubscriber = LaunchbagBugID("Bug #%d - Add a subscriber")

def bug_attachment_edit(context, view):
    return smartquote('Bug #%d - Edit attachment "%s"') % (
        context.bug.id, context.title)

bug_branch_add = LaunchbagBugID('Bug #%d - Add branch')

bug_comment_add = LaunchbagBugID('Bug #%d - Add a comment or attachment')

bug_cve = LaunchbagBugID("Bug #%d - Add CVE reference")

bug_edit = ContextId('Bug #%d - Edit')

bug_edit_confirm = ContextId('Bug #%d - Edit confirmation')

bug_extref_add = LaunchbagBugID("Bug #%d - Add a web link")

def bug_extref_edit(context, view):
    return smartquote('Bug #%d - Edit web link "%s"') % (
        context.bug.id, context.title)

bug_mark_as_duplicate = ContextId('Bug #%d - Mark as duplicate')

bug_removecve = LaunchbagBugID("Bug #%d - Remove CVE reference")

bug_secrecy = ContextId('Bug #%d - Set visibility')

bug_subscription = LaunchbagBugID('Bug #%d - Subscription options')

bug_watch_add = LaunchbagBugID('Bug #%d - Add external bug watch')

bugbranch_status = "Edit branch fix status"

def bugcomment_index(context, view):
    return "Bug #%d - Commment #%d" % (context.bug.id, view.comment.index)

buglinktarget_linkbug = 'Link to bug report'

buglinktarget_unlinkbugs = 'Remove links to bug reports'

buglisting_advanced = ContextTitle("Bugs in %s")

buglisting_default = ContextTitle("Bugs in %s")

def bugwatch_editform(context, view):
    return 'Bug #%d - Edit external bug watch (%s in %s)' % (
        context.bug.id, context.remotebug, context.bugtracker.title)

# bugpackageinfestations_index is a redirect

# bugproductinfestations_index is a redirect

def bugs_assigned(context, view):
    if view.user:
        return 'Bugs assigned to %s' % view.user.browsername
    else:
        return 'No-one to display bugs for'

bugtarget_advanced_search = ContextTitle("Search bugs in %s")

bugtarget_filebug = ContextTitle('Report a bug about %s')

bugtask_backport_fixing = BugTaskBackportingTitle()

bugtask_confirm_unlinked = LaunchbagBugID('Bug #%d - Request a fix')

bugtask_edit = BugTaskPageTitle()

bugtask_index = BugTaskPageTitle()

bugtask_requestfix = bugtask_confirm_unlinked

bugtask_view = BugTaskPageTitle()

# bugtask_macros_buglisting contains only macros
# bugtasks_index is a redirect

bugtracker_edit = ContextTitle(
    smartquote('Change details for "%s" bug tracker'))

bugtracker_index = ContextTitle(smartquote('Bug tracker "%s"'))

bugtrackers_add = 'Register an external bug tracker'

bugtrackers_index = 'Bug trackers registered in Malone'

build_buildlog = ContextTitle('Build log for %s')

build_changes = ContextTitle('Changes in %s')

build_index = ContextTitle('Build details for %s')

build_retry = ContextTitle('Retry %s')

build_rescore = ContextTitle('Rescore %s')

builders_index = 'Launchpad build farm'

builder_edit = ContextTitle(smartquote('Edit build machine "%s"'))

builder_index = ContextTitle(smartquote('Build machine "%s"'))

builder_cancel = ContextTitle(smartquote('Cancel job for "%s"'))

builder_mode = ContextTitle(smartquote('Change mode for "%s"'))

builder_admin = ContextTitle(smartquote('Administer "%s" builder'))

builder_history = ContextTitle(smartquote('Build History for "%s"'))

calendar_index = ContextTitle('%s')

calendar_event_addform = ContextTitle('Add event to %s')

calendar_event_display = ContextTitle(smartquote('Event "%s"'))

calendar_event_editform = ContextTitle(smartquote('Change "%s" event details'))

calendar_subscribe = ContextTitle(smartquote('Subscribe to "%s"'))

calendar_subscriptions = 'Calendar subscriptions'

def calendar_view(context, view):
    return '%s - %s' % (context.calendar.title, view.datestring)
calendar_view_day = calendar_view
calendar_view_week = calendar_view
calendar_view_month = calendar_view
calendar_view_year = calendar_view

codeofconduct_admin = 'Administer Codes of Conduct'

codeofconduct_index = ContextTitle('%s')

codeofconduct_list = 'Ubuntu Codes of Conduct'

cveset_all = 'All CVE entries registered in Launchpad'

cveset_index = 'Launchpad CVE tracker'

cve_index = ContextDisplayName('%s')

cve_linkbug = ContextDisplayName('Link %s to a bug report')

cve_unlinkbugs = ContextDisplayName('Remove links between %s and bug reports')

debug_root_changelog = 'Launchpad changelog'

debug_root_index = 'Launchpad Debug Home Page'

default_editform = 'Default "Edit" Page'

distributionmirror_edit = ContextTitle('Edit mirror %s')

distributionmirror_index = ContextTitle('Mirror %s')

distributionmirror_mark_official = ContextTitle('Mark mirror %s as official')

distributionmirror_prober_logs = ContextTitle('%s mirror prober logs')

distribution_allpackages = ContextTitle('All packages in %s')

distribution_bugcontact = ContextTitle('Change bug contact for %s')

distribution_change_mirror_admin = 'Change mirror administrator'

distribution_cvereport = ContextTitle('CVE reports for %s')

distribution_edit = ContextTitle('Edit %s')

distribution_members = ContextTitle('%s distribution members')

distribution_memberteam = ContextTitle(
    smartquote("Change %s's distribution team"))

distribution_mirrors = ContextTitle("Mirrors of %s")

distribution_newmirror = ContextTitle("Register a new mirror for %s")

distribution_translations = ContextDisplayName('Translating %s')

distribution_translators = ContextTitle(
    smartquote("Appoint %s's translation group"))

distribution_search = ContextDisplayName(smartquote("Search %s's packages"))

distribution_index = ContextTitle('%s in Launchpad')

distribution_builds = ContextTitle('%s builds')

distribution_uploadadmin = ContextTitle('Change Upload Manager for %s')

distributionsourcepackage_bugs = ContextTitle('Bugs in %s')

distributionsourcepackage_index = ContextTitle('%s')

distributionsourcepackage_manage_bugcontacts = ContextTitle('Bug contacts for %s')

distributionsourcepackagerelease_index = ContextTitle('%s')

distroarchrelease_admin = ContextTitle('Administer %s')

distroarchrelease_index = ContextTitle('%s in Launchpad')

distroarchrelease_builds = ContextTitle('%s builds')

distroarchrelease_search = ContextTitle(
    smartquote("Search %s's binary packages"))

distroarchreleasebinarypackage_index = ContextTitle('%s')

distroarchreleasebinarypackagerelease_index = ContextTitle('%s')

distrorelease_addport = ContextTitle('Add a port of %s')

distrorelease_bugs = ContextTitle('Bugs in %s')

distrorelease_cvereport = ContextDisplayName('CVE report for %s')

distrorelease_edit = ContextTitle('Edit details of %s')

def distrorelease_index(context, view):
    return '%s %s in Launchpad' % (context.distribution.title, context.version)

distrorelease_packaging = ContextDisplayName('Mapping packages to upstream '
    'for %s')

distrorelease_search = ContextDisplayName('Search packages in %s')

distrorelease_translations = ContextTitle('Translations of %s in Rosetta')

distrorelease_builds = ContextTitle('Builds for %s')

distrorelease_queue = ContextTitle('Queue for %s')

distroreleasebinarypackage_index = ContextTitle('%s')

distroreleaselanguage_index = ContextTitle('%s')

distroreleasesourcepackagerelease_index = ContextTitle('%s')

distros_index = 'Distributions registered in Launchpad'

errorservice_config = 'Configure error log'

errorservice_entry = 'Error log entry'

errorservice_index = 'Error log report'

errorservice_tbentry = 'Traceback entry'

faq = 'Launchpad Frequently Asked Questions'

foaf_adminrequestmerge = 'Merge Launchpad accounts'

foaf_mergerequest_sent = 'Merge request sent'

foaf_newperson = 'Create a new Launchpad profile'

foaf_newteam = 'Register a new team in Launchpad'

foaf_requestmerge_multiple = 'Merge Launchpad accounts'

foaf_requestmerge = 'Merge Launchpad accounts'

karmaaction_index = 'Karma actions'

karmaaction_edit = 'Edit karma action'

karmacontext_topcontributors = ContextTitle('Top %s Contributors')

# launchpad_debug doesn't need a title.

def launchpad_addform(context, view):
    # Returning None results in the default Launchpad page title being used.
    return getattr(view, 'page_title', None)

launchpad_editform = launchpad_addform

launchpad_feedback = 'Help us improve Launchpad'

launchpad_forbidden = 'Forbidden'

launchpad_forgottenpassword = 'Need a new Launchpad password?'

launchpad_graphics = 'Overview of Launchpad graphics and icons'

template_form = 'XXX PLEASE DO NOT USE THIS TEMPLATE XXX'

# launchpad_css is a css file

# launchpad_js is standard javascript

# XXX: The general form is a fallback form; I'm not sure why it is
# needed, nor why it needs a pagetitle, but I can't debug this today.
#   -- kiko, 2005-09-29
launchpad_generalform = "Launchpad - General Form (Should Not Be Displayed)"

launchpad_legal = 'Launchpad legalese'

launchpad_login = 'Log in or register with Launchpad'

launchpad_log_out = 'Log out from Launchpad'

launchpad_notfound = 'Error: Page not found'

launchpad_requestexpired = 'Error: Timeout'

launchpad_unexpectedformdata = 'Error: Unexpected form data'

launchpad_librarianfailure = "Sorry, you can't do this right now"

# launchpad_widget_macros doesn't need a title.

logintoken_claimprofile = 'Claim Launchpad profile'

logintoken_index = 'Launchpad: redirect to the logintoken page'

logintoken_mergepeople = 'Merge Launchpad accounts'

logintoken_newaccount = 'Create a new Launchpad account'

logintoken_resetpassword = 'Forgotten your password?'

logintoken_validateemail = 'Confirm e-mail address'

logintoken_validategpg = 'Confirm OpenPGP key'

logintoken_validatesignonlygpg = 'Confirm sign-only OpenPGP key'

logintoken_validateteamemail = 'Confirm e-mail address'

# main_template has the code to insert one of these titles.

malone_about = 'About Malone'

malone_distros_index = 'Report a bug about a distribution'

malone_index = 'Malone: the Launchpad bug tracker'

malone_filebug = "Report a bug"

# malone_people_index is a redirect

# malone_template is a means to include the mainmaster template

# messagechunk_snippet is a fragment

# messages_index is a redirect

message_add = ContextId('Bug #%d - Add a comment')

milestone_add = ContextTitle('Add new milestone for %s')

milestone_index = ContextTitle('%s')

milestone_edit = ContextTitle('Edit %s')

# object_pots is a fragment.

object_potemplatenames = ContextDisplayName('Template names for %s')

object_reassignment = ContextTitle('Reassign %s')

object_driver = ContextTitle('Appoint the driver for %s')

object_launchpadusage = ContextTitle('Launchpad usage by %s')

oops = 'Oops!'

def package_bugs(context, view):
    return 'Bugs in %s' % context.name

people_index = 'People and teams in Launchpad'

def people_list(context, view):
    return view.header

person_bounties = ContextDisplayName('Bounties for %s')

person_branches = ContextDisplayName('Bazaar branches for %s')

person_branch_add = ContextDisplayName('Register a new branch for %s')

def person_bugs(context, view):
    return view.getSearchPageHeading()

person_changepassword = 'Change your password'

person_claim = 'Claim account'

person_codesofconduct = ContextDisplayName(smartquote("%s's code of conduct signatures"))

person_edit = ContextDisplayName(smartquote("%s's details"))

person_editemails = ContextDisplayName(smartquote("%s's e-mail addresses"))

person_editpgpkeys = ContextDisplayName(smartquote("%s's OpenPGP keys"))

person_edithomepage = ContextDisplayName(smartquote("%s's home page"))

person_editircnicknames = ContextDisplayName(smartquote("%s's IRC nicknames"))

person_editjabberids = ContextDisplayName(smartquote("%s's Jabber IDs"))

person_editsshkeys = ContextDisplayName(smartquote("%s's SSH keys"))

person_editwikinames = ContextDisplayName(smartquote("%s's wiki names"))

# person_foaf is an rdf file

person_images = ContextDisplayName(smartquote("%s's hackergotchi and emblem"))

person_index = ContextDisplayName('%s in Launchpad')

person_karma = ContextDisplayName(smartquote("%s's karma in Launchpad"))

person_packages = ContextDisplayName('Packages maintained by %s')

person_packagebugs = ContextDisplayName("%s's package bug reports")

person_packagebugs_overview = person_packagebugs

person_packagebugs_search = person_packagebugs

person_review = ContextDisplayName("Review %s")

person_specfeedback = ContextDisplayName('Feature feedback requests for %s')

person_specworkload = ContextDisplayName('Specification workload for %s')

person_translations = ContextDisplayName('Translations made by %s')

person_teamhierarchy = ContextDisplayName('Team hierarchy for %s')

pofile_edit = 'Rosetta: Edit PO file details'
# XXX mpt 20051209: This should be more context-sensitive

pofile_export = ContextTitle('%s file exports')

def pofile_index(context, view):
    return 'Rosetta: %s in %s' % (
        context.potemplate.title, context.language.englishname)

def pofile_translate(context, view):
    return 'Translating %s into %s with Rosetta' % (
        context.potemplate.displayname,
        context.language.englishname)

pofile_upload = ContextTitle('%s upload in Rosetta')

# portlet_* are portlets

poll_edit = ContextTitle(smartquote('Edit poll "%s"'))

poll_index = ContextTitle(smartquote('Poll: "%s"'))

poll_newoption = ContextTitle(smartquote('New option for poll "%s"'))

def poll_new(context, view):
    return 'Create a new Poll in team %s' % context.team.displayname

def polloption_edit(context, view):
    return 'Edit option: %s' % context.title

poll_options = ContextTitle(smartquote('Options for poll "%s"'))

poll_vote_condorcet = ContextTitle(smartquote('Vote in poll "%s"'))

poll_vote_simple = ContextTitle(smartquote('Vote in poll "%s"'))

def pomsgset_translate(context, view):
    return 'Translating %s into %s with Rosetta' % (
        context.pofile.potemplate.displayname,
        context.pofile.language.englishname)

# potemplate_chart is a fragment

potemplate_edit = ContextTitle(smartquote('Edit "%s" in Rosetta'))

potemplate_index = ContextTitle(smartquote('"%s" in Rosetta'))

potemplate_upload = ContextTitle(smartquote('"%s" upload in Rosetta'))

potemplate_export = ContextTitle(smartquote('Export translations of "%s"'))

potemplatename_add = 'Add a new template name to Rosetta'

potemplatename_edit = ContextTitle(smartquote('Edit "%s" in Rosetta'))

potemplatename_index = ContextTitle(smartquote('"%s" in Rosetta'))

potemplatenames_index = 'Template names in Launchpad'

product_add = 'Register a product with Launchpad'

product_admin = ContextTitle('Administer %s in Launchpad')

product_bugcontact = ContextTitle('Edit bug contact for %s')

product_bugs = ContextDisplayName('Bugs in %s')

product_branches = ContextDisplayName(
    smartquote("%s's Bazaar branches registered in Launchpad"))

product_distros = ContextDisplayName('%s packages: Comparison of distributions')

product_cvereport = ContextTitle('CVE reports for %s')

product_edit = ContextTitle('%s in Launchpad')

product_index = ContextTitle('%s in Launchpad')

product_new = 'Register a product in the Launchpad'

product_translators = ContextTitle('Set translation group for %s')

product_packages = ContextDisplayName('%s packages in Launchpad')

product_translations = ContextTitle('Translations of %s in Rosetta')

productrelease_add = ContextTitle('Register a new %s release in Launchpad')

productrelease_admin = ContextTitle('Administer %s in Launchpad')

productrelease_edit = ContextDisplayName('Edit details of %s in Launchpad')

productrelease_index = ContextDisplayName('%s in Launchpad')

products_index = 'Products registered in Launchpad'

productseries_index = ContextTitle('Overview of %s')

productseries_packaging = ContextDisplayName('Packaging of %s in distributions')

productseries_source = 'Import product series'

productseries_translations = ContextTitle('Translation templates for %s')

productseries_translations_upload = 'Request new translations upload'

productseries_ubuntupkg = 'Ubuntu source package'

project_index = ContextTitle('%s in Launchpad')

project_branches = ContextTitle('Bazaar branches for %s')

project_bugs = ContextTitle('Bugs in %s')

project_edit = ContextTitle('%s project details')

project_interest = 'Rosetta: Project not translatable'

project_rosetta_index = ContextTitle('Rosetta: %s')

project_specs = ContextTitle('Specifications for %s')

projects_index = 'Projects registered in Launchpad'

projects_request = 'Rosetta: Request a project'

projects_search = 'Search for projects in Launchpad'

rdf_index = "Launchpad RDF"

# redirect_up is a redirect

def reference_index(context, view):
    return 'Web links for bug %s' % context.bug.id

# references_index is a redirect

registry_about = 'About the Launchpad Registry'

registry_index = 'Product and group registration in Launchpad'

products_all = 'Upstream products registered in Launchpad'

projects_all = 'Projects registered in Launchpad'

registry_review = 'Review Launchpad items'

related_bounties = ContextDisplayName('Bounties for %s')

remotebug_index = ContextTitle('%s')

root_index = 'Launchpad'

rosetta_about = 'About Rosetta'

rosetta_index = 'Rosetta'

rosetta_preferences = 'Rosetta: Preferences'

product_branch_add = ContextDisplayName('Register a new %s branch')

def productseries_edit(context, view):
    return 'Change %s %s details' % (context.product.displayname, context.name)

productseries_new = ContextDisplayName('Register a new %s release series')

securitycontact_edit = ContextDisplayName("Edit %s security contact")

shipit_adminrequest = 'ShipIt admin request'

shipit_index = 'ShipIt'

shipit_exports = 'ShipIt exports'

shipit_forbidden = 'Forbidden'

shipit_myrequest = "Your ShipIt order"

shipit_oops = 'Error: Oops'

shipit_reports = 'ShipIt reports'

shipit_requestcds = 'Your ShipIt Request'

shipitrequests_index = 'ShipIt requests'

shipitrequests_search = 'Search ShipIt requests'

shipitrequest_edit = 'Edit ShipIt request'

shipit_notfound = 'Error: Page not found'

signedcodeofconduct_index = ContextDisplayName('%s')

signedcodeofconduct_add = ContextTitle('Sign %s')

signedcodeofconduct_acknowledge = 'Acknowledge code of conduct signature'

signedcodeofconduct_activate = ContextDisplayName('Activating %s')

signedcodeofconduct_deactivate = ContextDisplayName('Deactivating %s')

sourcepackage_bugs = ContextDisplayName('Bugs in %s')

sourcepackage_builds = ContextTitle('Builds for %s')

sourcepackage_translate = ContextTitle('Help translate %s')

sourcepackage_changelog = 'Source package changelog'

sourcepackage_filebug = ContextTitle("Report a bug about %s")

sourcepackage_gethelp = ContextTitle('Help and support options for %s')

sourcepackage_hctstatus = ContextTitle('%s HCT status')

def sourcepackage_index(context, view):
    return '%s source packages' % context.distrorelease.title

sourcepackage_packaging = ContextTitle('Define upstream series for %s')

sourcepackage_translate = ContextTitle('Help translate %s')

sourcepackage_translations = ContextTitle(
    'Rosetta translation templates for %s')

sourcepackagenames_index = 'Source package name set'

sourcepackagerelease_index = ContextTitle('Source package %s')

def sourcepackages(context, view):
    return '%s source packages' % context.distrorelease.title

sourcepackages_comingsoon = 'Coming soon'

sources_index = 'Bazaar: Upstream revision control imports to Bazaar'

sourcesource_index = 'Upstream source import'

specification_add = 'Register a feature specification in Launchpad'

specification_addsubscriber = 'Subscribe someone else to this spec'

specification_linkbug = ContextTitle(
  u'Link specification \N{left double quotation mark}%s'
  u'\N{right double quotation mark} to a bug report')

specification_unlinkbugs = 'Remove links to bug reports'

specification_retargeting = 'Attach spec to a different product or distribution'

specification_superseding = 'Mark specification as superseded by another'

specification_goaldecide = 'Approve or decline specification goal'

specification_dependency = 'Create a specification dependency'

specification_deptree = 'Complete dependency tree'

specification_milestone = 'Target feature to milestone'

specification_people = 'Change specification assignee, drafter, and reviewer'

specification_priority = 'Change specification priority'

specification_distrorelease = ('Target specification at a distribution release')

specification_productseries = 'Target specification at a series'

specification_removedep = 'Remove a dependency'

specification_givefeedback = 'Clear feedback requests'

specification_requestfeedback = 'Request feedback on this specification'

specification_edit = 'Edit specification details'

specification_linksprint = 'Put specification on sprint agenda'

specification_status = 'Edit specification status'

specification_index = ContextTitle(smartquote('Feature specification: "%s"'))

specification_subscription = 'Subscribe to specification'

specification_queue = 'Queue specification for review'

specifications_index = ContextTitle('%s')

specificationgoal_specs = ContextTitle('List goals for %s')

specificationgoal_setgoals = ContextTitle('Set goals for %s')

def specificationsubscription_edit(context, view):
    return "Subscription of %s" % context.person.browsername

specificationtarget_documentation = ContextTitle('Documentation for %s')

specificationtarget_index = ContextTitle('Specification Listing for %s')

def specificationtarget_specs(context, view):
    return view.title

specificationtarget_roadmap = ContextTitle('Project plan for %s')

specificationtarget_assignments = ContextTitle('Specification assignments for %s')

specificationtarget_workload = ContextTitle('Feature workload in %s')

sprint_attend = ContextTitle('Register your attendance at %s')

sprint_edit = ContextTitle(smartquote('Edit "%s" details'))

sprint_index = ContextTitle('%s (sprint or meeting)')

sprint_new = 'Register a meeting or sprint in Launchpad'

sprint_register = 'Register someone to attend this meeting'

sprint_specs = ContextTitle('Specifications for %s')

sprint_settopics = ContextTitle('Review topics proposed for discussion at %s')

sprint_workload = ContextTitle('Workload at %s')

sprints_index = 'Meetings and sprints registered in Launchpad'

sprintspecification_decide = 'Consider spec for sprint agenda'

sprintspecification_admin = 'Approve specification for sprint agenda'

tickets_index = 'Launchpad tech support system'

ticket_add = ContextDisplayName('Request support with %s')

ticket_add_search = ContextDisplayName('Request support with %s')

ticket_bug = ContextId('Link support request #%s to a bug report')

ticket_edit = ContextId('Edit support request #%s details')

def ticket_index(context, view):
    text = (
        smartquote('%s support request #%d: "%s"') %
        (context.target.displayname, context.id, context.title))
    return text

ticket_history = ContextId('History of support request #%s')

ticket_linkbug = ContextId('Link support request #%s to a bug report')

ticket_makebug = ContextId('Create bug report based on request #%s')

ticket_reject = ContextId('Reject support request #%s')

ticket_unlinkbugs = ContextId('Remove bug links from request #%s')

ticket_reopen = ContextId('Reopen request #%s')

ticket_subscription = ContextId('Subscription to request #%s')

def tickettarget_tickets(context, view):
    return view.title

standardshipitrequests_index = 'Standard ShipIt options'

standardshipitrequest_new = 'Create a new standard option'

standardshipitrequest_edit = 'Edit standard option'

team_addmember = ContextBrowsername('Add members to %s')

team_edit = 'Edit team information'

team_editemail = ContextDisplayName('%s contact e-mail address')

team_index = ContextBrowsername(smartquote('"%s" team in Launchpad'))

team_editproposed = ContextBrowsername('Proposed members of %s')

team_join = ContextBrowsername('Join %s')

team_leave = ContextBrowsername('Leave %s')

team_members = ContextBrowsername(smartquote('"%s" members'))

def teammembership_index(context, view):
    return smartquote("%s's membership status in %s") % (
        context.person.browsername, context.team.browsername)

team_newpoll = ContextTitle('New poll for team %s')

team_polls = ContextTitle('Polls for team %s')

template_auto_add = 'Launchpad Auto-Add Form'

template_auto_edit = 'Launchpad Auto-Edit Form'

template_edit = 'EXAMPLE EDIT TITLE'

template_index = '%EXAMPLE TITLE'

template_new = 'EXAMPLE NEW TITLE'

ticket_listing = ContextDisplayName("Support requests for %s")

tickettarget_manage_supportcontacts = ContextTitle("Support contact for %s")

translationgroup_index = ContextTitle(smartquote('"%s" Rosetta translation group'))

translationgroup_appoint = ContextTitle(
    smartquote('Appoint a new translator to "%s"'))

translationgroups_index = 'Rosetta translation groups'

translationimportqueueentry_index = 'Translation import queue entry'

translationimportqueue_index = 'Translation import queue'

translationimportqueue_blocked = 'Translation import queue - Blocked'

unauthorized = 'Error: Not authorized'
