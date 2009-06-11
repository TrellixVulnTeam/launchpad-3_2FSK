# Copyright 2008-2009 Canonical Ltd.  All rights reserved.

"""Update the interface schema values due to circular imports.

There are situations where there would normally be circular imports to define
the necessary schema values in some interface fields.  To avoid this the
schema is initially set to `Interface`, but this needs to be updated once the
types are defined.
"""

__metaclass__ = type


__all__ = []


from lazr.restful.declarations import LAZR_WEBSERVICE_EXPORTED

from canonical.launchpad.components.apihelpers import (
    patch_entry_return_type, patch_collection_property,
    patch_collection_return_type, patch_plain_parameter_type,
    patch_choice_parameter_type, patch_reference_property)

from lp.bugs.interfaces.bug import IBug
from lp.bugs.interfaces.bugbranch import IBugBranch
from lp.bugs.interfaces.bugtask import IBugTask
from lp.soyuz.interfaces.build import (
    BuildStatus, IBuild)
from lp.soyuz.interfaces.buildrecords import IHasBuildRecords
from lp.blueprints.interfaces.specification import ISpecification
from lp.blueprints.interfaces.specificationbranch import (
    ISpecificationBranch)
from lp.code.interfaces.branch import IBranch
from lp.code.interfaces.branchmergeproposal import IBranchMergeProposal
from lp.code.interfaces.branchsubscription import IBranchSubscription
from lp.code.interfaces.codereviewcomment import ICodeReviewComment
from lp.code.interfaces.codereviewvote import ICodeReviewVoteReference
from lp.code.interfaces.hasbranches import IHasBranches, IHasMergeProposals
from canonical.launchpad.interfaces.diff import IPreviewDiff
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage)
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.person import IPerson, IPersonPublic
from canonical.launchpad.interfaces.hwdb import IHWSubmission
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.soyuz.interfaces.archive import IArchive
from lp.soyuz.interfaces.archivepermission import (
    IArchivePermission)
from lp.soyuz.interfaces.archivesubscriber import (
    IArchiveSubscriber)
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries
from lp.soyuz.interfaces.publishing import (
    IBinaryPackagePublishingHistory, ISecureBinaryPackagePublishingHistory,
    ISecureSourcePackagePublishingHistory, ISourcePackagePublishingHistory,
    PackagePublishingPocket, PackagePublishingStatus)
from lp.soyuz.interfaces.packageset import IPackageset
from lp.registry.interfaces.sourcepackage import ISourcePackage


IBranch['product'].schema = IProduct
IBranch['subscriptions'].value_type.schema = IBranchSubscription
IBranch['landing_targets'].value_type.schema = IBranchMergeProposal
IBranch['landing_candidates'].value_type.schema = IBranchMergeProposal
IBranch['dependent_branches'].value_type.schema = IBranchMergeProposal
IBranch['subscribe'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['return_type'].schema = IBranchSubscription
IBranch['bug_branches'].value_type.schema = IBugBranch
IBranch['spec_links'].value_type.schema = ISpecificationBranch

IBranchMergeProposal['getComment'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['return_type'].schema = ICodeReviewComment
IBranchMergeProposal['createComment'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['params']['parent'].schema = \
        ICodeReviewComment
IBranchMergeProposal['all_comments'].value_type.schema = ICodeReviewComment
IBranchMergeProposal['votes'].value_type.schema = ICodeReviewVoteReference

IHasBranches['getBranches'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['return_type'].value_type.schema = \
        IBranch
IHasMergeProposals['getMergeProposals'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['return_type'].value_type.schema = \
        IBranchMergeProposal

# IBug

IBug['addBranch'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['return_type'].schema = IBugBranch

# IBugTask

IBugTask['findSimilarBugs'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['return_type'].value_type.schema = IBug
patch_plain_parameter_type(
    IBug, 'linkHWSubmission', 'submission', IHWSubmission)
patch_plain_parameter_type(
    IBug, 'unlinkHWSubmission', 'submission', IHWSubmission)
patch_collection_return_type(
    IBug, 'getHWSubmissions', IHWSubmission)

IPreviewDiff['branch_merge_proposal'].schema = IBranchMergeProposal

patch_reference_property(IPersonPublic, 'archive', IArchive)
patch_collection_property(IPersonPublic, 'ppas', IArchive)
patch_entry_return_type(IPersonPublic, 'getPPAByName', IArchive)

IHasBuildRecords['getBuildRecords'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)[
        'params']['pocket'].vocabulary = PackagePublishingPocket
IHasBuildRecords['getBuildRecords'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)[
        'params']['build_state'].vocabulary = BuildStatus
IHasBuildRecords['getBuildRecords'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)[
        'return_type'].value_type.schema = IBuild

ISourcePackage['distroseries'].schema = IDistroSeries
ISourcePackage['productseries'].schema = IProductSeries
ISourcePackage['getBranch'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)[
        'params']['pocket'].vocabulary = PackagePublishingPocket
ISourcePackage['getBranch'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['return_type'].schema = IBranch
ISourcePackage['setBranch'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)[
        'params']['pocket'].vocabulary = PackagePublishingPocket
ISourcePackage['setBranch'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['params']['branch'].schema = IBranch
patch_reference_property(ISourcePackage, 'distribution', IDistribution)

ISpecification['linkBranch'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['return_type'].schema = ISpecificationBranch

IPerson['hardware_submissions'].value_type.schema = IHWSubmission

# publishing.py
ISourcePackagePublishingHistory['getBuilds'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['return_type'].value_type.schema = IBuild
ISourcePackagePublishingHistory['getPublishedBinaries'].queryTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)[
    'return_type'].value_type.schema = IBinaryPackagePublishingHistory
patch_reference_property(
    ISecureBinaryPackagePublishingHistory, 'distroarchseries',
    IDistroArchSeries)
patch_reference_property(
    ISecureBinaryPackagePublishingHistory, 'archive', IArchive)
patch_reference_property(
    ISecureSourcePackagePublishingHistory, 'archive', IArchive)

# IArchive apocalypse.
patch_reference_property(IArchive, 'distribution', IDistribution)
patch_collection_return_type(
    IArchive, 'getPermissionsForPerson', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getUploadersForPackage', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getUploadersForComponent', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getQueueAdminsForComponent', IArchivePermission)
patch_collection_return_type(
    IArchive, 'getComponentsForQueueAdmin', IArchivePermission)
patch_entry_return_type(IArchive, 'newPackageUploader', IArchivePermission)
patch_entry_return_type(IArchive, 'newComponentUploader', IArchivePermission)
patch_entry_return_type(IArchive, 'newQueueAdmin', IArchivePermission)
patch_plain_parameter_type(IArchive, 'syncSources', 'from_archive', IArchive)
patch_plain_parameter_type(IArchive, 'syncSource', 'from_archive', IArchive)
patch_entry_return_type(IArchive, 'newSubscription', IArchiveSubscriber)
patch_plain_parameter_type(
    IArchive, 'getPublishedSources', 'distroseries', IDistroSeries)
patch_collection_return_type(
    IArchive, 'getPublishedSources', ISourcePackagePublishingHistory)
patch_choice_parameter_type(
    IArchive, 'getPublishedSources', 'status', PackagePublishingStatus)
patch_choice_parameter_type(
    IArchive, 'getPublishedSources', 'pocket', PackagePublishingPocket)
patch_plain_parameter_type(
    IArchive, 'getAllPublishedBinaries', 'distroarchseries',
    IDistroArchSeries)
patch_collection_return_type(
    IArchive, 'getAllPublishedBinaries', IBinaryPackagePublishingHistory)
patch_choice_parameter_type(
    IArchive, 'getAllPublishedBinaries', 'status', PackagePublishingStatus)
patch_choice_parameter_type(
    IArchive, 'getAllPublishedBinaries', 'pocket', PackagePublishingPocket)

# IDistribution
IDistribution['serieses'].value_type.schema = IDistroSeries
patch_reference_property(
    IDistribution, 'currentseries', IDistroSeries)
patch_entry_return_type(
    IDistribution, 'getSeries', IDistroSeries)
patch_collection_return_type(
    IDistribution, 'getDevelopmentSerieses', IDistroSeries)
patch_entry_return_type(
    IDistribution, 'getSourcePackage', IDistributionSourcePackage)
patch_collection_return_type(
    IDistribution, 'searchSourcePackages', IDistributionSourcePackage)
patch_reference_property(
    IDistribution, 'main_archive', IArchive)
IDistribution['all_distro_archives'].value_type.schema = IArchive


# IDistroSeries
patch_entry_return_type(
    IDistroSeries, 'getDistroArchSeries', IDistroArchSeries)
patch_reference_property(
    IDistroSeries, 'main_archive', IArchive)
patch_reference_property(
    IDistroSeries, 'distribution', IDistribution)

# IDistroArchSeries
patch_reference_property(IDistroArchSeries, 'main_archive', IArchive)

# IPackageset
patch_collection_return_type(
    IPackageset, 'setsIncluded', IPackageset)
patch_collection_return_type(
    IPackageset, 'setsIncludedBy', IPackageset)
patch_plain_parameter_type(
    IPackageset, 'getSourcesSharedBy', 'other_package_set', IPackageset)
patch_plain_parameter_type(
    IPackageset, 'getSourcesNotSharedBy', 'other_package_set', IPackageset)
