# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Product series interfaces."""

__metaclass__ = type

__all__ = [
    'IProductSeries',
    'IProductSeriesSet',
    'IProductSeriesSourceAdmin',
    ]

import re

from zope.schema import  Choice, Datetime, Int, Object, Text, TextLine
from zope.interface import Interface, Attribute

from CVS.protocol import CVSRoot, CvsRootError

from canonical.launchpad.fields import ContentNameField
from canonical.launchpad.interfaces import (
    IBranch, IBugTarget, ISpecificationGoal, IHasOwner, IHasDrivers,
    validate_url)

from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.validators.name import name_validator
from canonical.launchpad import _


class ProductSeriesNameField(ContentNameField):

    errormessage = _("%s is already in use by another series.")

    @property
    def _content_iface(self):
        return IProductSeries

    def _getByName(self, name):
        if self._content_iface.providedBy(self.context):
            return self.context.product.getSeries(name)
        else:
            return self.context.getSeries(name)


def validate_cvs_root(cvsroot):
    try:
        root = CVSRoot(cvsroot)
    except CvsRootError, e:
        raise LaunchpadValidationError(str(e))
    if root.method == 'local':
        raise LaunchpadValidationError('Local CVS roots are not allowed.')
    if root.hostname.count('.') == 0:
        raise LaunchpadValidationError(
            'Please use a fully qualified host name.')
    return True

def validate_cvs_module(cvsmodule):
    valid_module = re.compile('^[a-zA-Z][a-zA-Z0-9_/.+-]*$')
    if not valid_module.match(cvsmodule):
        raise LaunchpadValidationError(
            'The CVS module contains illegal characters.')
    if cvsmodule == 'CVS':
        raise LaunchpadValidationError('A CVS module can not be called "CVS".')
    return True
    
def validate_cvs_branch(branch):
    if branch and re.match('^[a-zA-Z][a-zA-Z0-9_-]*$', branch):
        return True
    else:
        raise LaunchpadValidationError('Your CVS branch name is invalid.')

def validate_svn_repo(repo):
    if validate_url(repo, ["http", "https", "svn", "svn+ssh"]):
        return True
    else:
        raise LaunchpadValidationError(
            'Please give valid Subversion server details.')

def validate_release_glob(value):
    if validate_url(value, ["http", "https", "ftp"]):
        return True
    else:
        raise LaunchpadValidationError('Invalid release URL pattern.')


class IProductSeries(IHasDrivers, IHasOwner, IBugTarget, ISpecificationGoal):
    """A series of releases. For example '2.0' or '1.3' or 'dev'."""
    # XXX Mark Shuttleworth 14/10/04 would like to get rid of id in
    # interfaces, as soon as SQLobject allows using the object directly
    # instead of using object.id.
    id = Int(title=_('ID'))
    # field names
    product = Choice(title=_('Product'), required=True, vocabulary='Product')
    name = ProductSeriesNameField(title=_('Name'), required=True,
        description=_("The name of the series is a short, unique name "
        "that identifies it, being used in URLs. It must be all "
        "lowercase, with no special characters. For example, '2.0' "
        "or 'trunk'."), constraint=name_validator)
    datecreated = Datetime(title=_('Date Registered'), required=True,
        readonly=True)
    owner = Choice(title=_('Owner'), required=True, vocabulary='ValidOwner',
        description=_('Product owner, either a valid Person or Team'))
    driver = Choice(
        title=_("Driver"),
        description=_(
            "The person or team responsible for decisions about features "
            "and bugs that will be targeted to this series. If you don't "
            "nominate someone here, then the owner of this series will "
            "automatically have those permissions."),
        required=False, vocabulary='ValidPersonOrTeam')
    title = Attribute('Title')
    displayname = Attribute(
        'Display name, in this case we have removed the underlying '
        'database field, and this attribute just returns the name.')
    summary = Text(title=_("Summary"), 
        description=_('A single paragraph introduction or overview '
        'of this series. For example: "The 2.0 series of Apache represents '
        'the current stable series, and is recommended for all new '
        'deployments".'), required=True)

    releases = Attribute("An iterator over the releases in this "
        "Series, sorted with latest release first.")
    potemplates = Attribute(
        _("Return an iterator over this productrelease's PO templates."))
    currentpotemplates = Attribute(
        _("Return an iterator over this productrelease's PO templates that "
          "have the 'iscurrent' flag set'."))
    packagings = Attribute("An iterator over the Packaging entries "
        "for this product series.")
    specifications = Attribute("The specifications targeted to this "
        "product series.")
    sourcepackages = Attribute(_("List of distribution packages for this "
        "product series"))

    milestones = Attribute(
        'The milestones associated with this series.')

    drivers = Attribute(
        'A list of the people or teams who are drivers for this series. '
        'This list is made up of any drivers or owners from this '
        'ProductSeries, the Product and if it exists, the relevant '
        'Project.')

    # XXX: 2006-09-05 jamesh
    # While it would be more sensible to call this ProductSeries.branch,
    # I've used this name to make sure code that works with the
    # vcs-imports branch (which used to be called branch) doesn't use
    # this attribute by accident.
    
    series_branch = Choice(
        title=_('Series Branch'),
        vocabulary='Branch',
        readonly=True,
        description=_("The Bazaar branch for this series."))
        
    user_branch = Choice(
        title=_('Branch'),
        vocabulary='Branch',
        required=False,
        description=_("The Bazaar branch for this series.  Leave blank "
                      "if this series is not maintained in Bazaar."))

    def getRelease(version):
        """Get the release in this series that has the specified version.
        Return None is there is no such release.
        """

    def getPackage(distrorelease):
        """Return the SourcePackage for this productseries in the supplied
        distrorelease. This will use a Packaging record if one exists, but
        it will also work through the ancestry of the distrorelease to try
        to find a Packaging entry that may be relevant."""

    def setPackaging(distrorelease, sourcepackagename, owner):
        """Create or update a Packaging record for this product series,
        connecting it to the given distrorelease and source package name.
        """

    def getPackagingInDistribution(distribution):
        """Return all the Packaging entries for this product series for the
        given distribution. Note that this only returns EXPLICT packaging
        entries, it does not look at distro release ancestry in the same way
        that IProductSeries.getPackage() does.
        """

    def getPOTemplate(name):
        """Return the POTemplate with this name for the series."""

    def newMilestone(name, dateexpected=None):
        """Create a new milestone for this DistroRelease."""

    # revision control items
    import_branch = Choice(
        title=_('Import Branch'),
        vocabulary='Branch',
        description=_("The Bazaar branch for this series imported from "
                      "upstream version control. Note that there may be "
                      "many branches associated with a given series, such "
                      "as the branches of individual tarball releases. "
                      "This branch is the real upstream code, mapped into "
                      "Bazaar from CVS or SVN."))
    importstatus = Attribute("The bazaar-import status of upstream "
        "revision control for this series. It can be NULL if we do not "
        "have any revision control data for this series, otherwise it "
        "will reflect our current status for importing and syncing the "
        "upstream code and publishing it as a Bazaar branch.")
    datelastsynced = Attribute("The date on which we last "
        "successfully synced the upstream RCS into the Bazaar branch "
        "in .branch.")
    syncinterval = Attribute("The time between sync attempts for this "
        "series. In some cases we might want to sync once a week, in "
        "others, several times per day.")
    rcstype = Choice(title=_("Type of RCS"),
        required=False, vocabulary='RevisionControlSystems',
        description=_("The type of revision control used for "
        "the upstream branch of this series. Can be CVS, SVN, BK or "
        "Arch."))
    cvsroot = TextLine(title=_("Repository root"), required=False,
        constraint=validate_cvs_root,
        description=_('Example: :pserver:anonymous@anoncvs.gnome.org:'
                      '/cvs/gnome'))
    cvsmodule = TextLine(title=_("Module"), required=False,
        constraint=validate_cvs_module)
    cvstarfileurl = Text(title=_("A URL where a tarball of the CVS "
        "repository can be found. This can sometimes be faster than "
        "trying to query the server for commit-by-commit data."))
    cvsbranch = TextLine(title=_("Branch name"), required=False,
        constraint=validate_cvs_branch,
        description=_('The branch representing the upstream codebase for '
                      'this product series.'))
    svnrepository = TextLine(title=_("Repository"), required=False,
        constraint=validate_svn_repo,
        description=_('The URL (Internet address) of the repository and '
                      'branch to be imported, in svn:// or http(s):// '
                      'format. This must be the correct upstream branch '
                      'for the trunk series of Evolution.'))
    # where are the tarballs released from this branch placed?
    releasefileglob = TextLine(title=_("Release URL pattern"),
        required=False, constraint=validate_release_glob,
        description=_('A URL pattern that matches releases that are part '
                      'of this series.  Launchpad automatically scans this '
                      'site to import new releases.  Example: '
                      'http://ftp.gnu.org/gnu/emacs/emacs-21.*.tar.gz'))
    releaseverstyle = Attribute("The version numbering style for this "
        "product series of releases.")
    dateautotested = Attribute("The date this upstream passed automatic "
        "testing.")
    datestarted = Attribute("The timestamp when we started the latest "
        "sync attempt on this upstream RCS.")
    datefinished = Attribute("The timestamp when the latest sync attempt "
        "on this upstream RCS finished.")
    dateprocessapproved = Attribute("The date when we approved processing "
        "of this upstream source.")
    datesyncapproved = Attribute("The date when we approved syncing of "
        "this upstream source into a public Bazaar branch.")

    def syncCertified():
        """is the series source sync enabled?"""

    def autoSyncEnabled():
        """is the series source enabled for automatic syncronisation?"""

    def autoTestFailed():
        """has the series source failed automatic testing by roomba?"""


class IProductSeriesSourceAdmin(Interface):
    """Administrative interface to approve syncing on a Product Series
    upstream codebase, publishing it as Bazaar branch."""

    def certifyForSync():
        """enable this to sync"""

    def enableAutoSync():
        """enable this series RCS for automatic baz syncronisation"""


class IProductSeriesSet(Interface):
    """Interface representing the set of ProductSeries."""

    def __getitem__(series_id):
        """Return the ProductSeries with the given id.

        Raise NotFoundError if there is no such series.
        """

    def get(series_id, default=None):
        """Return the ProductSeries with the given id.

        Return the default value if there is no such series.
        """

    def search(ready=None, text=None, forimport=None, importstatus=None,
               start=None, length=None):
        """return a list of series matching the arguments, which are passed
        through to _querystr to generate the query."""

    def importcount(status=None):
        """Return the number of series that are in the process of being
        imported and published as baz branches. If status is None then all
        the statuses are included, otherwise the count reflects the number
        of branches with that importstatus."""

    def getByCVSDetails(cvsroot, cvsmodule, cvsbranch, default=None):
        """Return the ProductSeries with the given CVS details.

        Return the default value if there is no ProductSeries with the 
        given details.
        """

    def getBySVNDetails(svnrepository, default=None):
        """Return the ProductSeries with the given SVN details.

        Return the default value if there is no ProductSeries with the
        given details.
        """
