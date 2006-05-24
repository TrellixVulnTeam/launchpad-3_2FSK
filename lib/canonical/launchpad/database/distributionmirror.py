# Copyright 2005 Canonical Ltd.  All rights reserved.

"""Module docstring goes here."""

__metaclass__ = type
__all__ = ['DistributionMirror', 'MirrorDistroArchRelease',
           'MirrorDistroReleaseSource', 'MirrorProbeRecord',
           'DistributionMirrorSet', 'MirrorCDImageDistroRelease']

from datetime import datetime, timedelta, MINYEAR
import urllib2
import pytz

from zope.component import getUtility
from zope.interface import implements

from sqlobject import ForeignKey, StringCol, BoolCol

from canonical.config import config
from canonical.cachedproperty import cachedproperty
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.sqlbase import SQLBase, sqlvalues, cursor

from canonical.archivepublisher.publishing import pocketsuffix
from canonical.archivepublisher.pool import Poolifier
from canonical.lp.dbschema import (
    MirrorSpeed, MirrorContent, MirrorPulseType, MirrorStatus,
    PackagePublishingPocket, EnumCol, PackagePublishingStatus,
    SourcePackageFileType, BinaryPackageFileType)
from canonical.launchpad.interfaces import (
    IDistributionMirror, IMirrorDistroReleaseSource, IMirrorDistroArchRelease,
    IMirrorProbeRecord, IDistributionMirrorSet, PROBE_INTERVAL,
    IDistroRelease, IDistroArchRelease, IMirrorCDImageDistroRelease,
    IDistributionSet, UnableToFetchCDImageFileList)
from canonical.launchpad.database.files import (
    BinaryPackageFile, SourcePackageReleaseFile)
from canonical.launchpad.database.publishing import (
    SecureSourcePackagePublishingHistory, SecureBinaryPackagePublishingHistory)
from canonical.launchpad.helpers import get_email_template
from canonical.launchpad.webapp import urlappend
from canonical.launchpad.mail import simple_sendmail, format_address


class DistributionMirror(SQLBase):
    """See IDistributionMirror"""

    implements(IDistributionMirror)
    _table = 'DistributionMirror'
    _defaultOrder = 'id'

    owner = ForeignKey(
        dbName='owner', foreignKey='Person', notNull=True)
    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution', notNull=True)
    name = StringCol(
        alternateID=True, notNull=True)
    displayname = StringCol(
        notNull=False, default=None)
    description = StringCol(
        notNull=False, default=None)
    http_base_url = StringCol(
        notNull=False, default=None, unique=True)
    ftp_base_url = StringCol(
        notNull=False, default=None, unique=True)
    rsync_base_url = StringCol(
        notNull=False, default=None, unique=True)
    pulse_source = StringCol(
        notNull=False, default=None)
    enabled = BoolCol(
        notNull=True, default=False)
    file_list = ForeignKey(
        dbName='file_list', foreignKey='LibraryFileAlias')
    speed = EnumCol(
        notNull=True, schema=MirrorSpeed)
    country = ForeignKey(
        dbName='country', foreignKey='Country', notNull=True)
    content = EnumCol(
        notNull=True, schema=MirrorContent)
    pulse_type = EnumCol(
        notNull=True, schema=MirrorPulseType, default=MirrorPulseType.PUSH)
    official_candidate = BoolCol(
        notNull=True, default=False)
    official_approved = BoolCol(
        notNull=True, default=False)

    @cachedproperty
    def last_probe_record(self):
        """See IDistributionMirror"""
        return MirrorProbeRecord.selectFirst(
            MirrorProbeRecord.q.distribution_mirrorID==self.id,
            orderBy='-date_created')

    @property
    def title(self):
        """See IDistributionMirror"""
        if self.displayname:
            return self.displayname
        else:
            return self.name

    def isOfficial(self):
        """See IDistributionMirror"""
        return self.official_candidate and self.official_approved

    def hasContent(self):
        """See IDistributionMirror"""
        return bool(self.source_releases or self.arch_releases or
                    self.cdimage_releases)

    def disableAndNotifyOwner(self):
        """See IDistributionMirror"""
        self.enabled = False
        template = get_email_template('notify-mirror-owner.txt')
        fromaddress = format_address(
            "Launchpad Mirror Prober", config.noreply_from_address)

        replacements = {'distro': self.distribution.title,
                        'mirror_name': self.name}
        message = template % replacements

        subject = "Launchpad: Your distribution mirror seems to be unreachable"
        to_address = format_address(
            self.owner.displayname, self.owner.preferredemail.email)
        simple_sendmail(fromaddress, to_address, subject, message)

    def newProbeRecord(self, log_file):
        """See IDistributionMirror"""
        return MirrorProbeRecord(distribution_mirror=self, log_file=log_file)

    def deleteMirrorDistroArchRelease(self, distro_arch_release, pocket,
                                      component):
        """See IDistributionMirror"""
        mirror = MirrorDistroArchRelease.selectOneBy(
            distribution_mirrorID=self.id,
            distro_arch_releaseID=distro_arch_release.id,
            pocket=pocket, componentID=component.id)
        if mirror is not None:
            mirror.destroySelf()

    def ensureMirrorDistroArchRelease(self, distro_arch_release, pocket,
                                      component):
        """See IDistributionMirror"""
        assert IDistroArchRelease.providedBy(distro_arch_release)
        mirror = MirrorDistroArchRelease.selectOneBy(
            distribution_mirrorID=self.id,
            distro_arch_releaseID=distro_arch_release.id,
            pocket=pocket, componentID=component.id)
        if mirror is None:
            mirror = MirrorDistroArchRelease(
                pocket=pocket, distribution_mirror=self,
                distro_arch_release=distro_arch_release,
                componentID=component.id)
        return mirror

    def ensureMirrorDistroReleaseSource(self, distrorelease, pocket, component):
        """See IDistributionMirror"""
        assert IDistroRelease.providedBy(distrorelease)
        mirror = MirrorDistroReleaseSource.selectOneBy(
            distribution_mirrorID=self.id, distroreleaseID=distrorelease.id,
            pocket=pocket, componentID=component.id)
        if mirror is None:
            mirror = MirrorDistroReleaseSource(
                distribution_mirror=self, distrorelease=distrorelease,
                pocket=pocket, componentID=component.id)
        return mirror

    def deleteMirrorDistroReleaseSource(self, distrorelease, pocket, component):
        """See IDistributionMirror"""
        mirror = MirrorDistroReleaseSource.selectOneBy(
            distribution_mirrorID=self.id, distroreleaseID=distrorelease.id,
            pocket=pocket, componentID=component.id)
        if mirror is not None:
            mirror.destroySelf()

    def ensureMirrorCDImageRelease(self, distrorelease, flavour):
        """See IDistributionMirror"""
        mirror = MirrorCDImageDistroRelease.selectOneBy(
            distribution_mirrorID=self.id, distroreleaseID=distrorelease.id,
            flavour=flavour)
        if mirror is None:
            mirror = MirrorCDImageDistroRelease(
                distribution_mirror=self, distrorelease=distrorelease,
                flavour=flavour)
        return mirror

    def deleteMirrorCDImageRelease(self, distrorelease, flavour):
        """See IDistributionMirror"""
        mirror = MirrorCDImageDistroRelease.selectOneBy(
            distribution_mirrorID=self.id, distroreleaseID=distrorelease.id,
            flavour=flavour)
        if mirror is not None:
            mirror.destroySelf()

    @property
    def cdimage_releases(self):
        """See IDistributionMirror"""
        return MirrorCDImageDistroRelease.selectBy(
            distribution_mirrorID=self.id)

    def getCDImageMirroredFlavoursByRelease(self):
        """See IDistributionMirror"""
        flavours_by_release = {}
        for cdimage in self.cdimage_releases:
            distrorelease, flavour = cdimage.distrorelease, cdimage.flavour
            flavours = flavours_by_release.setdefault(distrorelease.title, [])
            if flavour not in flavours:
                flavours.append(flavour)
        return flavours_by_release

    @property
    def source_releases(self):
        """See IDistributionMirror"""
        return MirrorDistroReleaseSource.selectBy(distribution_mirrorID=self.id)

    def getSummarizedMirroredSourceReleases(self):
        """See IDistributionMirror"""
        # Select the mirror with the worst status for each distrorelease.
        query = """
            SELECT DISTINCT ON (MirrorDistroReleaseSource.distribution_mirror,
                                MirrorDistroReleaseSource.distrorelease)
                   MirrorDistroReleaseSource.id
            FROM MirrorDistroReleaseSource, DistributionMirror
            WHERE DistributionMirror.id = 
                        MirrorDistroReleaseSource.distribution_mirror
                  AND DistributionMirror.distribution = %(distribution)s
            ORDER BY MirrorDistroReleaseSource.distribution_mirror, 
                     MirrorDistroReleaseSource.distrorelease, 
                     MirrorDistroReleaseSource.status DESC
            """ % sqlvalues(distribution=self.distribution)
        cur = cursor()
        cur.execute(query)
        ids = ", ".join([str(id) for (id,) in cur.fetchall()])
        return MirrorDistroReleaseSource.select("id IN (%s)" % ids)

    @property
    def arch_releases(self):
        """See IDistributionMirror"""
        return MirrorDistroArchRelease.selectBy(distribution_mirrorID=self.id)

    def getSummarizedMirroredArchReleases(self):
        """See IDistributionMirror"""
        # Select the mirror with the worst status for each distro_arch_release.
        query = """
            SELECT DISTINCT ON (MirrorDistroArchRelease.distribution_mirror,
                                MirrorDistroArchRelease.distro_arch_release)
                   MirrorDistroArchRelease.id
            FROM MirrorDistroArchRelease, DistributionMirror
            WHERE DistributionMirror.id = 
                        MirrorDistroArchRelease.distribution_mirror
                  AND DistributionMirror.distribution = %(distribution)s
            ORDER BY MirrorDistroArchRelease.distribution_mirror, 
                     MirrorDistroArchRelease.distro_arch_release, 
                     MirrorDistroArchRelease.status DESC
            """ % sqlvalues(distribution=self.distribution)
        cur = cursor()
        cur.execute(query)
        ids = ", ".join([str(id) for (id,) in cur.fetchall()])
        return MirrorDistroArchRelease.select("id IN (%s)" % ids)

    def _getCDImageFileList(self):
        url = config.distributionmirrorprober.releases_file_list_url
        try:
            return urllib2.urlopen(url)
        except urllib2.URLError, e:
            raise UnableToFetchCDImageFileList(
                'Unable to fetch %s: %s' % (url, e))

    def guessCDImagePaths(self):
        """See IDistributionMirror"""
        d = {}
        for line in self._getCDImageFileList().readlines():
            flavour, releasename, path, size = line.split('\t')
            paths = d.setdefault((flavour, releasename), [])
            paths.append(path)

        paths = []
        # XXX: We only probe Ubuntu release mirrors, but even so it'd be good
        # if we could get the Ubuntu Distribution from somewhere else, instead
        # of having it hardcoded here.
        # -- Guilherme Salgado, 2006-05-11
        ubuntu = getUtility(IDistributionSet)['ubuntu']
        for key, value in d.items():
            flavour, releasename = key
            release = ubuntu.getRelease(releasename)
            paths.append((release, flavour, value))
        return paths

    def guessPackagesPaths(self):
        """See IDistributionMirror"""
        paths = []
        for release in self.distribution.releases:
            for pocket, suffix in pocketsuffix.items():
                for component in release.components:
                    for arch_release in release.architectures:
                        path = ('dists/%s%s/%s/binary-%s/Packages.gz'
                                % (release.name, suffix, component.name,
                                   arch_release.architecturetag))
                        paths.append((arch_release, pocket, component, path))
        return paths

    def guessSourcesPaths(self):
        """See IDistributionMirror"""
        paths = []
        for release in self.distribution.releases:
            for pocket, suffix in pocketsuffix.items():
                for component in release.components:
                    path = ('dists/%s%s/%s/source/Sources.gz'
                            % (release.name, suffix, component.name))
                    paths.append((release, pocket, component, path))
        return paths


class DistributionMirrorSet:
    """See IDistributionMirrorSet"""

    implements (IDistributionMirrorSet)

    def __getitem__(self, mirror_id):
        """See IDistributionMirrorSet"""
        return DistributionMirror.get(mirror_id)

    def getMirrorsToProbe(self, content_type):
        """See IDistributionMirrorSet"""
        query = """
            SELECT distributionmirror.id, max(mirrorproberecord.date_created)
            FROM distributionmirror 
            LEFT OUTER JOIN mirrorproberecord
                ON mirrorproberecord.distribution_mirror = distributionmirror.id
            WHERE distributionmirror.enabled IS TRUE
                AND distributionmirror.content = %s
                AND distributionmirror.official_candidate IS TRUE
                AND distributionmirror.official_approved IS TRUE
            GROUP BY distributionmirror.id
            HAVING max(mirrorproberecord.date_created) IS NULL
                OR max(mirrorproberecord.date_created) 
                    < %s - '%s hours'::interval
            """ % sqlvalues(content_type, UTC_NOW, PROBE_INTERVAL)
        conn = DistributionMirror._connection
        ids = ", ".join(str(id) for (id, date_created) in conn.queryAll(query))
        query = '1 = 2'
        if ids:
            query = 'id IN (%s)' % ids
        return DistributionMirror.select(query)

    def getByName(self, name):
        """See IDistributionMirrorSet"""
        return DistributionMirror.selectOneBy(name=name)

    def getByHttpUrl(self, url):
        """See IDistributionMirrorSet"""
        return DistributionMirror.selectOneBy(http_base_url=url)

    def getByFtpUrl(self, url):
        """See IDistributionMirrorSet"""
        return DistributionMirror.selectOneBy(ftp_base_url=url)

    def getByRsyncUrl(self, url):
        """See IDistributionMirrorSet"""
        return DistributionMirror.selectOneBy(rsync_base_url=url)


class _MirrorReleaseMixIn:
    """A class containing some commonalities between MirrorDistroArchRelease
    and MirrorDistroReleaseSource.

    This class is not meant to be used alone. Instead, both
    MirrorDistroReleaseSource and MirrorDistroArchRelease should inherit from
    it and override the methods and attributes that say so.
    """

    # The status_times map defines levels for specifying how up to date a
    # mirror is; we use published files to assess whether a certain level is
    # fulfilled by a mirror. The map is used in combination with a special
    # status UP that maps to the latest published file for that distribution
    # release, component and pocket: if that file is found, we consider the
    # distribution to be up to date; if it is not found we then look through
    # the rest of the map to try and determine at what level the mirror is.
    status_times = [
        (MirrorStatus.ONEHOURBEHIND, 1.5),
        (MirrorStatus.TWOHOURSBEHIND, 2.5),
        (MirrorStatus.SIXHOURSBEHIND, 6.5),
        (MirrorStatus.ONEDAYBEHIND, 24.5),
        (MirrorStatus.TWODAYSBEHIND, 48.5),
        (MirrorStatus.ONEWEEKBEHIND, 168.5)
        ]

    def _getPackageReleaseURLFromPublishingRecord(self, publishing_record):
        """Given a publishing record, return a dictionary mapping MirrorStatus
        items to URLs of files on this mirror.

        Must be overwritten on subclasses.
        """
        raise NotImplementedError

    def getLatestPublishingEntry(time_interval):
        """Return the publishing entry with the most recent datepublished.

        Time interval must be a tuple of the form (start, end), and only
        records whose datepublished is between start and end are considered.
        """
        raise NotImplementedError

    def getURLsToCheckUpdateness(self, when=None):
        """See IMirrorDistroReleaseSource or IMirrorDistroArchRelease."""
        if when is None:
            when = datetime.now(pytz.timezone('UTC'))

        start = datetime(MINYEAR, 1, 1, tzinfo=pytz.timezone('UTC'))
        time_interval = (start, when)
        latest_upload = self.getLatestPublishingEntry(time_interval)
        if latest_upload is None:
            return {}

        url = self._getPackageReleaseURLFromPublishingRecord(latest_upload)
        urls = {MirrorStatus.UP: url}

        # For each status in self.status_times, do:
        #   1) if latest_upload was published before the start of this status'
        #      time interval, skip it and move to the next status.
        #   2) if latest_upload was published between this status' time
        #      interval, adjust the end of the time interval to be identical
        #      to latest_upload.datepublished. We do this because even if the
        #      mirror doesn't have the latest upload, we can't skip that whole
        #      time interval: the mirror might have other packages published
        #      in that interval.
        #      This happens in pathological cases where two publications were
        #      done successively after a long period of time with no
        #      publication: if the mirror lacks the latest published package,
        #      we still need to check the corresponding interval or we will
        #      misreport the mirror as being very out of date.
        #   3) search for publishing records whose datepublished is between
        #      the specified time interval, and if one is found, append an
        #      item to the urls dictionary containing this status and the url
        #      on this mirror from where the file correspondent to that
        #      publishing record can be downloaded.
        last_threshold = 0
        for status, threshold in self.status_times:
            start = when - timedelta(hours=threshold)
            end = when - timedelta(hours=last_threshold)
            last_threshold = threshold
            if latest_upload.datepublished < start:
                continue
            if latest_upload.datepublished < end:
                end = latest_upload.datepublished
                    
            time_interval = (start, end)
            upload = self.getLatestPublishingEntry(time_interval)

            if upload is None:
                # No uploads that would allow us to know the mirror was in
                # this status, so we better skip it.
                continue

            url = self._getPackageReleaseURLFromPublishingRecord(upload)
            urls.update({status: url})

        return urls


class MirrorCDImageDistroRelease(SQLBase):
    """See IMirrorCDImageDistroRelease"""

    implements(IMirrorCDImageDistroRelease)
    _table = 'MirrorCDImageDistroRelease'
    _defaultOrder = 'id'

    distribution_mirror = ForeignKey(
        dbName='distribution_mirror', foreignKey='DistributionMirror',
        notNull=True)
    distrorelease = ForeignKey(
        dbName='distrorelease', foreignKey='DistroRelease', notNull=True)
    flavour = StringCol(notNull=True)


class MirrorDistroArchRelease(SQLBase, _MirrorReleaseMixIn):
    """See IMirrorDistroArchRelease"""

    implements(IMirrorDistroArchRelease)
    _table = 'MirrorDistroArchRelease'
    _defaultOrder = [
        'distro_arch_release', 'component', 'pocket', 'status', 'id']

    distribution_mirror = ForeignKey(
        dbName='distribution_mirror', foreignKey='DistributionMirror',
        notNull=True)
    distro_arch_release = ForeignKey(
        dbName='distro_arch_release', foreignKey='DistroArchRelease',
        notNull=True)
    component = ForeignKey(
        dbName='component', foreignKey='Component', notNull=True)
    status = EnumCol(
        notNull=True, default=MirrorStatus.UNKNOWN, schema=MirrorStatus)
    pocket = EnumCol(
        notNull=True, schema=PackagePublishingPocket)

    def getLatestPublishingEntry(self, time_interval, deb_only=True):
        """Return the SecureBinaryPackagePublishingHistory record with the
        most recent datepublished.

        :deb_only: If True, return only publishing records whose
                   binarypackagerelease's binarypackagefile.filetype is
                   BinaryPackageFileType.DEB.
        """
        query = """
            SecureBinaryPackagePublishingHistory.pocket = %s 
            AND SecureBinaryPackagePublishingHistory.component = %s 
            AND SecureBinaryPackagePublishingHistory.distroarchrelease = %s
            AND SecureBinaryPackagePublishingHistory.status = %s
            """ % sqlvalues(self.pocket, self.component.id, 
                            self.distro_arch_release.id,
                            PackagePublishingStatus.PUBLISHED)

        if deb_only:
            query += """
                AND SecureBinaryPackagePublishingHistory.binarypackagerelease =
                    BinaryPackageFile.binarypackagerelease
                AND BinaryPackageFile.filetype = %s
                """ % sqlvalues(BinaryPackageFileType.DEB)

        if time_interval is not None:
            start, end = time_interval
            assert end > start, '%s is not more recent than %s' % (end, start)
            query = (query + " AND datepublished >= %s AND datepublished < %s"
                     % sqlvalues(start, end))
        return SecureBinaryPackagePublishingHistory.selectFirst(
            query, clauseTables=['BinaryPackageFile'], orderBy='-datepublished')


    def _getPackageReleaseURLFromPublishingRecord(self, publishing_record):
        """Given a SecureBinaryPackagePublishingHistory, return the URL on 
        this mirror from where the BinaryPackageRelease file can be downloaded.
        """
        bpr = publishing_record.binarypackagerelease
        base_url = self.distribution_mirror.http_base_url
        path = Poolifier().poolify(bpr.sourcepackagename, self.component.name)
        file = BinaryPackageFile.selectOneBy(
            binarypackagereleaseID=bpr.id, filetype=BinaryPackageFileType.DEB)
        full_path = 'pool/%s/%s' % (path, file.libraryfile.filename)
        return urlappend(base_url, full_path)


class MirrorDistroReleaseSource(SQLBase, _MirrorReleaseMixIn):
    """See IMirrorDistroReleaseSource"""

    implements(IMirrorDistroReleaseSource)
    _table = 'MirrorDistroReleaseSource'
    _defaultOrder = ['distrorelease', 'component', 'pocket', 'status', 'id']

    distribution_mirror = ForeignKey(
        dbName='distribution_mirror', foreignKey='DistributionMirror',
        notNull=True)
    distrorelease = ForeignKey(
        dbName='distrorelease', foreignKey='DistroRelease',
        notNull=True)
    component = ForeignKey(
        dbName='component', foreignKey='Component', notNull=True)
    status = EnumCol(
        notNull=True, default=MirrorStatus.UNKNOWN, schema=MirrorStatus)
    pocket = EnumCol(
        notNull=True, schema=PackagePublishingPocket)

    def getLatestPublishingEntry(self, time_interval):
        query = """
            SecureSourcePackagePublishingHistory.pocket = %s 
            AND SecureSourcePackagePublishingHistory.component = %s 
            AND SecureSourcePackagePublishingHistory.distrorelease = %s
            AND SecureSourcePackagePublishingHistory.status = %s
            """ % sqlvalues(self.pocket, self.component.id, 
                            self.distrorelease.id,
                            PackagePublishingStatus.PUBLISHED)

        if time_interval is not None:
            start, end = time_interval
            assert end > start
            query = (query + " AND datepublished >= %s AND datepublished < %s"
                     % sqlvalues(start, end))
        return SecureSourcePackagePublishingHistory.selectFirst(
            query, orderBy='-datepublished')

    def _getPackageReleaseURLFromPublishingRecord(self, publishing_record):
        """Given a SecureSourcePackagePublishingHistory, return the URL on 
        this mirror from where the SourcePackageRelease file can be downloaded.
        """
        spr = publishing_record.sourcepackagerelease
        base_url = self.distribution_mirror.http_base_url
        sourcename = spr.name
        path = Poolifier().poolify(sourcename, self.component.name)
        file = SourcePackageReleaseFile.selectOneBy(
            sourcepackagereleaseID=spr.id, filetype=SourcePackageFileType.DSC)
        full_path = 'pool/%s/%s' % (path, file.libraryfile.filename)
        return urlappend(base_url, full_path)


class MirrorProbeRecord(SQLBase):
    """See IMirrorProbeRecord"""

    implements(IMirrorProbeRecord)
    _table = 'MirrorProbeRecord'
    _defaultOrder = 'id'

    distribution_mirror = ForeignKey(
        dbName='distribution_mirror', foreignKey='DistributionMirror',
        notNull=True)
    log_file = ForeignKey(
        dbName='log_file', foreignKey='LibraryFileAlias', default=None)
    date_created = UtcDateTimeCol(notNull=True, default=UTC_NOW)

