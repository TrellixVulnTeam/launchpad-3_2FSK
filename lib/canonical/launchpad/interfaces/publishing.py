# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Publishing interfaces."""

__metaclass__ = type

__all__ = [
    'IBinaryPackagePublishing',
    'ISourcePackagePublishing',
    'ISourcePackageFilePublishing',
    'IBinaryPackageFilePublishing',
    'ISourcePackagePublishingView',
    'IBinaryPackagePublishingView',
    'ISecureSourcePackagePublishingHistory',
    'ISecureBinaryPackagePublishingHistory',
    'ISourcePackagePublishingHistory',
    'IBinaryPackagePublishingHistory',
    ]

from zope.schema import Bool, Datetime, Int, TextLine
from zope.interface import Interface, Attribute
from zope.i18nmessageid import MessageIDFactory

_ = MessageIDFactory('launchpad')

#
# Source package publishing
#

class IBaseSourcePackagePublishing(Interface):
    distribution = Int(
            title=_('Distribution ID'), required=True, readonly=True,
            )
    distroreleasename = TextLine(
            title=_('Distro Release name'), required=True, readonly=True,
            )
    sourcepackagename = TextLine(
            title=_('Binary package name'), required=True, readonly=True,
            )
    componentname = TextLine(
            title=_('Component name'), required=True, readonly=True,
            )
    publishingstatus = Int(
            title=_('Package publishing status'), required=True, readonly=True,
            )
    pocket = Int(
            title=_('Package publishing pocket'), required=True, readonly=True,
            )


class ISourcePackagePublishingView(IBaseSourcePackagePublishing):
    """Source package publishing information neatened up a bit"""
    sectionname = TextLine(
            title=_('Section name'), required=True, readonly=True,
            )


class ISourcePackageFilePublishing(IBaseSourcePackagePublishing):
    """Source package release files and their publishing status"""
    sourcepackagepublishing = Int(
            title=_('Sourcepackage publishing record id'), required=True,
            readonly=True,
            )
    libraryfilealias = Int(
            title=_('Sourcepackage release file alias'), required=True,
            readonly=True,
            )
    libraryfilealiasfilename = TextLine(
            title=_('File name'), required=True, readonly=True,
            )


class ISourcePackagePublishing(Interface):
    """A source package publishing record."""
    id = Int(
            title=_('ID'), required=True, readonly=True,
            )
    sourcepackagerelease = Int(
            title=_('The source package release being published'),
            required=False, readonly=False,
            )
    status = Int(
            title=_('The status of this publishing record'),
            required=False, readonly=False,
            )
    distrorelease = Int(
            title=_('The distrorelease being published into'),
            required=False, readonly=False,
            )
    component = Int(
            title=_('The component being published into'),
            required=False, readonly=False,
            )
    section = Int(
            title=_('The section being published into'),
            required=False, readonly=False,
            )
    datepublished = Datetime(
            title=_('The date on which this record was published'),
            required=False, readonly=False,
            )
    scheduleddeletiondate = Datetime(
            title=_('The date on which this record is scheduled for deletion'),
            required=False, readonly=False,
            )
    pocket = Int(
            title=_('The pocket into which this entry is published'),
            required=True, readonly=True,
            )


class IExtendedSourcePackagePublishing(ISourcePackagePublishing):
    supersededby = Int(
            title=_('The sourcepackagerelease which superseded this one'),
            required=False, readonly=False,
            )
    datesuperseded = Datetime(
            title=_('The date on which this record was marked superseded'),
            required=False, readonly=False,
            )
    datecreated = Datetime(
            title=_('The date on which this record was created'),
            required=True, readonly=False,
            )
    datemadepending = Datetime(
            title=_('The date on which this record was set as pending removal'),
            required=False, readonly=False,
            )
    dateremoved = Datetime(
            title=_('The date on which this record was removed from the '
                    'published set'),
            required=False, readonly=False,
            )


class ISecureSourcePackagePublishingHistory(IExtendedSourcePackagePublishing):
    """A source package publishing history record."""
    embargo = Bool(
            title=_('Whether or not this record is under embargo'),
            required=True, readonly=False,
            )
    embargolifted = Datetime(
            title=_('The date on which this record had its embargo lifted'),
            required=False, readonly=False,
            )


class ISourcePackagePublishingHistory(IExtendedSourcePackagePublishing):
    """A source package publishing history record."""
    meta_sourcepackage = Attribute(
        "Return an ISourcePackage meta object correspondent to the "
        "sourcepackagerelease attribute inside a specific distrorelease")
    meta_sourcepackagerelease = Attribute(
        "Return an IDistribuitionSourcePackageRelease meta object "
        "correspondent to the sourcepackagerelease attribute")
    meta_supersededby = Attribute(
        "Return an IDistribuitionSourcePackageRelease meta object "
        "correspondent to the supersededby attribute. if supersededby "
        "is None return None.")

#
# Binary package publishing
#


class IBaseBinaryPackagePublishing(Interface):
    distribution = Int(
            title=_('Distribution ID'), required=True, readonly=True,
            )
    distroreleasename = TextLine(
            title=_('Distribution release name'), required=True, readonly=True,
            )
    componentname = TextLine(
            title=_('Component name'), required=True, readonly=True,
            )
    publishingstatus = Int(
            title=_('Package publishing status'), required=True, readonly=True,
            )
    pocket = Int(
            title=_('Package publishing pocket'), required=True, readonly=True,
            )


class IBinaryPackagePublishingView(IBaseBinaryPackagePublishing):
    """Binary package publishing information neatened up a bit"""
    binarypackagename = TextLine(
            title=_('Binary package name'), required=True, readonly=True,
            )
    sectionname = TextLine(
            title=_('Section name'), required=True, readonly=True,
            )
    priority = Int(
            title=_('Priority'), required=True, readonly=True,
            )


class IBinaryPackageFilePublishing(IBaseBinaryPackagePublishing):
    """Binary package files and their publishing status"""
    # Note that it is really /source/ package name below, and not a
    # thinko; at least, that's what Celso tells me the code uses
    #   -- kiko, 2006-03-22
    sourcepackagename = TextLine(
            title=_('Source package name'), required=True, readonly=True,
            )
    binarypackagepublishing = Int(
            title=_('Binary Package publishing record id'), required=True,
            readonly=True,
            )
    libraryfilealias = Int(
            title=_('Binarypackage file alias'), required=True,
            readonly=True,
            )
    libraryfilealiasfilename = TextLine(
            title=_('File name'), required=True, readonly=True,
            )
    architecturetag = TextLine(
            title=_("Architecture tag. As per dpkg's use"), required=True,
            readonly=True,
            )


class IBinaryPackagePublishing(Interface):
    """A binary package publishing record."""
    id = Int(
            title=_('ID'), required=True, readonly=True,
            )
    binarypackagerelease = Int(
            title=_('The binary package being published'), required=False,
            readonly=False,
            )
    distroarchrelease = Int(
            title=_('The distroarchrelease being published into'),
            required=False, readonly=False,
            )
    component = Int(
            title=_('The component being published into'),
            required=False, readonly=False,
            )
    section = Int(
            title=_('The section being published into'),
            required=False, readonly=False,
            )
    priority = Int(
            title=_('The priority being published into'),
            required=False, readonly=False,
            )
    datepublished = Datetime(
            title=_('The date on which this record was published'),
            required=False, readonly=False,
            )
    scheduleddeletiondate = Datetime(
            title=_('The date on which this record is scheduled for deletion'),
            required=False, readonly=False,
            )
    status = Int(
            title=_('The status of this publishing record'),
            required=False, readonly=False,
            )
    pocket = Int(
            title=_('The pocket into which this entry is published'),
            required=True, readonly=True,
            )
    distroarchreleasebinarypackagerelease = Attribute("The object that "
        "represents this binarypacakgerelease in this distroarchrelease.")


class IExtendedBinaryPackagePublishing(IBinaryPackagePublishing):
    supersededby = Int(
            title=_('The build which superseded this one'),
            required=False, readonly=False,
            )
    datecreated = Datetime(
            title=_('The date on which this record was created'),
            required=True, readonly=False,
            )
    datesuperseded = Datetime(
            title=_('The date on which this record was marked superseded'),
            required=False, readonly=False,
            )
    datemadepending = Datetime(
            title=_('The date on which this record was set as pending removal'),
            required=False, readonly=False,
            )
    dateremoved = Datetime(
            title=_('The date on which this record was removed from the '
                    'published set'),
            required=False, readonly=False,
            )


class ISecureBinaryPackagePublishingHistory(IExtendedBinaryPackagePublishing):
    """A binary package publishing record."""
    embargo = Bool(
            title=_('Whether or not this record is under embargo'),
            required=True, readonly=False,
            )
    embargolifted = Datetime(
            title=_('The date and time at which this record had its '
                    'embargo lifted'),
            required=False, readonly=False,
            )


class IBinaryPackagePublishingHistory(IExtendedBinaryPackagePublishing):
    """A binary package publishing record."""
    hasRemovalRequested = Bool(
            title=_('Whether a removal has been requested for this record')
            )
