# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Packageset interfaces."""

__metaclass__ = type

__all__ = [
    'DuplicatePackagesetName',
    'IPackageset',
    'IPackagesetSet',
    'NoSuchPackageSet',
    ]

from zope.interface import Interface
from zope.schema import Bool, Datetime, Int, List, TextLine

from canonical.launchpad import _
from canonical.launchpad.validators.name import name_validator
from canonical.launchpad.webapp.interfaces import NameLookupFailed
from lazr.restful.declarations import (
    collection_default_content, export_as_webservice_collection,
    export_as_webservice_entry, export_factory_operation,
    export_read_operation, export_write_operation, exported,
    operation_parameters, operation_returns_collection_of,
    operation_returns_entry, webservice_error)
from lazr.restful.fields import Reference
from lazr.restful.interface import copy_field
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.role import IHasOwner
from lp.soyuz.interfaces.packagesetgroup import IPackagesetGroup


class NoSuchPackageSet(NameLookupFailed):
    """Raised when we try to look up an PackageSet that doesn't exist."""
    # Bad request.
    webservice_error(400)
    _message_prefix = "No such package set (in the specified distro series)"


class DuplicatePackagesetName(Exception):
    """Raised for packagesets with the same name and distroseries."""
    # Bad request.
    webservice_error(400)


class IPackagesetViewOnly(IHasOwner):
    """A read-only interface for package sets."""
    export_as_webservice_entry()

    id = Int(title=_('ID'), required=True, readonly=True)

    date_created = exported(Datetime(
        title=_("Date Created"), required=True, readonly=True,
        description=_("The creation date/time for the package set at hand.")))

    owner = exported(Reference(
        IPerson, title=_("Person"), required=True, readonly=True,
        description=_("The person who owns this package set.")))

    name = exported(TextLine(
        title=_('Valid package set name'),
        required=True, constraint=name_validator))

    description = exported(TextLine(
        title=_("Description"), required=True, readonly=True,
        description=_("The description for the package set at hand.")))

    distroseries = exported(Reference(
        IDistroSeries, title=_("Distribution series"), required=True,
        readonly=True,
        description=_(
            "The distroseries to which this package set is related.")))

    packagesetgroup = Reference(
        IPackagesetGroup, title=_('Package set group'), required=True,
        readonly=True,
        description=_(
            'Used internally to link package sets across distro series.'))

    def sourcesIncluded(direct_inclusion=False):
        """Get all source names associated with this package set.

        This method returns the source package names that are directly
        or indirectly associated with the package set at hand. Indirect
        associations may be defined through package set successors.

        :param direct_inclusion: if this flag is set to True only sources
            directly included by this package set will be considered.
        :return: A (potentially empty) sequence of `ISourcePackageName`
            instances.
        """

    @operation_parameters(
        direct_inclusion=Bool(required=False))
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    def setsIncludedBy(direct_inclusion=False):
        """Get all package sets that include this one.

        Return all package sets that directly or indirectly include this one.

        :param direct_inclusion: if this flag is set to True only sets
            directly including this one will be considered.
        :return: A (potentially empty) sequence of `IPackageset` instances.
        """

    @operation_parameters(
        direct_inclusion=Bool(required=False))
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    def setsIncluded(direct_inclusion=False):
        """Get all package sets that are included by this one.

        Return all package sets that are directly or indirectly
        included by this one.

        :param direct_inclusion: if this flag is set to True only sets
            directly included by this one will be considered.
        :return: A (potentially empty) sequence of `IPackageset` instances.
        """

    def sourcesSharedBy(other_package_set, direct_inclusion=False):
        """Get source package names also included by another package set.

        What source package names does this package set have in common with
        the `other_package_set`?

        :param other_package_set: the other package set
        :param direct_inclusion: if this flag is set to True only directly
            included sources will be considered.
        :return: A (potentially empty) sequence of `ISourcePackageName`
            instances.
        """

    def sourcesNotSharedBy(other_package_set, direct_inclusion=False):
        """Get source package names not included by another package set.

        Which source package names included by this package are *not*
        included by the `other_package_set`?

        :param other_package_set: the other package set
        :param direct_inclusion: if this flag is set to True only directly
            included sources will be considered.
        :return: A (potentially empty) sequence of `ISourcePackageName`
            instances.
        """

    @operation_parameters(
        direct_inclusion=Bool(required=False))
    @export_read_operation()
    def getSourcesIncluded(direct_inclusion=False):
        """Get all source names associated with this package set.

        This method returns the source package names that are directly
        or indirectly associated with the package set at hand. Indirect
        associations may be defined through package set successors.

        Please note: this method was mainly introduced in order to
        facilitate the listing of source package names via the LP
        web services API. It returns string names as opposed to
        `ISourcePackageName` instances.

        :param direct_inclusion: if this flag is set to True only sources
            directly included by this package set will be considered.
        :return: A (potentially empty) sequence of string source package
            names.
        """

    @operation_parameters(
        other_package_set=Reference(
            Interface,
            title=_('The package set we are comparing to.'), required=True),
        direct_inclusion=Bool(required=False))
    @export_read_operation()
    def getSourcesSharedBy(other_package_set, direct_inclusion=False):
        """Get source package names also included by another package set.

        What source package names does this package set have in common with
        the `other_package_set`?

        Please note: this method was mainly introduced in order to
        facilitate the listing of source package names via the LP
        web services API. It returns string names as opposed to
        `ISourcePackageName` instances.

        :param other_package_set: the other package set
        :param direct_inclusion: if this flag is set to True only directly
            included sources will be considered.
        :return: A (potentially empty) sequence of string source package
            names.
        """

    @operation_parameters(
        other_package_set=Reference(
            Interface,
            title=_('The package set we are comparing to.'), required=True),
        direct_inclusion=Bool(required=False))
    @export_read_operation()
    def getSourcesNotSharedBy(other_package_set, direct_inclusion=False):
        """Get source package names not included by another package set.

        Which source package names included by this package are *not*
        included by the `other_package_set`?

        Please note: this method was mainly introduced in order to
        facilitate the listing of source package names via the LP
        web services API. It returns string names as opposed to
        `ISourcePackageName` instances.

        :param other_package_set: the other package set
        :param direct_inclusion: if this flag is set to True only directly
            included sources will be considered.
        :return: A (potentially empty) sequence of string source package
            names.
        """

    @operation_returns_collection_of(Interface)
    @export_read_operation()
    def relatedSets():
        """Get all package sets related to this one.

        Return all package sets that are related to this one.

        :return: A (potentially empty) sequence of `IPackageset` instances.
        """


class IPackagesetEdit(Interface):
    """A writeable interface for package sets."""
    export_as_webservice_entry()

    def add(data):
        """Add source package names or other package sets to this one.

        Any passed `SourcePackageName` or `Packageset` instances will become
        *directly* associated with the package set at hand.

        This function is idempotent in the sense that entities that are
        already directly associated with a package set will be ignored.

        :param data: an iterable with `SourcePackageName` XOR `Packageset`
            instances
        """

    def remove(data):
        """Remove source package names or other package sets from this one.

        Only source package names or package subsets *directly* included by
        this package set can be removed. Any others will be ignored.

        :param data: an iterable with `SourcePackageName` XOR `Packageset`
            instances
        """

    @operation_parameters(
        names=List(
        title=_("A list of source package names."), value_type=TextLine()))
    @export_write_operation()
    def addSources(names):
        """Add the named source packages to this package set.

        Any passed source package names will become *directly* associated
        with the package set at hand.

        This function is idempotent in the sense that source package names
        that are already directly associated with a package set will be
        ignored.

        This method facilitates the addition of source package names to
        package sets via the LP web services API. It takes string names
        as opposed to `ISourcePackageName` instances. Non-existing source
        package names will be ignored.

        :param names: an iterable with string source package names
        """

    @operation_parameters(
        names=List(
        title=_("A list of source package names."), value_type=TextLine()))
    @export_write_operation()
    def removeSources(names):
        """Remove the named source packages from this package set.

        Only source package names *directly* included by this package
        set can be removed. Any others will be ignored.

        This method facilitates the removal of source package names from
        package sets via the LP web services API. It takes string names
        as opposed to `ISourcePackageName` instances.

        :param names: an iterable with string source package names
        """

    @operation_parameters(
        names=List(
        title=_("A list of package set names."), value_type=TextLine()))
    @export_write_operation()
    def addSubsets(names):
        """Add the named package sets as subsets to this package set.

        Any passed source package names will become *directly* associated
        with the package set at hand.

        This function is idempotent in the sense that package subsets
        that are already directly associated with a package set will be
        ignored.

        This method facilitates the addition of package subsets via the
        LP web services API. It takes string names as opposed to
        `IPackageset` instances.

        :param names: an iterable with string package set names
        """

    @operation_parameters(
        names=List(
        title=_("A list of package set names."), value_type=TextLine()))
    @export_write_operation()
    def removeSubsets(names):
        """Remove the named package subsets from this package set.

        Only package subsets *directly* included by this package
        set can be removed. Any others will be ignored.

        This method facilitates the removal of package subsets via the
        LP web services API. It takes string names as opposed to
        `IPackageset` instances.

        :param names: an iterable with string package set names
        """


class IPackageset(IPackagesetViewOnly, IPackagesetEdit):
    """An interface for package sets."""
    export_as_webservice_entry()


class IPackagesetSet(Interface):
    """An interface for multiple package sets."""
    export_as_webservice_collection(IPackageset)

    @operation_parameters(
        name=TextLine(title=_('Valid package set name'), required=True),
        description=TextLine(
            title=_('Package set description'), required=True),
        owner=Reference(
            IPerson, title=_("Person"), required=True, readonly=True,
            description=_("The person who owns this package set.")),
        distroseries=Reference(
            IDistroSeries, title=_("Distroseries"), required=False,
            readonly=True, description=_(
                "The distribution series to which the packageset "
                "is related.")),
        related_set=Reference(
            IPackageset, title=_("Related package set"), required=False,
            readonly=True, description=_(
                "The new package set will share the package set group "
                "with this one.")))
    @export_factory_operation(IPackageset, [])
    def new(name, description, owner, distroseries=None, related_set=None):
        """Create a new package set.

        :param name: the name of the package set to be created.
        :param description: the description for the package set to be created.
        :param owner: the owner of the package set to be created.
        :param distroseries: the distroseries to which the new packageset
            is related. Defaults to the current Ubuntu series.
        :param related_set: the newly created package set is to be related to
            `related_set` (by being placed in the same package group).

        :raises DuplicatePackagesetName: if a package set with the same `name`
            exists in `distroseries` already.
        :return: a newly created `IPackageset`.
        """

    @operation_parameters(
        name=TextLine(title=_('Package set name'), required=True),
        distroseries=Reference(
            IDistroSeries, title=_("Distroseries"), required=False,
            readonly=True, description=_(
                "The distribution series to which the packageset "
                "is related.")))
    @operation_returns_entry(IPackageset)
    @export_read_operation()
    def getByName(name, distroseries=None):
        """Return the single package set with the given name (if any).

        :param name: the name of the package set sought.
        :param distroseries: the distroseries to which the new packageset
            is related. Defaults to the current Ubuntu series.

        :return: An `IPackageset` instance or None.
        """

    @collection_default_content()
    def get(limit=50):
        """Return the first `limit` package sets in Launchpad.

        :return: A (potentially empty) sequence of `IPackageset` instances.
        """

    def getByOwner(owner):
        """Return the package sets belonging to the given owner (if any).

        :param owner: the owner of the package sets sought.

        :return: A (potentially empty) sequence of `IPackageset` instances.
        """

    @operation_parameters(
        sourcepackagename=TextLine(
            title=_('Source package name'), required=True),
        distroseries=copy_field(IPackageset['distroseries'], required=False),
        direct_inclusion=Bool(required=False))
    @operation_returns_collection_of(IPackageset)
    @export_read_operation()
    def setsIncludingSource(sourcepackagename, distroseries=None,
                            direct_inclusion=False):
        """Get the package sets that include this source package.

        Return all package sets that directly or indirectly include the
        given source package name.

        :param sourcepackagename: the included source package name; can be
            either a string or a `ISourcePackageName`.
        :param distroseries: the `IDistroSeries` in which to look for sets.
            If omitted, matching package sets from all series will be
            returned.
        :param direct_inclusion: if this flag is set to True, then only
            package sets that directly include this source package name will
            be considered.

        :raises NoSuchSourcePackageName: if a source package with the given
            name cannot be found.
        :return: A (potentially empty) sequence of `IPackageset` instances.
        """

    def __getitem__(name):
        """Retrieve a package set by name."""

