# Copyright 2004 Canonical Ltd.  All rights reserved.
#
"""Database schemas

Use them like this:

  from canonical.lp.dbschema import BugTaskSeverity

  print "SELECT * FROM Bug WHERE Bug.severity='%d'" % BugTaskSeverity.CRITICAL

"""
__metaclass__ = type

# MAINTAINER:
#
# When you add a new DBSchema subclass, add its name to the __all__ tuple
# below.
#
# If you do not do this, from canonical.lp.dbschema import * will not
# work properly, and the thing/lp:SchemaClass will not work properly.

# The DBSchema subclasses should be in alphabetical order, listed after
# EnumCol and Item.  Please keep it that way.
__all__ = (
'EnumCol',
'Item',
'DBSchema',
# DBSchema types follow.
'ArchArchiveType',
'BinaryPackageFileType',
'BinaryPackageFormat',
'BountyDifficulty',
'BountyStatus',
'BranchRelationships',
'BranchLifecycleStatus',
'BranchReviewStatus',
'BugBranchStatus',
'BugTaskStatus',
'BugAttachmentType',
'BugTrackerType',
'BugExternalReferenceType',
'BugInfestationStatus',
'BugTaskPriority',
'BugRelationship',
'BugTaskSeverity',
'BuildStatus',
'CodereleaseRelationships',
'CveStatus',
'DistributionReleaseStatus',
'EmailAddressStatus',
'GPGKeyAlgorithm',
'ImportTestStatus',
'ImportStatus',
'LoginTokenType',
'ManifestEntryType',
'ManifestEntryHint',
'MirrorFreshness',
'MirrorContent',
'MirrorPulseType',
'MirrorSpeed',
'MirrorStatus',
'PackagePublishingPriority',
'PackagePublishingStatus',
'PackagePublishingPocket',
'PackagingType',
'PollAlgorithm',
'PollSecrecy',
'ProjectRelationship',
'ProjectStatus',
'RevisionControlSystems',
'RosettaFileFormat',
'RosettaImportStatus',
'RosettaTranslationOrigin',
'ShipItArchitecture',
'ShipItDistroRelease',
'ShipItFlavour',
'ShippingService',
'SourcePackageFileType',
'SourcePackageFormat',
'SourcePackageRelationships',
'SourcePackageUrgency',
'SpecificationDelivery',
'SpecificationGoalStatus',
'SpecificationPriority',
'SpecificationSort',
'SpecificationStatus',
'SprintSpecificationStatus',
'SSHKeyType',
'TextDirection',
'TicketPriority',
'TicketStatus',
'TeamMembershipStatus',
'TeamSubscriptionPolicy',
'TranslationPriority',
'TranslationPermission',
'TranslationValidationStatus',
'DistroReleaseQueueStatus',
'DistroReleaseQueueCustomFormat',
'UpstreamFileType',
'UpstreamReleaseVersionStyle',
)

from canonical.database.constants import DEFAULT

from zope.interface.advice import addClassAdvisor
import sys
import warnings

from sqlobject.col import SOCol, Col
from sqlobject.include import validators
import sqlobject.constraints as consts


class SODBSchemaEnumCol(SOCol):

    def __init__(self, **kw):
        self.schema = kw.pop('schema')
        if not issubclass(self.schema, DBSchema):
            raise TypeError('schema must be a DBSchema: %r' % self.schema)
        SOCol.__init__(self, **kw)
        self.validator = validators.All.join(
            DBSchemaValidator(schema=self.schema), self.validator)

    def autoConstraints(self):
        return [consts.isInt]

    def _sqlType(self):
        return 'INT'


class DBSchemaEnumCol(Col):
    baseClass = SODBSchemaEnumCol


class DBSchemaValidator(validators.Validator):

    def __init__(self, **kw):
        self.schema = kw.pop('schema')
        validators.Validator.__init__(self, **kw)

    def fromPython(self, value, state):
        """Convert from DBSchema Item to int.

        >>> validator = DBSchemaValidator(schema=BugTaskStatus)
        >>> validator.fromPython(BugTaskStatus.FIXCOMMITTED, None)
        25
        >>> validator.fromPython(ImportTestStatus.NEW, None)
        Traceback (most recent call last):
        ...
        TypeError: DBSchema Item from wrong class, <class 'canonical.lp.dbschema.ImportTestStatus'> != <class 'canonical.lp.dbschema.BugTaskStatus'>
        >>>

        """
        if value is None:
            return None
        if isinstance(value, int):
            raise TypeError(
                'Need to set a dbschema Enum column to a dbschema Item,'
                ' not an int')
        # Allow this to work in the presence of security proxies.
        ##if not isinstance(value, Item):
        if value is DEFAULT:
            return value
        if value.__class__ != Item:
            # We use repr(value) because if it's a tuple (yes, it has been
            # seen in some cases) then the interpolation would swallow that
            # fact, confusing poor programmers like Daniel.
            raise TypeError('Not a DBSchema Item: %s' % repr(value))
        # Using != rather than 'is not' in order to cope with Security Proxy
        # proxied items and their schemas.
        if value.schema != self.schema:
            raise TypeError('DBSchema Item from wrong class, %r != %r' % (
                value.schema, self.schema))
        return value.value

    def toPython(self, value, state):
        """Convert from int to DBSchema Item.

        >>> validator = DBSchemaValidator(schema=BugTaskStatus)
        >>> validator.toPython(25, None) is BugTaskStatus.FIXCOMMITTED
        True

        """
        if value is None:
            return None
        if value is DEFAULT:
            return value
        return self.schema.items[value]

EnumCol = DBSchemaEnumCol

def docstring_to_title_descr(string):
    """When given a classically formatted docstring, returns a tuple
    (title,x description).

    >>> class Foo:
    ...     '''
    ...     Title of foo
    ...
    ...     Description of foo starts here.  It may
    ...     spill onto multiple lines.  It may also have
    ...     indented examples:
    ...
    ...       Foo
    ...       Bar
    ...
    ...     like the above.
    ...     '''
    ...
    >>> title, descr = docstring_to_title_descr(Foo.__doc__)
    >>> print title
    Title of foo
    >>> for num, line in enumerate(descr.splitlines()):
    ...    print num, line
    ...
    0 Description of foo starts here.  It may
    1 spill onto multiple lines.  It may also have
    2 indented examples:
    3 
    4   Foo
    5   Bar
    6 
    7 like the above.

    """
    lines = string.splitlines()
    # title is the first non-blank line
    for num, line in enumerate(lines):
        line = line.strip()
        if line:
            title = line
            break
    else:
        raise ValueError
    assert not lines[num+1].strip()
    descrlines = lines[num+2:]
    descr1 = descrlines[0]
    indent = len(descr1) - len(descr1.lstrip())
    descr = '\n'.join([line[indent:] for line in descrlines])
    return title, descr


class OrderedMapping:

    def __init__(self, mapping):
        self.mapping = mapping

    def __getitem__(self, key):
        if key in self.mapping:
            return self.mapping[key]
        else:
            for k, v in self.mapping.iteritems():
                if v.name == key:
                    return v
            raise KeyError, key

    def __iter__(self):
        L = self.mapping.items()
        L.sort()
        for k, v in L:
            yield v


class ItemsDescriptor:

    def __get__(self, inst, cls=None):
        return OrderedMapping(cls._items)


class Item:
    """An item in an enumerated type.

    An item has a name, title and description.  It also has an integer value.
    """

    def __init__(self, value, title, description=None):
        frame = sys._getframe(1)
        locals = frame.f_locals

        # Try to make sure we were called from a class def
        if (locals is frame.f_globals) or ('__module__' not in locals):
            raise TypeError("Item can be used only from a class definition.")

        addClassAdvisor(self._setClassFromAdvice)
        try:
            self.value = int(value)
        except ValueError:
            raise TypeError("value must be an int, not %r" % (value,))
        if description is None:
            self.title, self.description = docstring_to_title_descr(title)
        else:
            self.title = title
            self.description = description

    def _setClassFromAdvice(self, cls):
        self.schema = cls
        names = [k for k, v in cls.__dict__.iteritems() if v is self]
        assert len(names) == 1
        self.name = names[0]
        if not hasattr(cls, '_items'):
            cls._items = {}
        cls._items[self.value] = self
        return cls

    def __int__(self):
        raise TypeError("Cannot cast Item to int.  Use item.value instead.")

    def __str__(self):
        return str(self.value)

    def __repr__(self):
        return "<Item %s (%d) from %s>" % (self.name, self.value, self.schema)

    def __sqlrepr__(self, dbname):
        return repr(self.value)

    def __eq__(self, other, stacklevel=2):
        if isinstance(other, int):
            warnings.warn('comparison of DBSchema Item to an int: %r' % self,
                stacklevel=stacklevel)
            return False
        # Cannot use isinstance, because 'other' might be security proxied.
        ##elif isinstance(other, Item):
        elif other.__class__ == Item:
            return self.value == other.value and self.schema == other.schema
        else:
            return False

    def __ne__(self, other):
        return not self.__eq__(other, stacklevel=3)

    def __hash__(self):
        return self.value

# TODO: make a metaclass for dbschemas that looks for ALLCAPS attributes
#       and makes the introspectible.
#       Also, makes the description the same as the docstring.
#       Also, sets the name on each Item based on its name.
#       (Done by crufty class advice at present.)
#       Also, set the name on the DBSchema according to the class name.
#
#       Also, make item take just one string, optionally, and parse that
#       to make something appropriate.

class DBSchema:
    """Base class for database schemas."""

    # TODO: Make description a descriptor that automatically refers to the
    #       docstring.
    description = "See body of class's __doc__ docstring."
    title = "See first line of class's __doc__ docstring."
    name = "See lower-cased-spaces-inserted class name."
    items = ItemsDescriptor()


class ArchArchiveType(DBSchema):
    """Arch Archive Type

    An arch archive can be read only, or it might be an archive
    into which we can push new changes, or it might be a mirror
    into which we can only push changes from the upstream. This schema
    documents those states.
    """

    READWRITE = Item(0, """
        ReadWrite Archive

        This archive can be written to with new changesets, it
        is an archive which we "own" and therefor are free to
        write changesets into. Note that an archive which has
        been created for upstream CVS mirroring, for example, would
        be "readwrite" because we need to be able to create new
        changesets in it as we mirror the changes in the CVS
        repository.
        """)

    READONLY = Item(1, """
        Read Only Archive

        An archive in the "readonly" state can only be published
        and read from, it cannot be written to.
        """)

    MIRRORTARGET = Item(2, """
        Mirror Target

        We can write into this archive, but we can only write
        changesets which have actually come from the upstream
        arch archive of which this is a mirror.
        """)


class BinaryPackageFormat(DBSchema):
    """Binary Package Format

    Launchpad tracks a variety of binary package formats. This schema
    documents the list of binary package formats that are supported
    in Launchpad.
    """

    DEB = Item(1, """
        Ubuntu Package

        This is the binary package format used by Ubuntu and all similar
        distributions. It includes dependency information to allow the
        system to ensure it always has all the software installed to make
        any new package work correctly.  """)

    UDEB = Item(2, """
        Ubuntu Installer Package

        This is the binary package format use by the installer in Ubuntu and
        similar distributions.  """)

    EBUILD = Item(3, """
        Gentoo Ebuild Package

        This is the Gentoo binary package format. While Gentoo is primarily
        known for being a build-it-from-source-yourself kind of
        distribution, it is possible to exchange binary packages between
        Gentoo systems.  """)

    RPM = Item(4, """
        RPM Package

        This is the format used by Mandrake and other similar distributions.
        It does not include dependency tracking information.  """)


class ImportTestStatus(DBSchema):
    """An Arch Import Autotest Result

    This enum tells us whether or not a sourcesource has been put through an
    attempted import.
    """

    NEW = Item(0, """
        Untested

        The sourcesource has not yet been tested by the autotester.
        """)

    FAILED = Item(1, """
        Failed

        The sourcesource failed to import cleanly.
        """)

    SUCCEEDED = Item(2, """
        Succeeded

        The sourcesource was successfully imported by the autotester.
        """)

class BugTrackerType(DBSchema):
    """The Types of BugTracker Supported by Launchpad

    This enum is used to differentiate between the different types of Bug
    Tracker that are supported by Malone in the Launchpad.
    """

    BUGZILLA = Item(1, """
        Bugzilla

        The godfather of open source bug tracking, the Bugzilla system was
        developed for the Mozilla project and is now in widespread use. It
        is big and ugly but also comprehensive.
        """)

    DEBBUGS = Item(2, """
        Debbugs

        The debbugs tracker is email based, and allows you to treat every
        bug like a small mailing list.
        """)

    ROUNDUP = Item(3, """
        Roundup

        Roundup is a lightweight, customisable and fast web/email based bug
        tracker written in Python.
        """)

    TRAC = Item(4, """
        Trac

        Trac is an enhanced wiki and issue tracking system for
        software development projects.
        """)

    SOURCEFORGE = Item(5, """
        SourceForge

        SourceForge is a project hosting service which includes bug,
        support and request tracking.
        """)


class CveStatus(DBSchema):
    """The Status of this item in the CVE Database

    When a potential problem is reported to the CVE authorities they assign
    a CAN number to it. At a later stage, that may be converted into a CVE
    number. This indicator tells us whether or not the issue is believed to
    be a CAN or a CVE.
    """

    CANDIDATE = Item(1, """
        Candidate

        The vulnerability is a candidate, it has not yet been confirmed and
        given "Entry" status.
        """)

    ENTRY = Item(2, """
        Entry

        This vulnerability or threat has been assigned a CVE number, and is
        fully documented. It has been through the full CVE verification
        process.
        """)

    DEPRECATED = Item(3, """
        Deprecated

        This entry is deprecated, and should no longer be referred to in
        general correspondence. There is either a newer entry that better
        defines the problem, or the original candidate was never promoted to
        "Entry" status.
        """)


class ProjectStatus(DBSchema):
    """A Project Status

    This is an enum of the values that Project.status can assume.
    Essentially it indicates whether or not this project has been reviewed,
    and if it has whether or not it passed review and should be considered
    active.
    """

    NEW = Item(1, """
        New

        This project is new and has not been reviewed.
        """)

    ACTIVE = Item(2, """
        Active

        This Project has been reviewed and is considered active in the
        launchpad.""")

    DISABLED = Item(3, """
        Disabled

        This project has been reviewed, and has been disabled. Typically
        this is because the contents appear to be bogus. Such a project
        should not show up in searches etc.""")


class ManifestEntryType(DBSchema):
    """A Sourcerer Manifest.

    This is a list of branches that are brought together to make up a source
    package. Each branch can be included in the package in a number of
    different ways, and the Manifest Entry Type tells sourcerer how to bring
    that branch into the package.
    """

    DIR = Item(1, """
        A Directory

        This is a special case of Manifest Entry Type, and tells
        sourcerer simply to create an empty directory with the given name.
        """)

    COPY = Item(2, """
        Copied Source code

        This branch will simply be copied into the source package at
        a specified location. Typically this is used where a source
        package includes chunks of code such as libraries or reference
        implementation code, and builds it locally for static linking
        rather than depending on a system-installed shared library.
        """)

    FILE = Item(3, """
        Binary file

        This is another special case of Manifest Entry Type that tells
        sourcerer to create a branch containing just the file given.
        """)

    TAR = Item(4, """
        A Tar File

        This branch will be tarred up and installed in the source
        package as a tar file. Typically, the package build system
        will know how to untar that code and use it during the build.
        """)

    ZIP = Item(5, """
        A Zip File

        This branch will be zipped up and installed in the source
        package as a zip file. Typically, the package build system
        will know how to unzip that code and use it during the build.
        """)

    PATCH = Item(6, """
        Patch File

        This branch will be brought into the source file as a patch
        against another branch. Usually, the patch is stored in the
        "patches" directory, then applied at build time by the source
        package build scripts.
        """)


class ManifestEntryHint(DBSchema):
    """Hint as to purpose of a ManifestEntry.

    Manifests, used by both HCT and Sourcerer, are made up of a collection
    of Manifest Entries.  Each entry refers to a particular component of
    the source package built by the manifest, usually each having a different
    branch or changeset.  A Manifest Entry Hint can be assigned to suggest
    what the purpose of the entry is.
    """

    ORIGINAL_SOURCE = Item(1, """
        Original Source

        This is the original source code of the source package, and in the
        absence of any Patch Base, the parent of any new patch branches
        created.
        """)

    PATCH_BASE = Item(2, """
        Patch Base

        This is an entry intended to serve as the base for any new patches
        created and added to the source package.  It is often a patch itself,
        or a virtual branch.  If not present, the Original Source is used
        instead.
        """)

    PACKAGING = Item(3, """
        Packaging

        This is the packaging meta-data for the source package, usually
        the entry that becomes the debian/ directory in the case of Debian
        source packages or the spec file in the case of RPMs.
        """)


class PackagingType(DBSchema):
    """Source packages.

    Source packages include software from one or more Upstream open source
    projects. This schema shows the relationship between a source package
    and the upstream open source products that it might incorporate. This
    schema is used in the Packaging table.
    """

    PRIME = Item(1, """
        Primary Product

        This is the primary product packaged in this source package. For
        example, a source package "apache2" would have a "prime" Packaging
        relationship with the "apache2" product from the Apache Project.
        The product and package don't have to have the same name.
        """)

    INCLUDES = Item(2, """
        SourcePackage Includes Product

        This source package includes some part or all of the product. For
        example, the "cadaver" source package has an "includes" Packaging
        relationship with the libneon product.
        """)

##XXX: (gpg+dbschema) cprov 20041004
## the data structure should be rearranged to support 4 field
## needed: keynumber(1,16,17,20), keyalias(R,g,D,G), title and description
class GPGKeyAlgorithm(DBSchema):
    """
    GPG Compilant Key Algorithms Types:

    1 : "R", # RSA
    16: "g", # ElGamal
    17: "D", # DSA
    20: "G", # ElGamal, compromised

    FIXME
    Rewrite it according the experimental API retuning also a name attribute
    tested on 'algorithmname' attribute

    """

    R = Item(1, """
        R

        RSA""")

    g = Item(16, """
        g

        ElGamal""")

    D = Item(17, """
        D

        DSA""")

    G = Item(20, """
        G

        ElGamal, compromised""")


class BugBranchStatus(DBSchema):
    """The status of a bugfix branch."""

    ABANDONED = Item(10, """
        Abandoned Attempt

        A fix for this bug is no longer being worked on in this
        branch.
        """)

    INPROGRESS = Item(20, """
        Fix In Progress

        Development to fix this bug is currently going on in this
        branch.
        """)

    FIXAVAILABLE = Item(30, """
        Fix Available

        This branch contains a potentially useful fix for this bug.
        """)

    BESTFIX = Item(40, """
        Best Fix Available

        This branch contains a fix agreed upon by the community as
        being the best available branch from which to merge to fix
        this bug.
        """)


class BranchRelationships(DBSchema):
    """Branch relationships.

    In Arch, everything is a branch. Your patches are all branches. Your
    brother, sister and hifi system are all branches. If it moves, it's
    a branch. And Bazaar (the Arch subsystem of Launchpad) tracks the
    relationships between those branches.
    """

    TRACKS = Item(1, """
        Subject Branch Tracks Object Branch

        The source branch "tracks" the destination branch. This means that
        we generally try to merge changes made in branch B into branch A.
        For example, if we have inlcuded a fix-branch into a source
        package, and there is an upstream for that fix-branch, then we will
        try to make our fix-branch "track" the upstream fix, so that our
        package inherits the latest fixes.
        """)

    CONTINUES = Item(2, """
        Subject Branch is a continuation of Object Branch

        The term "continuation" is an Arch term meaning that the branch was
        tagged from another one.
        """)

    RELEASES = Item(3, """
        Subject Branch is a "Release Branch" of Object Branch

        A "release branch" is a branch that is designed to capture the extra
        bits that are added to release tarballs and which are not in the
        project revision control system. For example, when a product is
        released, the project administrators will typically tag the
        code in the revision system, then pull that code into a clean
        directory. The files at this stage represent what is in the
        revision control system. They will often then add other files, for
        example files created by the Gnu Automake and Autoconf system,
        before tarring up the directory and pushing that tarball out as the
        release. Those extra files are included in a release branch.
        """)

    FIXES = Item(4, """
        Subject Branch is a fix for Object Branch

        This relationship indicates that Subject Branch includes a fix
        for the Object Branch. It is used to indicate that Subject
        Branch's main purpose is for the development of a fix to a
        specific issue in Object Branch. The description and title of the
        Subject will usually include information about the issue and the
        fix. Such fixes are usually merged when the fix is considered
        stable.
        """)

    PORTS = Item(5, """
        Subject Branch is a porting branch of B

        This relationship indicates that Subject Branch is a port of
        Object Branch to a different architecture or operating system.
        Such changes will usually be merged back at a future date when
        they are considered stable.
        """)

    ENHANCES = Item(6, """
        Subject Branch contains a new feature for Object Branch

        This relationship indicates that Subject Branch is a place
        where developers are working on a new feature for the
        software in Object Branch. Usually such a feature is merged
        at some future date when the code is considered stable.
        Subject The Branch.description will usually describe the
        feature being implemented.
        """)

    FORKS = Item(7, """
        The Subject Branch is a For of the Object Branch

        Sometimes the members of an open source project cannot agree on
        the direction a project should take, and the project forks. In
        this case, one group will "fork" the codebase and start work on a
        new version of the product which will likely not be merged. That
        new version is a "fork" of the original code.
        """)


class EmailAddressStatus(DBSchema):
    """Email Address Status

    Launchpad keeps track of email addresses associated with a person. They
    can be used to login to the system, or to associate an Arch changeset
    with a person, or to associate a bug system email message with a person,
    for example.
    """

    NEW = Item(1, """
        New Email Address

        This email address has had no validation associated with it. It
        has just been created in the system, either by a person claiming
        it as their own, or because we have stored an email message or
        arch changeset including that email address and have created
        a phantom person and email address to record it. WE SHOULD
        NEVER EMAIL A "NEW" EMAIL.
        """)

    VALIDATED = Item(2, """
        Validated Email Address

        We have proven that the person associated with this email address
        can read email sent to this email address, by sending a token
        to that address and getting the appropriate response from that
        person.
        """)

    OLD = Item(3, """
        Old Email Address

        The email address was validated for this person, but is now no
        longer accessible or in use by them. We should not use this email
        address to login that person, nor should we associate new incoming
        content from that email address with that person.
        """)

    PREFERRED = Item(4, """
        Preferred Email Address

        The email address was validated and is the person's choice for
        receiving notifications from Launchpad.
        """)

class TeamMembershipStatus(DBSchema):
    """TeamMembership Status

    According to the policies specified by each team, the membership status of
    a given member can be one of multiple different statuses. More information
    can be found in the TeamMembership spec.
    """

    PROPOSED = Item(1, """
        Proposed

        You are a proposed member of this team. To become an active member your
        subscription has to bo approved by one of the team's administrators.
        """)

    APPROVED = Item(2, """
        Approved

        You are an active member of this team.
        """)

    ADMIN = Item(3, """
        Administrator

        You are an administrator of this team.
        """)

    DEACTIVATED = Item(4, """
        Deactivated

        Your subscription to this team has been deactivated.
        """)

    EXPIRED = Item(5, """
        Expired

        Your subscription to this team is expired.
        """)

    DECLINED = Item(6, """
        Declined

        Your proposed subscription to this team has been declined.
        """)


class TeamSubscriptionPolicy(DBSchema):
    """Team Subscription Policies

    The policies that apply to a team and specify how new subscriptions must
    be handled. More information can be found in the TeamMembershipPolicies
    spec.
    """

    MODERATED = Item(1, """
        Moderated Team

        All subscriptions for this team are subjected to approval by one of
        the team's administrators.
        """)

    OPEN = Item(2, """
        Open Team

        Any user can join and no approval is required.
        """)

    RESTRICTED = Item(3, """
        Restricted Team

        New members can only be added by one of the team's administrators.
        """)


class ProjectRelationship(DBSchema):
    """Project Relationship

    Launchpad tracks different open source projects, and the relationships
    between them. This schema is used to describe the relationship between
    two open source projects.
    """

    AGGREGATES = Item(1, """
        Subject Project Aggregates Object Project

        Some open source projects are in fact an aggregation of several
        other projects. For example, the Gnome Project aggregates
        Gnumeric, Abiword, EOG, and many other open source projects.
        """)

    SIMILAR = Item(2, """
        Subject Project is Similar to Object Project

        Often two different groups will start open source projects
        that are similar to one another. This relationship is used
        to describe projects that are similar to other projects in
        the system.
        """)


class DistributionReleaseStatus(DBSchema):
    """Distribution Release Status

    A DistroRelease (warty, hoary, or grumpy for example) changes state
    throughout its development. This schema describes the level of
    development of the distrorelease. The typical sequence for a
    distrorelease is to progress from experimental to development to
    frozen to current to supported to obsolete, in a linear fashion.
    """

    EXPERIMENTAL = Item(1, """
        Experimental

        This distrorelease contains code that is far from active
        release planning or management. Typically, distroreleases
        that are beyond the current "development" release will be
        marked as "experimental". We create those so that people
        have a place to upload code which is expected to be part
        of that distant future release, but which we do not want
        to interfere with the current development release.
        """)

    DEVELOPMENT = Item(2, """
        Active Development

        The distrorelease that is under active current development
        will be tagged as "development". Typically there is only
        one active development release at a time. When that freezes
        and releases, the next release along switches from "experimental"
        to "development".
        """)

    FROZEN = Item(3, """
        Pre-release Freeze

        When a distrorelease is near to release the administrators
        will freeze it, which typically means that new package uploads
        require significant review before being accepted into the
        release.
        """)

    CURRENT = Item(4, """
        Current Stable Release

        This is the latest stable release. Normally there will only
        be one of these for a given distribution.
        """)

    SUPPORTED = Item(5, """
        Supported

        This distrorelease is still supported, but it is no longer
        the current stable release. In Ubuntu we normally support
        a distrorelease for 2 years from release.
        """)

    OBSOLETE = Item(6, """
        Obsolete

        This distrorelease is no longer supported, it is considered
        obsolete and should not be used on production systems.
        """)


class UpstreamFileType(DBSchema):
    """Upstream File Type

    When upstream open source project release a product they will
    include several files in the release. All of these files are
    stored in Launchpad (we throw nothing away ;-). This schema
    gives the type of files that we know about.
    """

    CODETARBALL = Item(1, """
        Code Release Tarball

        This file contains code in a compressed package like
        a tar.gz or tar.bz or .zip file.
        """)

    README = Item(2, """
        README File

        This is a README associated with the upstream
        release. It might be in .txt or .html format, the
        filename would be an indicator.
        """)

    RELEASENOTES = Item(3, """
        Release Notes

        This file contains the release notes of the new
        upstream release. Again this could be in .txt or
        in .html format.
        """)

    CHANGELOG = Item(4, """
        ChangeLog File

        This file contains information about changes in this
        release from the previous release in the series. This
        is usually not a detailed changelog, but a high-level
        summary of major new features and fixes.
        """)


class SourcePackageFormat(DBSchema):
    """Source Package Format

    Launchpad supports distributions that use source packages in a variety
    of source package formats. This schema documents the types of source
    package format that we understand.
    """

    DPKG = Item(1, """
        The DEB Format

        This is the source package format used by Ubuntu, Debian, Linspire
        and similar distributions.
        """)

    RPM = Item(2, """
        The RPM Format

        This is the format used by Red Hat, Mandrake, SUSE and other similar
        distributions.
        """)

    EBUILD = Item(3, """
        The Ebuild Format

        This is the source package format used by Gentoo.
        """)


class SourcePackageUrgency(DBSchema):
    """Source Package Urgency

    When a source package is released it is given an "urgency" which tells
    distributions how important it is for them to consider bringing that
    package into their archives. This schema defines the possible values
    for source package urgency.
    """

    LOW = Item(1, """
        Low Urgency

        This source package release does not contain any significant or
        important updates, it might be a cleanup or documentation update
        fixing typos and speling errors, or simply a minor upstream
        update.
        """)

    MEDIUM = Item(2, """
        Medium Urgency

        This package contains updates that are worth considering, such
        as new upstream or packaging features, or significantly better
        documentation.
        """)

    HIGH = Item(3, """
        Very Urgent

        This update contains updates that fix security problems or major
        system stability problems with previous releases of the package.
        Administrators should urgently evaluate the package for inclusion
        in their archives.
        """)

    EMERGENCY = Item(4, """
        Critically Urgent

        This release contains critical security or stability fixes that
        affect the integrity of systems using previous releases of the
        source package, and should be installed in the archive as soon
        as possible after appropriate review.
        """)


class SpecificationDelivery(DBSchema):
    """Specification Delivery Status
    
    This tracks the implementation or delivery of the feature being
    specified. The status values indicate the progress that is being made in
    the actual coding or configuration that is needed to realise the
    feature.
    """

    UNKNOWN = Item(0, """
        Unknown

        We have no information on the implementation of this feature.
        """)

    DEFERRED = Item(10, """
        Deferred

        There is no chance that this feature will actually be delivered in
        the targeted release. The specification has effectively been
        deferred to a later date of implementation.
        """)

    NEEDSINFRASTRUCTURE = Item(40, """
        Needs Infrastructure

        Work cannot proceed on this feature, because it depends on
        infrastructure (servers, databases, connectivity, system
        administration work) which has not been done.
        """)

    BLOCKED = Item(50, """
        Blocked

        Work cannot proceed on this specification because it depends on
        another feature in a different specification which has not yet been
        done. Note: the other specification should be listed as a blocker of
        this one.
        """)

    STARTED = Item(60, """
        Started

        Work has begun on this feature, but has not yet been published
        except as informal branches or patches. No indication is given as to
        whether or not this work will be completed for the targeted release.
        """)

    SLOW = Item(65, """
        Slow progress

        Work has been slow on this item and it has a high risk of not being
        delivered on time. Help is wanted on direction or assistance is
        needed with the implementation of the feature.
        """)

    GOOD = Item(70, """
        Good progress

        This functionality is making good progress and is considered on 
        track for delivery in the targeted release.
        """)

    BETA = Item(75, """
        Beta Available

        The code for this feature has reached the point where a beta version
        that implements substantially all of the required functionality
        is being published for widespread testing, in personal package
        archives or a personal release, but the code is not yet in the
        main archive or mainline branch. Testing and feedback are solicited.
        """)

    NEEDSREVIEW = Item(80, """
        Needs Code Review

        The developer is satisfied that the feature has been well
        implemented, and is now ready for review and final sign-off on the
        feature, after which it will be marked implemented or deployed.
        """)

    AWAITINGDEPLOYMENT = Item(85, """
        Awaiting Deployment

        The work contemplated in this specification has been done, and can
        be deployed in the production environment, but the system
        administrators have not yet attended to that. Note: the status
        whiteboard should include an RT ticket for the deployment.
        """)

    IMPLEMENTED = Item(90, """
        Implemented

        This functionality has been delivered for the targeted release, the
        code has been uploaded to the main archives or committed to the
        targeted product series, and no further work is necessary.
        """)


class SpecificationPriority(DBSchema):
    """The Priority with a Specification must be implemented.

    This enum is used to prioritise work.
    """

    NOTFORUS = Item(0, """
        Not

        This feature has been proposed but the project leaders have decided
        that it is not appropriate for inclusion in the mainline codebase.
        See the status whiteboard or the
        specification itself for the rationale for this decision. Of course,
        you are welcome to implement it in any event and publish that work
        for consideration by the community and end users, but it is unlikely
        to be accepted by the mainline developers.
        """)

    PROPOSED = Item(5, """
        Proposed

        This feature has recently been proposed and has not yet been
        evaluated and prioritised by the project leaders.
        """)

    LOW = Item(10, """
        Low

        The specification is low priority. We would like to have it in the
        code, but it's not on any critical path and is likely to get bumped
        in favour of higher-priority work. The idea behind the specification
        is sound and the project leaders would incorporate this
        functionality if the work was done. In general, "low" priority
        specifications will not get core resources assigned to them.
        """)

    MEDIUM = Item(50, """
        Medium

        The specification is of a medium, or normal priority. The project
        developers will definitely get to this feature but perhaps not in
        the next major release or two.
        """)

    HIGH = Item(70, """
        High

        This specification is strongly desired for the next major release,
        and we have every reason to believe that it can be delivered in that
        timeframe.
        """)

    ESSENTIAL = Item(90, """
        Essential

        The specification is essential for the next release, and should be
        the focus of current development. Use this state only for the most
        important of all features.
        """)


class SpecificationSort(DBSchema):
    """A preferred sorting scheme for the results of a query about
    specifications.

    This is usually used in interfaces which ask for a filtered list of
    specifications, so that you can tell which specifications you would
    expect to see first.

    NB: this is not really a "dbschema" in that is doesn't map to an int
    that is stored in the db. In future, we will likely have a different way
    of defining such enums.
    """
    DATE = Item(10, """
        Date

        This indicates a preferred sort order of date of creation, newest
        first.
        """)

    PRIORITY = Item(20, """
        Priority

        This indicates a preferred sort order of priority (highest first)
        followed by status.
        """)


class SpecificationStatus(DBSchema):
    """The current status of a Specification

    This enum tells us whether or not a specification is approved, or still
    being drafted, or implemented, or obsolete in some way. The ordinality
    of the values is important, it's the order (lowest to highest) in which
    we probably want them displayed by default.
    """

    APPROVED = Item(10, """
        Approved

        This specification has been approved. The project team believe that
        it is ready to be implemented without substantial further issues being
        encountered.
        """)

    PENDINGAPPROVAL = Item(15, """
        Pending Approval

        This spec has been reviewed, and is considered to be ready for final
        approval. The reviewer believes that the specification is clearly
        written and adequately addresses all the important issues that will
        be raised during implementation.
        """)

    PENDINGREVIEW = Item(20, """
        Pending Review

        This spec has been put in a reviewers queue. The reviewer will
        assess the clarity and comprehensiveness of the spec, and decide
        whether further work is needed before the spec can be considered for
        actual approval.
        """)

    DRAFT = Item(30, """
        Drafting

        The specification is actively being drafted. The spec should only be
        in this state if it has a drafter in place, and the spec is under
        regular revision. Please do not park specs in the "drafting" state
        indefinitely.
        """)

    BRAINDUMP = Item(40, """
        Braindump

        The specification is a thought, or collection of thoughts, with
        no attention yet given to implementation strategy, dependencies or
        presentation/UI issues.
        """)

    INFORMATIONAL = Item(55, """
        Informational

        This specification does not need to be implemented. It is an
        overview, or documentation spec, that describes high level behaviour
        and links to actual specifications for implementation.
        """)

    SUPERSEDED = Item(60, """
        Superseded

        This specification is still interesting, but has been superseded by
        a newer spec, or set of specs, that clarify or describe a newer way
        to implement the desired feature(s). Please use the newer specs and
        not this one.
        """)

    OBSOLETE = Item(70, """
        Obsolete

        This specification has been obsoleted. Probably, we decided not to
        implement it for some reason. It should not be displayed, and people
        should not put any effort into implementing it.
        """)


class SpecificationGoalStatus(DBSchema):
    """The target status for this specification
    
    This enum allows us to show whether or not the specification has been
    approved or declined as a target for the given product series or distro
    release.
    """

    ACCEPTED = Item(10, """
        Accepted

        The drivers have confirmed that this specification is targeted to
        the stated distribution release or product series.
        """)

    DECLINED = Item(20, """
        Declined

        The drivers have decided not to accept this specification as a goal
        for the stated distribution release or product series.
        """)

    PROPOSED = Item(30, """
        Proposed

        This spec has been submitted as a potential goal for the stated
        product series or distribution release, but the drivers have not yet
        accepted or declined that goal.
        """)


class SprintSpecificationStatus(DBSchema):
    """The current approval status of the spec on this sprints agenda.
    
    This enum allows us to know whether or not the meeting admin team has
    agreed to discuss an item.
    """

    CONFIRMED = Item(10, """
        confirmed

        The meeting organisers have confirmed this topic for the meeting
        agenda.
        """)

    DEFERRED = Item(20, """
        deferred

        This spec has been deferred from the meeting agenda 
        because of a lack of available resources, or uncertainty over
        the specific requirements or outcome desired.
        """)

    SUBMITTED = Item(30, """
        submitted

        This spec has been submitted for consideration by the meeting
        organisers. It has not yet been approved or declined for the meeting
        agenda.
        """)


class TicketPriority(DBSchema):
    """The Priority with a Support Request must be handled.

    This enum is used to prioritise work done in the Launchpad support
    request management system.
    """

    WISHLIST = Item(0, """
        Wishlist

        This support ticket is really a request for a new feature. We will
        not take it further as a support ticket, it should be closed, and a
        specification created and managed in the Launchpad Specification
        Tracker.
        """)

    NORMAL = Item(10, """
        Normal

        This support ticket is of normal priority. We should respond to it
        in due course.
        """)

    HIGH = Item(70, """
        High

        This support ticket has been flagged as being of higher than normal
        priority. It should always be prioritised over a "normal" support
        request.
        """)

    EMERGENCY = Item(90, """
        Emergency

        This support ticket is classed as an emergency. No more than 5% of
        requests should fall into this category. Support engineers should
        ensure that there is somebody on this problem full time until it is
        resolved, or escalate it to the core technical and management team.
        """)


class TicketStatus(DBSchema):
    """The current status of a Support Request

    This enum tells us the current status of the support ticket. The
    request has a simple lifecycle, from open to answered or rejected.
    """

    OPEN = Item(10,
        """Open

        There might be someone that answered the support request, but
        the submitter hasn't accepted the answer yet.
        """)

    ANSWERED = Item(20,
        """Answered

        The submitter of the support request has accepted an answer.
        """)

    REJECTED = Item(30,
        """Rejected

        No acceptable answer was provided to the question.
        """)


class ImportStatus(DBSchema):
    """This schema describes the states that a SourceSource record can take
    on."""

    DONTSYNC = Item(1, """
        Do Not Sync

        We do not want to attempt to test or sync this upstream repository
        or branch. The ProductSeries can be set to DONTSYNC from any state
        other than SYNCING. Once it is Syncing, it can be STOPPED but should
        not be set to DONTSYNC. This prevents us from forgetting that we
        were at one stage SYNCING the ProductSeries.  """)

    TESTING = Item(2, """
        Testing

        New entries should start in this mode. We will try to import the
        given upstream branch from CVS or SVN automatically. When / if this
        ever succeeds it should set the status to AUTOTESTED.  """)

    TESTFAILED = Item(3, """
        Test Failed

        This sourcesource has failed its test import run. Failures can be
        indicative of a problem with the RCS server, or a problem with the
        actual data in their RCS system, or a network error.""")

    AUTOTESTED = Item(4, """
        Auto Tested

        The automatic testing system ("roomba") has successfully imported
        and in theory verified its import of the upstream revision control
        system. This ProductSeries is a definite candidate for manual review
        and should be switched to PROCESSING.  """)

    PROCESSING = Item(5, """
        Processing

        This ProductSeries is nearly ready for syncing. We will run it
        through the official import process, and then manually review the
        results. If they appear to be correct, then the
        ProductSeries.bazimportstatus can be set to SYNCING.  """)

    SYNCING = Item(6, """
        Syncing

        This ProductSeries is in Sync mode and SHOULD NOT BE EDITED OR
        CHANGED.  At this point, protection of the data related to the
        upstream revision control system should be extreme, with only
        launchpad.Special (in this case the vcs-imports team) able to affect
        these fields. If it is necessary to stop the syncing then the status
        must be changed to STOPPED, and not to DONTSYNC.  """)

    STOPPED = Item(7, """
        Stopped

        This state is used for ProductSeries that were in SYNCING mode and
        it was necessary to stop the sync activity. For example, when an
        upstream uses the same branch for versions 1, 2 and 3 of their
        product, we should put the ProductSeries into STOPPED after each
        release, create a new ProductSeries for the next version with the
        same branch details for upstream revision control system. That way,
        if they go back and branch off the previous release tag, we can
        amend the previous ProductSeries.  In theory, a STOPPED
        ProductSeries can be set to Sync again, but this requires serious
        Bazaar fu, and the vcs-imports team.  """)


class SourcePackageFileType(DBSchema):
    """Source Package File Type

    Launchpad tracks files associated with a source package release. These
    files are stored on one of the inner servers, and a record is kept in
    Launchpad's database of the file's name and location. This schema
    documents the files we know about.
    """

    EBUILD = Item(1, """
        Ebuild File

        This is a Gentoo Ebuild, the core file that Gentoo uses as a source
        package release. Typically this is a shell script that pulls in the
        upstream tarballs, configures them and builds them into the
        appropriate locations.  """)

    SRPM = Item(2, """
        Source RPM

        This is a Source RPM, a normal RPM containing the needed source code
        to build binary packages. It would include the Spec file as well as
        all control and source code files.  """)

    DSC = Item(3, """
        DSC File

        This is a DSC file containing the Ubuntu source package description,
        which in turn lists the orig.tar.gz and diff.tar.gz files used to
        make up the package.  """)

    ORIG = Item(4, """
        Orig Tarball

        This file is an Ubuntu "orig" file, typically an upstream tarball or
        other lightly-modified upstreamish thing.  """)

    DIFF = Item(5, """
        Diff File

        This is an Ubuntu "diff" file, containing changes that need to be
        made to upstream code for the packaging on Ubuntu. Typically this
        diff creates additional directories with patches and documentation
        used to build the binary packages for Ubuntu.  """)

    TARBALL = Item(6, """
        Tarball

        This is a tarball, usually of a mixture of Ubuntu and upstream code,
        used in the build process for this source package.  """)


class TranslationPriority(DBSchema):
    """Translation Priority

    Translations in Rosetta can be assigned a priority. This is used in a
    number of places. The priority stored on the translation itself is set
    by the upstream project maintainers, and used to identify the
    translations they care most about. For example, if Apache were nearing a
    big release milestone they would set the priority on those POTemplates
    to 'high'. The priority is also used by TranslationEfforts to indicate
    how important that POTemplate is to the effort. And lastly, an
    individual translator can set the priority on his personal subscription
    to a project, to determine where it shows up on his list.  """

    HIGH = Item(1, """
        High

        This translation should be shown on any summary list of translations
        in the relevant context. For example, 'high' priority projects show
        up on the home page of a TranslationEffort or Project in Rosetta.
        """)

    MEDIUM = Item(2, """
        Medium

        A medium priority POTemplate should be shown on longer lists and
        dropdowns lists of POTemplates in the relevant context.  """)

    LOW = Item(3, """
        Low

        A low priority POTemplate should only show up if a comprehensive
        search or complete listing is requested by the user.  """)

class TranslationPermission(DBSchema):
    """Translation Permission System

    Projects, products and distributions can all have content that needs to
    be translated. In this case, Rosetta allows them to decide how open they
    want that translation process to be. At one extreme, anybody can add or
    edit any translation, without review. At the other, only the designated
    translator for that group in that language can edit its translation
    files. This schema enumerates the options.
    """

    OPEN = Item(1, """
        Open

        This group allows totally open access to its translations. Any
        logged-in user can add or edit translations in any language, without
        any review.""")

    STRUCTURED = Item(20, """
        Structured

        This group has designated translators for certain languages. In
        those languages, people who are not designated translators can only
        make suggestions. However, in languages which do not yet have a
        designated translator, anybody can edit the translations directly,
        with no further review.""")

    CLOSED = Item(100, """
        Closed

        This group allows only designated translators to edit the
        translations of its files. You can become a designated translator
        either by joining an existing language translation team for this
        project, or by getting permission to start a new team for a new
        language. People who are not designated translators can still make
        suggestions for new translations, but those suggestions need to be
        reviewed before being accepted by the designated translator.""")

class DistroReleaseQueueStatus(DBSchema):
    """Distro Release Queue Status

    An upload has various stages it must pass through before becoming part
    of a DistroRelease. These are managed via the DistroReleaseQueue table
    and related tables and eventually (assuming a successful upload into the
    DistroRelease) the effects are published via the PackagePublishing and
    SourcePackagePublishing tables.  """

    NEW = Item(0, """
        New

        This upload is either a brand-new source package or contains a
        binary package with brand new debs or similar. The package must sit
        here until someone with the right role in the DistroRelease checks
        and either accepts or rejects the upload. If the upload is accepted
        then entries will be made in the overrides tables and further
        uploads will bypass this state """)

    UNAPPROVED = Item(1, """
        Unapproved

        If a DistroRelease is frozen or locked out of ordinary updates then
        this state is used to mean that while the package is correct from a
        technical point of view; it has yet to be approved for inclusion in
        this DistroRelease. One use of this state may be for security
        releases where you want the security team of a DistroRelease to
        approve uploads.  """)

    ACCEPTED = Item(2, """
        Accepted

        An upload in this state has passed all the checks required of it and
        is ready to have its publishing records created.  """)

    DONE = Item(3, """
        Done

        An upload in this state has had its publishing records created if it
        needs them and is fully processed into the DistroRelease. This state
        exists so that a logging and/or auditing tool can pick up accepted
        uploads and create entries in a journal or similar before removing
        the queue item.  """)

    REJECTED = Item(4, """
        Rejected

        An upload which reaches this state has, for some reason or another
        not passed the requirements (technical or human) for entry into the
        DistroRelease it was targetting. As for the 'done' state, this state
        is present to allow logging tools to record the rejection and then
        clean up any subsequently unnecessary records.  """)

# If you change this (add items, change the meaning, whatever) search for
# the token ##CUSTOMFORMAT## e.g. database/queue.py or nascentupload.py and
# update the stuff marked with it.
class DistroReleaseQueueCustomFormat(DBSchema):
    """Custom formats valid for the upload queue

    An upload has various files potentially associated with it, from source
    package releases, through binary builds, to specialist upload forms such
    as a debian-installer tarball or a set of translations.
    """

    DEBIAN_INSTALLER = Item(0, """
        raw-installer

        A raw-installer file is a tarball. This is processed as a version
        of the debian-installer to be unpacked into the archive root.
        """)

    ROSETTA_TRANSLATIONS = Item(1, """
        raw-translations

        A raw-translations file is a tarball. This is passed to the rosetta
        import queue to be incorporated into that package's translations.
        """)

    DIST_UPGRADER = Item(2, """
        raw-dist-upgrader

        A raw-dist-upgrader file is a tarball. It is simply published into
        the archive.
        """)

class PackagePublishingStatus(DBSchema):
    """Package Publishing Status

     A package has various levels of being published within a DistroRelease.
     This is important because of how new source uploads dominate binary
     uploads bit-by-bit. Packages (source or binary) enter the publishing
     tables as 'Pending', progress through to 'Published' eventually become
     'Superseded' and then become 'PendingRemoval'. Once removed from the
     DistroRelease the publishing record is also removed.
     """

    PENDING = Item(1, """
        Pending

        This [source] package has been accepted into the DistroRelease and
        is now pending the addition of the files to the published disk area.
        In due course, this source package will be published.
        """)

    PUBLISHED = Item(2, """
        Published

        This package is currently published as part of the archive for that
        distrorelease. In general there will only ever be one version of any
        source/binary package published at any one time. Once a newer
        version becomes published the older version is marked as superseded.
        """)

    SUPERSEDED = Item(3, """
        Superseded

        When a newer version of a [source] package is published the existing
        one is marked as "superseded".  """)

    PENDINGREMOVAL = Item(6, """
        PendingRemoval

        Once a package is ready to be removed from the archive is is put
        into this state and the removal will be acted upon when a period of
        time has passed. When the package is moved to this state the
        scheduleddeletiondate column is filled out. When that date has
        passed the archive maintainance tools will remove the package from
        the on-disk archive and remove the publishing record.  """)

    REMOVED = Item(7, """
        Removed

        Once a package is removed from the archive, its publishing record
        is set to this status. This means it won't show up in the SPP view
        and thus will not be considered in most queries about source
        packages in distroreleases. """)

class PackagePublishingPriority(DBSchema):
    """Package Publishing Priority

    Binary packages have a priority which is related to how important
    it is to have that package installed in a system. Common priorities
    range from required to optional and various others are available.
    """

    REQUIRED = Item(50, """
        Required

        This priority indicates that the package is required. This priority
        is likely to be hard-coded into various package tools. Without all
        the packages at this priority it may become impossible to use dpkg.
        """)

    IMPORTANT = Item(40, """
        Important

        If foo is in a package; and "What is going on?! Where on earth is
        foo?!?!" would be the reaction of an experienced UNIX hacker were
        the package not installed, then the package is important.
        """)

    STANDARD = Item(30, """
        Standard

        Packages at this priority are standard ones you can rely on to be in
        a distribution. They will be installed by default and provide a
        basic character-interface userland.
        """)

    OPTIONAL = Item(20, """
        Optional

        This is the software you might reasonably want to install if you did
        not know what it was or what your requiredments were. Systems such
        as X or TeX will live here.
        """)

    EXTRA = Item(10, """
        Extra

        This contains all the packages which conflict with those at the
        other priority levels; or packages which are only useful to people
        who have very specialised needs.
        """)

class PackagePublishingPocket(DBSchema):
    """Package Publishing Pocket

    A single distrorelease can at its heart be more than one logical
    distrorelease as the tools would see it. For example there may be a
    distrorelease called 'hoary' and a SECURITY pocket subset of that would
    be referred to as 'hoary-security' by the publisher and the distro side
    tools.
    """

    RELEASE = Item(0, """
        Release

        The package versions that were published
        when the distribution release was made.
        For releases that are still under development,
        packages are published here only.
        """)

    SECURITY = Item(10, """
        Security

        Package versions containing security fixes for the released
        distribution.
        It is a good idea to have security updates turned on for your system.
        """)

    UPDATES = Item(20, """
        Updates

        Package versions including new features after the distribution
        release has been made.
        Updates are usually turned on by default after a fresh install.
        """)

    PROPOSED = Item(30, """
        Proposed

        Package versions including new functions that should be widely
        tested, but that are not yet part of a default installation.
        People who "live on the edge" will test these packages before they
        are accepted for use in "Updates".
        """)

    BACKPORTS = Item(40, """
        Backports

        Backported packages.
        """)

class SourcePackageRelationships(DBSchema):
    """Source Package Relationships

    Launchpad tracks many source packages. Some of these are related to one
    another. For example, a source package in Ubuntu called "apache2" might
    be related to a source package in Mandrake called "httpd". This schema
    defines the relationships that Launchpad understands.
    """

    REPLACES = Item(1, """
        Replaces

        The subject source package was designed to replace the object source
        package.  """)

    REIMPLEMENTS = Item(2, """
        Reimplements

        The subject source package is a completely new packaging of the same
        underlying products as the object package.  """)

    SIMILARTO = Item(3, """
        Similar To

        The subject source package is similar, in that it packages software
        that has similar functionality to the object package.  For example,
        postfix and exim4 would be "similarto" one another.  """)

    DERIVESFROM = Item(4, """
        Derives From

        The subject source package derives from and tracks the object source
        package. This means that new uploads of the object package should
        trigger a notification to the maintainer of the subject source
        package.  """)

    CORRESPONDSTO = Item(5, """
        Corresponds To

        The subject source package includes the same products as the object
        source package, but for a different distribution. For example, the
        "apache2" Ubuntu package "correspondsto" the "httpd2" package in Red
        Hat.  """)


class BountyDifficulty(DBSchema):
    """Bounty Difficulty

    An indicator of the difficulty of a particular bounty."""

    TRIVIAL = Item(10, """
        Trivial

        This bounty requires only very basic skills to complete the task. No
        real domain knowledge is required, only simple system
        administration, writing or configuration skills, and the ability to
        publish the work.""")

    BASIC = Item(20, """
        Basic

        This bounty requires some basic programming skills, in a high level
        language like Python or C# or... BASIC. However, the project is
        being done "standalone" and so no knowledge of existing code is
        required.""")

    STRAIGHTFORWARD = Item(30, """
        Straightforward

        This bounty is easy to implement but does require some broader
        understanding of the framework or application within which the work
        must be done.""")

    NORMAL = Item(50, """
        Normal

        This bounty requires a moderate amount of programming skill, in a
        high level language like HTML, CSS, JavaScript, Python or C#. It is
        an extension to an existing application or package so the work will
        need to follow established project coding standards.""")

    CHALLENGING = Item(60, """
        Challenging

        This bounty requires knowledge of a low-level programming language
        such as C or C++.""")

    DIFFICULT = Item(70, """
        Difficult

        This project requires knowledge of a low-level programming language
        such as C or C++ and, in addition, requires extensive knowledge of
        an existing codebase into which the work must fit.""")

    VERYDIFFICULT = Item(90, """
        Very Difficult

        This project requires exceptional programming skill and knowledge of
        very low level programming environments, such as assembly language.""")

    EXTREME = Item(100, """
        Extreme

        In order to complete this work, detailed knowledge of an existing
        project is required, and in addition the work itself must be done in
        a low-level language like assembler or C on multiple architectures.""")


class BountyStatus(DBSchema):
    """Bounty Status

    An indicator of the status of a particular bounty. This can be edited by
    the bounty owner or reviewer."""

    OPEN = Item(1, """
        Open

        This bounty is open. People are still welcome to contact the creator
        or reviewer of the bounty, and submit their work for consideration
        for the bounty.""")

    WITHDRAWN = Item(9, """
        Withdrawn

        This bounty has been withdrawn.
        """)

    CLOSED = Item(10, """
        Closed

        This bounty is closed. No further submissions will be considered.
        """)


class BinaryPackageFileType(DBSchema):
    """Binary Package File Type

    Launchpad handles a variety of packaging systems and binary package
    formats. This schema documents the known binary package file types.
    """

    DEB = Item(1, """
        DEB Format

        This format is the standard package format used on Ubuntu and other
        similar operating systems.
        """)

    UDEB = Item(3, """
        UDEB Format

        This format is the standard package format used on Ubuntu and other
        similar operating systems for the installation system.
        """)

    RPM = Item(2, """
        RPM Format

        This format is used on mandrake, Red Hat, Suse and other similar
        distributions.
        """)


class CodereleaseRelationships(DBSchema):
    """Coderelease Relationships

    Code releases are both upstream releases and distribution source package
    releases, and in this schema we document the relationships that Launchpad
    understands between these two.
    """

    PACKAGES = Item(1, """
        Packages

        The subject is a distribution packing of the object. For example,
        apache2-2.0.48-1 "packages" the upstream apache2.0.48.tar.gz.
        """)

    REPLACES = Item(2, """
        Replaces

        A subsequent release in the same product series typically
        "replaces" the prior release. For example, apache2.0.48
        "replaces" apache2.0.47. Similarly, within the distribution
        world, apache-2.0.48-3ubuntu2 "replaces" apache2-2.0.48-3ubuntu2.
        """)

    DERIVESFROM = Item(3, """
        Derives From

        The subject package derives from the object package. It is common
        for distributions to build on top of one another's work, creating
        source packages that are modified versions of the source package
        in a different distribution, and this relationship captures that
        concept.
        """)


class BugInfestationStatus(DBSchema):
    """Bug Infestation Status

    Malone is the bug tracking application that is part of Launchpad. It
    tracks the status of bugs in different distributions as well as
    upstream. This schema documents the kinds of infestation of a bug
    in a coderelease.
    """

    AFFECTED = Item(60, """
        Affected

        It is believed that this bug affects that coderelease. The
        verifiedby field will indicate whether that has been verified
        by a package maintainer.
        """)

    DORMANT = Item(50, """
        Dormant

        The bug exists in the code of this coderelease, but it is dormant
        because that codepath is unused in this release.
        """)

    VICTIMIZED = Item(40, """
        Victimized

        This code release does not actually contain the buggy code, but
        it is affected by the bug nonetheless because of the way it
        interacts with the products or packages that are actually buggy.
        Often users will report a bug against the package which displays
        the symptoms when the bug itself lies elsewhere.
        """)

    FIXED = Item(30, """
        Fixed

        It is believed that the bug is actually fixed in this release of code.
        Setting the "fixed" flag allows us to generate lists of bugs fixed
        in a release.
        """)

    UNAFFECTED = Item(20, """
        Unaffected

        It is believed that this bug does not infest this release of code.
        """)

    UNKNOWN = Item(10, """
        Unknown

        We don't know if this bug infests that coderelease.
        """)


class BranchLifecycleStatus(DBSchema):
    """Branch Lifecycle Status

    This indicates the status of the branch, as part of an overall
    "lifecycle". The idea is to indicate to other people how mature this
    branch is, or whether or not the code in the branch has been deprecated.
    Essentially, this tells us what the author of the branch thinks of the
    code in the branch.
    """

    NEW = Item(1, """
        New

        This branch has just been created, and we know nothing else about
        it.
        """)

    EXPERIMENTAL = Item(10, """
        Experimental

        This branch contains code that is considered experimental. It is
        still under active development and should not be merged into
        production infrastructure.
        """)

    DEVELOPMENT = Item(30, """
        Development

        This branch contains substantial work that is shaping up nicely, but
        is not yet ready for merging or production use. The work is
        incomplete, or untested.
        """)

    MATURE = Item(50, """
        Mature

        The developer considers this code mature. That means that it
        completely addresses the issues it is supposed to, that it is tested,
        and that it has been found to be stable enough for the developer to
        recommend it to others for inclusion in their work.
        """)

    MERGED = Item(70, """
        Merged

        This code has successfully been merged into its target branch(es),
        and no further development is anticipated on the branch.
        """)

    ABANDONED = Item(80, """
        Abandoned

        This branch contains work which the author has abandoned, likely
        because it did not prove fruitful.
        """)


class BranchReviewStatus(DBSchema):
    """Branch Review Cycle

    This is an indicator of what the project thinks about this branch.
    Typically, it will be set by the upstream as part of a review process
    before the branch lands on an official series.
    """

    NONE = Item(10, """
        None

        This branch has not been queued for review, and no review has been
        done on it.
        """)

    REQUESTED = Item(20, """
        Requested

        The author has requested a review of the branch. This usually
        indicates that the code is mature and ready for merging, but it may
        also indicate that the author would like some feedback on the
        direction in which he is headed.
        """)

    NEEDSWORK = Item(30, """
        Needs Further Work

        The reviewer feels that this branch is not yet ready for merging, or
        is not on the right track. Detailed comments would be found in the
        reviewer discussion around the branch, see those for a list of the
        issues to be addressed or discussed.
        """)

    MERGECONDITIONAL = Item(50, """
        Conditional Merge Approved

        The reviewer has said that this branch can be merged if specific
        issues are addressed. The review feedback will be contained in the
        branch discussion. Once those are addressed by the author the branch
        can be merged without further review.
        """)

    MERGEAPPROVED = Item(60, """
        Merge Approved

        The reviewer is satisfied that the branch can be merged without
        further changes.
        """)


class BugTaskStatus(DBSchema):
    """Bug Task Status

    The various possible states for a bugfix in a specific place.
    """

    UNCONFIRMED = Item(10, """
        Unconfirmed

        This is a new bug and has not yet been confirmed by the maintainer of
        this product or source package.
        """)

    NEEDSINFO = Item(15, """
        Needs Info

        More info is required before making further progress on this bug, likely
        from the reporter. E.g. the exact error message the user saw, the URL
        the user was visiting when the bug occurred, etc.
        """)

    REJECTED = Item(17, """
        Rejected

        This bug has been rejected, e.g. in cases of operator-error.
        """)

    CONFIRMED = Item(20, """
        Confirmed

        This bug has been reviewed, verified, and confirmed as something needing
        fixing.
        """)

    INPROGRESS = Item(22, """
        In Progress

        The person assigned to fix this bug is currently working on fixing it.
        """)

    FIXCOMMITTED = Item(25, """
        Fix Committed

        This bug has been fixed in version control, but the fix has
        not yet made it into a released version of the affected
        software.
        """)

    FIXRELEASED = Item(30, """
        Fix Released

        The fix for this bug is available in a released version of the
        affected software.
        """)


class BugTaskPriority(DBSchema):
    """Bug Task Priority

    Each bug task in Malone can be assigned a priority by the
    maintainer of the bug. The priority is an indication of the
    maintainer's desire to fix the task. This schema documents the
    priorities Malone allows.
    """

    HIGH = Item(40, """
        High

        This is a high priority task for the maintainer.
        """)

    MEDIUM = Item(30, """
        Medium

        This is a medium priority task for the maintainer.
        """)

    LOW = Item(20, """
        Low

        This is a low priority task for the maintainer.
        """)

    WONTFIX = Item(10, """
        Wontfix

        The maintainer does not intend to fix this task.
        """)


class BugTaskSeverity(DBSchema):
    """Bug Task Severity

    A bug task has a severity, which is an indication of the
    extent to which the bug impairs the stability and security of
    the distribution or upstream in which it was reported.
    """

    CRITICAL = Item(50, """
        Critical

        This bug is essential to fix as soon as possible. It affects
        system stability, data integrity and / or remote access
        security.
        """)

    MAJOR = Item(40, """
        Major

        This bug needs urgent attention from the maintainer or
        upstream. It affects local system security or data integrity.
        """)

    NORMAL = Item(30, """
        Normal

        This bug warrants an upload just to fix it, but can be put
        off until other major or critical bugs have been fixed.
        """)

    MINOR = Item(20, """
        Minor

        This bug does not warrant an upload just to fix it, but
        should if possible be fixed when next the maintainer does an
        upload. For example, it might be a typo in a document.
        """)

    WISHLIST = Item(10, """
        Wishlist

        This is not a bug, but is a request for an enhancement or
        new feature that does not yet exist in the package. It does
        not affect system stability, it might be a usability or
        documentation fix.
        """)


class BugExternalReferenceType(DBSchema):
    """Bug External Reference Type

    Malone allows external information references to be attached to
    a bug. This schema lists the known types of external references.
    """

    CVE = Item(1, """
        CVE Reference

        This external reference is a CVE number, which means it
        exists in the CVE database of security bugs.
        """)

    URL = Item(2, """
        URL

        This external reference is a URL. Typically that means it
        is a reference to a web page or other internet resource
        related to the bug.
        """)


class BugRelationship(DBSchema):
    """Bug Relationship

    Malone allows for rich relationships between bugs to be specified,
    and this schema lists the types of relationships supported.
    """

    RELATED = Item(1, """
        Related Bug

        This indicates that the subject and object bugs are related in
        some way. The order does not matter. When displaying one bug, it
        would be appropriate to list the other bugs which are related to it.
        """)


class BugAttachmentType(DBSchema):
    """Bug Attachment Type.

    An attachment to a bug can be of different types, since for example
    a patch is more important than a screenshot. This schema describes the
    different types. 
    """

    PATCH = Item(1, """
        Patch

        This is a patch that potentially fixes the bug.
        """)

    UNSPECIFIED = Item(2, """
        Unspecified

        This is everything else. It can be a screenshot, a log file, a core
        dump, etc. Basically anything that adds more information to the bug.
        """)


class UpstreamReleaseVersionStyle(DBSchema):
    """Upstream Release Version Style

    Sourcerer will actively look for new upstream releases, and it needs
    to know roughly what version numbering format upstream uses. The
    release version number schemes understood by Sourcerer are documented
    in this schema. XXX andrew please fill in!
    """

    GNU = Item(1, """
        GNU-style Version Numbers

        XXX Andrew need description here
        """)


class RevisionControlSystems(DBSchema):
    """Revision Control Systems

    Bazaar brings code from a variety of upstream revision control
    systems into Arch. This schema documents the known and supported
    revision control systems.
    """

    CVS = Item(1, """
        Concurrent Version System

        The Concurrent Version System is very widely used among
        older open source projects, it was the first widespread
        open source version control system in use.
        """)

    SVN = Item(2, """
        Subversion

        Subversion aims to address some of the shortcomings in
        CVS, but retains the central server bottleneck inherent
        in the CVS design.
        """)

    ARCH = Item(3, """
        The Arch Revision Control System

        An open source revision control system that combines truly
        distributed branching with advanced merge algorithms. This
        removes the scalability problems of centralised revision
        control.
        """)

    PACKAGE = Item(4, """
        Package

        DEPRECATED DO NOT USE
        """)


    BITKEEPER = Item(5, """
        Bitkeeper

        A commercial revision control system that, like Arch, uses
        distributed branches to allow for faster distributed
        development.
        """)


class RosettaTranslationOrigin(DBSchema):
    """Rosetta Translation Origin

    Translation sightings in Rosetta can come from a variety
    of sources. We might see a translation for the first time
    in CVS, or we might get it through the web, for example.
    This schema documents those options.
    """

    SCM = Item(1, """
        Source Control Management Source

        This translation sighting came from a PO File we
        analysed in a source control managements sytem first.
        """)

    ROSETTAWEB = Item(2, """
        Rosetta Web Source

        This translation was presented to Rosetta via
        the community web site.
        """)


class RosettaImportStatus(DBSchema):
    """Rosetta Import Status

    Define the status of an import on the Import queue. It could have one
    of the following states: approved, imported, deleted, failed, needs_review
    or blocked.
    """

    APPROVED = Item(1, """
        Approved

        The entry has been approved by a Rosetta Expert or was able to be
        approved by our automatic system and is waiting to be imported.
        """)

    IMPORTED = Item(2, """
        Imported

        The entry has been imported.
        """)

    DELETED = Item(3, """
        Deleted

        The entry has been removed before being imported.
        """)

    FAILED = Item(4, """
        Failed

        The entry import failed.
        """)

    NEEDS_REVIEW = Item(5, """
        Needs Review

        A Rosetta Expert needs to review this entry to decide whether it will
        be imported and where it should be imported.
        """)

    BLOCKED = Item(6, """
        Blocked

        The entry has been blocked to be imported by a Rosetta Expert.
        """)


class SSHKeyType(DBSchema):
    """SSH key type

    SSH (version 2) can use RSA or DSA keys for authentication.  See OpenSSH's
    ssh-keygen(1) man page for details.
    """

    RSA = Item(1, """
        RSA

        RSA
        """)

    DSA = Item(2, """
        DSA

        DSA
        """)

class LoginTokenType(DBSchema):
    """Login token type

    Tokens are emailed to users in workflows that require email address
    validation, such as forgotten password recovery or account merging.
    We need to identify the type of request so we know what workflow
    is being processed.
    """

    PASSWORDRECOVERY = Item(1, """
        Password Recovery

        User has forgotten or never known their password and need to
        reset it.
        """)

    ACCOUNTMERGE = Item(2, """
        Account Merge

        User has requested that another account be merged into their
        current one.
        """)

    NEWACCOUNT = Item(3, """
        New Account

        A new account is being setup. They need to verify their email address
        before we allow them to set a password and log in.
        """)

    VALIDATEEMAIL = Item(4, """
        Validate Email

        A user has added more email addresses to their account and they
        need to be validated.
        """)

    VALIDATETEAMEMAIL = Item(5, """
        Validate Team Email

        One of the team administrators is trying to add a contact email
        address for the team, but this address need to be validated first.
        """)

    VALIDATEGPG = Item(6, """
        Validate GPG key 

        A user has submited a new GPG key to his account and it need to
        be validated.
        """)

    VALIDATESIGNONLYGPG = Item(7, """
        Validate a sign-only GPG key

        A user has submitted a new sign-only GPG key to his account and it
        needs to be validated.
        """)


class BuildStatus(DBSchema):
    """Build status type

    Builds exist in the database in a number of states such as 'complete',
    'needs build' and 'dependency wait'. We need to track these states in
    order to correctly manage the autobuilder queues in the BuildQueue table.
    """

    NEEDSBUILD = Item(0, """
        Needs building

        Build record is fresh and needs building. Nothing is yet known to
        block this build and it is a candidate for building on any free
        builder of the relevant architecture
        """)

    FULLYBUILT = Item(1, """
        Successfully built

        Build record is an historic account of the build. The build is complete
        and needs no further work to complete it. The build log etc are all
        in place if available.
        """)

    FAILEDTOBUILD = Item(2, """
        Failed to build

        Build record is an historic account of the build. The build failed and
        cannot be automatically retried. Either a new upload will be needed
        or the build will have to be manually reset into 'NEEDSBUILD' when
        the issue is corrected
        """)

    MANUALDEPWAIT = Item(3, """
        Dependency wait

        Build record represents a package whose build dependencies cannot
        currently be satisfied within the relevant DistroArchRelease. This
        build will have to be manually given back (put into 'NEEDSBUILD') when
        the dependency issue is resolved.
        """)

    CHROOTWAIT = Item(4, """
        Chroot problem

        Build record represents a build which needs a chroot currently known
        to be damaged or bad in some way. The buildd maintainer will have to
        reset all relevant CHROOTWAIT builds to NEEDSBUILD after the chroot
        has been fixed.
        """)

    SUPERSEDED = Item(5, """
        Build for superseded Source.

        Build record represents a build which never got to happen because the
        source package release for the build was superseded before the job
        was scheduled to be run on a builder. Builds which reach this state
        will rarely if ever be reset to any other state.
        """)


class MirrorFreshness(DBSchema):
    """ Mirror Freshness

    This valeu indicates how up-to-date Mirror is.
    """

    UNKNOWN = Item(99, """
        Freshness Unknown

        The Freshness was never verified and is unknown.
        """)


class MirrorContent(DBSchema):
    """The content that is mirrored."""

    ARCHIVE = Item(1, """
        Archive

        This mirror contains source and binary packages for a given
        distribution. Mainly used for APT-based system.
        """)

    RELEASE = Item(2, """
        Release

        Mirror containing released installation images for a given
        distribution.
        """)

    CDIMAGE = Item(3, """
        CD Image

        Mirrors containing CD images other than the installation ones, relesed
        for a given distribution.
        """)


class MirrorPulseType(DBSchema):
    """The method used by a mirror to update its contents."""

    PULL = Item(1, """
        Pull

        Mirror has a supported network application to "pull" the original
        content server periodically.
        """)

    PUSH = Item(2, """
        Push

        Original content server has enough access to the Mirror and is able to
        "push" new modification as soon as they happen.
        """)


class MirrorSpeed(DBSchema):
    """The speed of a given mirror."""

    S128K = Item(1, """
        128Kb per second

        The upstream link of this mirror can make up to 128Kb per second.
        """)

    S256K = Item(2, """
        256Kb per second

        The upstream link of this mirror can make up to 256Kb per second.
        """)

    S512K = Item(3, """
        512Kb per second

        The upstream link of this mirror can make up to 512Kb per second.
        """)

    S1M = Item(4, """
        1Mb per second

        The upstream link of this mirror can make up to 1Mb per second.
        """)

    S2M = Item(5, """
        2Mb per second

        The upstream link of this mirror can make up to 2Mb per second.
        """)

    S10M = Item(6, """
        10Mb per second

        The upstream link of this mirror can make up to 10Mb per second.
        """)

    S100M = Item(7, """
        100Mb per second

        The upstream link of this mirror can make up to 100Mb per second.
        """)


class MirrorStatus(DBSchema):
    """The status of a given mirror."""

    UP = Item(1, """
        Up to date

        This mirror is up to date with the original content.
        """)

    ONEHOURBEHIND = Item(2, """
        One hour behind

        This mirror's content seems to have been last updated one hour ago.
        """)

    TWOHOURSBEHIND = Item(3, """
        Two hours behind

        This mirror's content seems to have been last updated two hours ago.
        """)

    SIXHOURSBEHIND = Item(4, """
        Six hours behind

        This mirror's content seems to have been last updated six hours ago.
        """)

    ONEDAYBEHIND = Item(5, """
        One day behind

        This mirror's content seems to have been last updated one day ago.
        """)

    TWODAYSBEHIND = Item(6, """
        Two days behind

        This mirror's content seems to have been last updated two days ago.
        """)

    ONEWEEKBEHIND = Item(7, """
        One week behind

        This mirror's content seems to have been last updated one week ago.
        """)

    UNKNOWN = Item(8, """
        Unknown

        We couldn't determine when this mirror's content was last updated.
        """)


class PollSecrecy(DBSchema):
    """The secrecy of a given Poll."""

    OPEN = Item(1, """
        Public Votes (Anyone can see a person's vote)

        Everyone who wants will be able to see a person's vote.
        """)

    ADMIN = Item(2, """
        Semi-secret Votes (Only team administrators can see a person's vote)

        All team owners and administrators will be able to see a person's vote.
        """)

    SECRET = Item(3, """
        Secret Votes (It's impossible to track a person's vote)

        We don't store the option a person voted in our database,
        """)


class PollAlgorithm(DBSchema):
    """The algorithm used to accept and calculate the results."""

    SIMPLE = Item(1, """
        Simple Voting

        The most simple method for voting; you just choose a single option.
        """)

    CONDORCET = Item(2, """
        Condorcet Voting

        One of various methods used for calculating preferential votes. See
        http://www.electionmethods.org/CondorcetEx.htm for more information.
        """)


class RosettaFileFormat(DBSchema):
    """Rosetta File Format

    This is an enumeration of the different sorts of file that Rosetta can
    export.
    """

    PO = Item(1, """
        PO format

        Gettext's standard text file format.
        """)

    MO = Item(2, """
        MO format

        Gettext's standard binary file format.
        """)

    XLIFF = Item(3, """
        XLIFF

        OASIS's XML Localisation Interchange File Format.
        """)

    CSHARP_DLL = Item(4, """
        .NET DLL

        The dynamic link library format as used by programs that use the .NET
        framework.
        """)

    CSHARP_RESOURCES = Item(5, """
        .NET resource file

        The resource file format used by programs that use the .NET framework.
        """)

    TCL = Item(6, """
        TCL format

        The .msg format as used by TCL/msgcat.
        """)

    QT = Item(7, """
        QT format

        The .qm format as used by programs using the QT toolkit.
        """)

class TranslationValidationStatus(DBSchema):
    """Translation Validation Status

    Every time a translation is added to Rosetta we should checked that
    follows all rules to be a valid translation inside a .po file.
    This schema documents the status of that validation.
    """

    UNKNOWN = Item(0, """
        Unknown

        This translation has not been validated yet.
        """)

    OK = Item(1, """
        Ok

        This translation has been validated and no errors were discovered.
        """)

    UNKNOWNERROR = Item(2, """
        Unknown Error

        This translation has an unknown error.
        """)


class ShippingService(DBSchema):
    """The Shipping company we use to ship CDs."""

    TNT = Item(1, """
        TNT

        The TNT shipping company.
        """)

    SPRING = Item(2, """
        Spring

        The Spring shipping company.
        """)


class ShipItFlavour(DBSchema):
    """The Distro Flavour, used only to link with ShippingRequest."""

    UBUNTU = Item(1, """
        Ubuntu

        The Ubuntu flavour.
        """)


class ShipItArchitecture(DBSchema):
    """The Distro Architecture, used only to link with ShippingRequest."""

    X86 = Item(1, """
        Intel/X86

        x86 processors.
        """)

    AMD64 = Item(2, """
        AMD64

        AMD64 or EM64T based processors.
        """)

    PPC = Item(3, """
        PowerPC

        PowerPC processors.
        """)


class ShipItDistroRelease(DBSchema):
    """The Distro Release, used only to link with ShippingRequest."""

    BREEZY = Item(1, """
        Breezy Badger

        The Breezy Badger release.
        """)


class TextDirection(DBSchema):
    """The base text direction for a language."""

    LTR = Item(0, """
        Left to Right

        Text is normally written from left to right in this language.
        """)

    RTL = Item(1, """
        Right to Left

        Text is normally written from left to right in this language.
        """)
