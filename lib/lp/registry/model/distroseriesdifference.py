# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes for a difference between two distribution series."""

__metaclass__ = type

__all__ = [
    'DistroSeriesDifference',
    ]

from lazr.enum import DBItem
from storm.expr import Desc
from storm.locals import (
    Int,
    Reference,
    Storm,
    Unicode,
    )
from zope.component import getUtility
from zope.interface import (
    classProvides,
    implements,
    )

from canonical.database.enumcol import DBEnum
from canonical.launchpad.interfaces.lpstorm import (
    IMasterStore,
    IStore,
    )
from lp.registry.enum import (
    DistroSeriesDifferenceStatus,
    DistroSeriesDifferenceType,
    )
from lp.registry.exceptions import NotADerivedSeriesError
from lp.registry.interfaces.distroseriesdifference import (
    IDistroSeriesDifference,
    IDistroSeriesDifferenceSource,
    )
from lp.registry.interfaces.distroseriesdifferencecomment import (
    IDistroSeriesDifferenceCommentSource,
    )
from lp.registry.model.distroseriesdifferencecomment import (
    DistroSeriesDifferenceComment)
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.propertycache import (
    cachedproperty,
    IPropertyCacheManager,
    )


class DistroSeriesDifference(Storm):
    """See `DistroSeriesDifference`."""
    implements(IDistroSeriesDifference)
    classProvides(IDistroSeriesDifferenceSource)
    __storm_table__ = 'DistroSeriesDifference'

    id = Int(primary=True)

    derived_series_id = Int(name='derived_series', allow_none=False)
    derived_series = Reference(
        derived_series_id, 'DistroSeries.id')

    source_package_name_id = Int(
        name='source_package_name', allow_none=False)
    source_package_name = Reference(
        source_package_name_id, 'SourcePackageName.id')

    package_diff_id = Int(
        name='package_diff', allow_none=True)
    package_diff = Reference(
        package_diff_id, 'PackageDiff.id')

    parent_package_diff_id = Int(
        name='parent_package_diff', allow_none=True)
    parent_package_diff = Reference(
        parent_package_diff_id, 'PackageDiff.id')

    status = DBEnum(name='status', allow_none=False,
                    enum=DistroSeriesDifferenceStatus)
    difference_type = DBEnum(name='difference_type', allow_none=False,
                             enum=DistroSeriesDifferenceType)
    source_version = Unicode(name='source_version', allow_none=True)
    parent_source_version = Unicode(name='parent_source_version',
                                    allow_none=True)

    @staticmethod
    def new(derived_series, source_package_name):
        """See `IDistroSeriesDifferenceSource`."""
        if derived_series.parent_series is None:
            raise NotADerivedSeriesError()

        store = IMasterStore(DistroSeriesDifference)
        diff = DistroSeriesDifference()
        diff.derived_series = derived_series
        diff.source_package_name = source_package_name

        # The status and type is set to default values - they will be
        # updated appropriately during the update() call.
        diff.status = DistroSeriesDifferenceStatus.NEEDS_ATTENTION
        diff.difference_type = DistroSeriesDifferenceType.DIFFERENT_VERSIONS
        diff.update()

        return store.add(diff)

    @staticmethod
    def getForDistroSeries(
        distro_series,
        difference_type=DistroSeriesDifferenceType.DIFFERENT_VERSIONS,
        status=None):
        """See `IDistroSeriesDifferenceSource`."""
        if status is None:
            status = (
                DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
                )
        elif isinstance(status, DBItem):
            status = (status, )

        return IStore(DistroSeriesDifference).find(
            DistroSeriesDifference,
            DistroSeriesDifference.derived_series == distro_series,
            DistroSeriesDifference.difference_type == difference_type,
            DistroSeriesDifference.status.is_in(status))

    @staticmethod
    def getByDistroSeriesAndName(distro_series, source_package_name):
        """See `IDistroSeriesDifferenceSource`."""
        return IStore(DistroSeriesDifference).find(
            DistroSeriesDifference,
            DistroSeriesDifference.derived_series == distro_series,
            DistroSeriesDifference.source_package_name == (
                SourcePackageName.id),
            SourcePackageName.name == source_package_name).one()

    @cachedproperty
    def source_pub(self):
        """See `IDistroSeriesDifference`."""
        return self._getLatestSourcePub()

    @cachedproperty
    def parent_source_pub(self):
        """See `IDistroSeriesDifference`."""
        return self._getLatestSourcePub(for_parent=True)

    @property
    def owner(self):
        """See `IDistroSeriesDifference`."""
        return self.derived_series.owner

    @property
    def title(self):
        """See `IDistroSeriesDifference`."""
        parent_name = self.derived_series.parent_series.displayname
        return ("Difference between distroseries '%(parent_name)s' and "
                "'%(derived_name)s' for package '%(pkg_name)s' "
                "(%(parent_version)s/%(source_version)s)" % {
                    'parent_name': parent_name,
                    'derived_name': self.derived_series.displayname,
                    'pkg_name': self.source_package_name.name,
                    'parent_version': self.parent_source_version,
                    'source_version': self.source_version,
                    })

    def _getLatestSourcePub(self, for_parent=False):
        """Helper to keep source_pub/parent_source_pub DRY."""
        distro_series = self.derived_series
        if for_parent:
            distro_series = self.derived_series.parent_series

        pubs = distro_series.getPublishedSources(
            self.source_package_name, include_pending=True)

        # The most recent published source is the first one.
        if pubs:
            return pubs[0]
        else:
            return None

    def update(self):
        """See `IDistroSeriesDifference`."""
        # Updating is expected to be a heavy operation (not called
        # during requests). We clear the cache beforehand - even though
        # it is not currently necessary - so that in the future it
        # won't cause a hard-to find bug if a script ever creates a
        # difference, copies/publishes a new version and then calls
        # update() (like the tests for this method do).
        IPropertyCacheManager(self).clear()
        self._updateType()
        updated = self._updateVersionsAndStatus()
        return updated

    def _updateType(self):
        """Helper for update() interface method.

        Check whether the presence of a source in the derived or parent
        series has changed (which changes the type of difference).
        """
        if self.source_pub is None:
            new_type = DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES
        elif self.parent_source_pub is None:
            new_type = DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES
        else:
            new_type = DistroSeriesDifferenceType.DIFFERENT_VERSIONS

        if new_type != self.difference_type:
            self.difference_type = new_type

    def _updateVersionsAndStatus(self):
        """Helper for the update() interface method.

        Check whether the status of this difference should be updated.
        """
        updated = False
        new_source_version = new_parent_source_version = None
        if self.source_pub:
            new_source_version = self.source_pub.source_package_version
            if self.source_version != new_source_version:
                self.source_version = new_source_version
                updated = True
                # If the derived version has change and the previous version
                # was blacklisted, then we remove the blacklist now.
                if self.status == (
                    DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT):
                    self.status = DistroSeriesDifferenceStatus.NEEDS_ATTENTION
        if self.parent_source_pub:
            new_parent_source_version = (
                self.parent_source_pub.source_package_version)
            if self.parent_source_version != new_parent_source_version:
                self.parent_source_version = new_parent_source_version
                updated = True

        # If this difference was resolved but now the versions don't match
        # then we re-open the difference.
        if self.status == DistroSeriesDifferenceStatus.RESOLVED:
            if self.source_version != self.parent_source_version:
                updated = True
                self.status = DistroSeriesDifferenceStatus.NEEDS_ATTENTION
        # If this difference was needing attention, or the current version
        # was blacklisted and the versions now match we resolve it. Note:
        # we don't resolve it if this difference was blacklisted for all
        # versions.
        elif self.status in (
            DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
            DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT):
            if self.source_version == self.parent_source_version:
                updated = True
                self.status = DistroSeriesDifferenceStatus.RESOLVED

        return updated

    def addComment(self, commenter, comment):
        """See `IDistroSeriesDifference`."""
        return getUtility(IDistroSeriesDifferenceCommentSource).new(
            self, commenter, comment)

    def getComments(self):
        """See `IDistroSeriesDifference`."""
        DSDComment = DistroSeriesDifferenceComment
        comments = IStore(DSDComment).find(
            DistroSeriesDifferenceComment,
            DSDComment.distro_series_difference == self)
        return comments.order_by(Desc(DSDComment.id))

    def blacklist(self, all=False):
        """See `IDistroSeriesDifference`."""
        if all:
            self.status = DistroSeriesDifferenceStatus.BLACKLISTED_ALWAYS
        else:
            self.status = DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT

    def unblacklist(self):
        """See `IDistroSeriesDifference`."""
        self.status = DistroSeriesDifferenceStatus.NEEDS_ATTENTION
        self.update()
