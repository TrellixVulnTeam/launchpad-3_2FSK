/*
  Add Comments to Launchpad database. Please keep these alphabetical by
  table.
*/

/* Branch */

COMMENT ON TABLE Branch IS 'Bzr branch';
COMMENT ON COLUMN Branch.mirror_status_message IS 'The last message we got when mirroring this branch.';
COMMENT ON COLUMN Branch.last_mirrored IS 'The time when the branch was last mirrored.';
COMMENT ON COLUMN Branch.last_mirrored_id IS 'The revision ID of the branch when it was last mirrored.';
COMMENT ON COLUMN Branch.last_scanned IS 'The time when the branch was last scanned.';
COMMENT ON COLUMN Branch.last_scanned_id IS 'The revision ID of the branch when it was last scanned.';

/* Bug */

COMMENT ON TABLE Bug IS 'A software bug that requires fixing. This particular bug may be linked to one or more products or source packages to identify the location(s) that this bug is found.';
COMMENT ON COLUMN Bug.name IS 'A lowercase name uniquely identifying the bug';
COMMENT ON COLUMN Bug.private IS 'Is this bug private? If so, only explicit subscribers will be able to see it';
COMMENT ON COLUMN Bug.security_related IS 'Is this bug a security issue?';
COMMENT ON COLUMN Bug.description IS 'A detailed description of the bug. Initially this will be set to the contents of the initial email or bug filing comment, but later it can be edited to give a more accurate description of the bug itself rather than the symptoms observed by the reporter.';

/* BugBranch */
COMMENT ON TABLE BugBranch IS 'A branch related to a bug, most likely a branch for fixing the bug.';
COMMENT ON COLUMN BugBranch.bug IS 'The bug associated with this branch.';
COMMENT ON COLUMN BugBranch.branch IS 'The branch associated to the bug.';
COMMENT ON COLUMN BugBranch.revision_hint IS 'An optional revision at which this branch became interesting to this bug, and/or may contain a fix for the bug.';
COMMENT ON COLUMN BugBranch.status IS 'The status of the bugfix in this branch.';
COMMENT ON COLUMN BugBranch.whiteboard IS 'Additional information about the status of the bugfix in this branch.';

/* BugTag */
COMMENT ON TABLE BugTag IS 'Attaches simple text tags to a bug.';
COMMENT ON COLUMN BugTag.bug IS 'The bug the tags is attached to.';
COMMENT ON COLUMN BugTag.tag IS 'The text representation of the tag.';

/* BugTask */

COMMENT ON TABLE BugTask IS 'Links a given Bug to a particular (sourcepackagename, distro) or product.';
COMMENT ON COLUMN BugTask.targetnamecache IS 'A cached value of the target name of this bugtask, to make it easier to sort and search on the target name.';
COMMENT ON COLUMN BugTask.bug IS 'The bug that is assigned to this (sourcepackagename, distro) or product.';
COMMENT ON COLUMN BugTask.product IS 'The product in which this bug shows up.';
COMMENT ON COLUMN BugTask.sourcepackagename IS 'The name of the sourcepackage in which this bug shows up.';
COMMENT ON COLUMN BugTask.distribution IS 'The distro of the named sourcepackage.';
COMMENT ON COLUMN BugTask.status IS 'The general health of the bug, e.g. Accepted, Rejected, etc.';
COMMENT ON COLUMN BugTask.importance IS 'The importance of fixing the bug.';
COMMENT ON COLUMN BugTask.priority IS 'Obsolete.';
COMMENT ON COLUMN BugTask.binarypackagename IS 'The name of the binary package built from the source package. This column may only contain a value if this bug task is linked to a sourcepackage (not a product)';
COMMENT ON COLUMN BugTask.assignee IS 'The person who has been assigned to fix this bug in this product or (sourcepackagename, distro)';
COMMENT ON COLUMN BugTask.date_assigned IS 'The date on which the bug in this (sourcepackagename, distro) or product was assigned to someone to fix';
COMMENT ON COLUMN BugTask.datecreated IS 'A timestamp for the creation of this bug assignment. Note that this is not the date the bug was created (though it might be), it''s the date the bug was assigned to this product, which could have come later.';
COMMENT ON COLUMN BugTask.date_confirmed IS 'The date when this bug transitioned from an unconfirmed status to a confirmed one. If the state regresses to a one that logically occurs before Confirmed, e.g., Unconfirmed, this date is cleared.';
COMMENT ON COLUMN BugTask.date_inprogress IS 'The date on which this bug transitioned from not being in progress to a state >= In Progress. If the status moves back to a pre-In Progress state, this date is cleared';
COMMENT ON COLUMN BugTask.date_closed IS 'The date when this bug transitioned to a resolved state, e.g., Rejected, Fix Released, etc. If the state changes back to a pre-closed state, this date is cleared';
COMMENT ON COLUMN BugTask.milestone IS 'A way to mark a bug for grouping purposes, e.g. to say it needs to be fixed by version 1.2';
COMMENT ON COLUMN BugTask.statusexplanation IS 'A place to store bug task specific information as free text';
COMMENT ON COLUMN BugTask.bugwatch IS 'This column allows us to link a bug
task to a bug watch. In other words, we are connecting the state of the task
to the state of the bug in a different bug tracking system. To the best of
our ability we\'ll try and keep the bug task syncronised with the state of
the remote bug watch.';


-- BugExternalRef

COMMENT ON TABLE BugExternalRef IS 'A table to store web links to related content for bugs.';
COMMENT ON COLUMN BugExternalRef.bug IS 'The bug to which this URL is relevant.';
COMMENT ON COLUMN BugExternalRef.owner IS 'This refers to the person who created the link.';


-- BugNotification

COMMENT ON TABLE BugNotification IS 'The text representation of changes to a bug, which are used to send email notifications to bug changes.';
COMMENT ON COLUMN BugNotification.bug IS 'The bug that was changed.';
COMMENT ON COLUMN BugNotification.message IS 'The message the contains the textual representation of the change.';
COMMENT ON COLUMN BugNotification.is_comment IS 'Is the change a comment addition.';
COMMENT ON COLUMN BugNotification.date_emailed IS 'When this notification was emailed to the bug subscribers.';


/* BugPackageInfestation */

COMMENT ON TABLE BugPackageInfestation IS 'A BugPackageInfestation records the impact that a bug is known to have on a specific sourcepackagerelease. This allows us to track the versions of a package that are known to be affected or unaffected by a bug.';
COMMENT ON COLUMN BugPackageInfestation.bug IS 'The Bug that infests this source package release.';
COMMENT ON COLUMN BugPackageInfestation.sourcepackagerelease IS 'The package (software) release that is infested with the bug. This points at the specific source package release version, such as "apache 2.0.48-1".';
COMMENT ON COLUMN BugPackageInfestation.explicit IS 'This field records whether or not the infestation was documented by a user of the system, or inferred from some other source such as the fact that it is documented to affect prior and subsequent releases of the package.';
COMMENT ON COLUMN BugPackageInfestation.infestationstatus IS 'The nature of the bug infestation for this source package release. Values are documented in dbschema.BugInfestationStatus, and include AFFECTED, UNAFFECTED, FIXED and VICTIMISED. See the dbschema.py file for details.';
COMMENT ON COLUMN BugPackageInfestation.creator IS 'The person who recorded this infestation. Typically, this is the user who reports the specific problem on that specific package release.';
COMMENT ON COLUMN BugPackageInfestation.verifiedby IS 'The person who verified that this infestation affects this specific package.';
COMMENT ON COLUMN BugPackageInfestation.dateverified IS 'The timestamp when the problem was verified on that specific release. This a small step towards a complete workflow for defect verification and management on specific releases.';
COMMENT ON COLUMN BugPackageInfestation.lastmodified IS 'The timestamp when this infestation report was last modified in any way. For example, when the infestation was adjusted, or it was verified, or otherwise modified.';
COMMENT ON COLUMN BugPackageInfestation.lastmodifiedby IS 'The person who touched this infestation report last, in any way.';

/* BugProductInfestation */

COMMENT ON TABLE BugProductInfestation IS 'A BugProductInfestation records the impact that a bug is known to have on a specific productrelease. This allows us to track the versions of a product that are known to be affected or unaffected by a bug.';
COMMENT ON COLUMN BugProductInfestation.bug IS 'The Bug that infests this product release.';
COMMENT ON COLUMN BugProductInfestation.productrelease IS 'The product (software) release that is infested with the bug. This points at the specific release version, such as "apache 2.0.48".';
COMMENT ON COLUMN BugProductInfestation.explicit IS 'This field records whether or not the infestation was documented by a user of the system, or inferred from some other source such as the fact that it is documented to affect prior and subsequent releases of the product.';
COMMENT ON COLUMN BugProductInfestation.infestationstatus IS 'The nature of the bug infestation for this product release. Values are documented in dbschema.BugInfestationStatus, and include AFFECTED, UNAFFECTED, FIXED and VICTIMISED. See the dbschema.py file for details.';
COMMENT ON COLUMN BugProductInfestation.creator IS 'The person who recorded this infestation. Typically, this is the user who reports the specific problem on that specific product release.';
COMMENT ON COLUMN BugProductInfestation.verifiedby IS 'The person who verified that this infestation affects this specific product release.';
COMMENT ON COLUMN BugProductInfestation.dateverified IS 'The timestamp when the problem was verified on that specific release. This a small step towards a complete workflow for defect verification and management on specific releases.';
COMMENT ON COLUMN BugProductInfestation.lastmodified IS 'The timestamp when this infestation report was last modified in any way. For example, when the infestation was adjusted, or it was verified, or otherwise modified.';
COMMENT ON COLUMN BugProductInfestation.lastmodifiedby IS 'The person who touched this infestation report last, in any way.';

/* BugTracker */

COMMENT ON TABLE BugTracker IS 'A bug tracker in some other project. Malone allows us to link Malone bugs with bugs recorded in other bug tracking systems, and to keep the status of the relevant bug task in sync with the status in that upstream bug tracker. So, for example, you might note that Malone bug #43224 is the same as a bug in the Apache bugzilla, number 534536. Then when the upstream guys mark that bug fixed in their bugzilla, Malone know that the bug is fixed upstream.';
COMMENT ON COLUMN BugTracker.bugtrackertype IS 'The type of bug tracker, a pointer to the table of bug tracker types. Currently we know about debbugs and bugzilla bugtrackers, and plan to support roundup and sourceforge as well.';
COMMENT ON COLUMN BugTracker.name IS 'The unique name of this bugtracker, allowing us to refer to it directly.';
COMMENT ON COLUMN BugTracker.summary IS 'A brief summary of this bug tracker, which might for example list any interesting policies regarding the use of the bug tracker. The summary is displayed in bold at the top of the bug tracker page.';
COMMENT ON COLUMN BugTracker.title IS 'A title for the bug tracker, used in listings of all the bug trackers and also displayed at the top of the descriptive page for the bug tracker.';
COMMENT ON COLUMN BugTracker.contactdetails IS 'The contact details of the people responsible for that bug tracker. This allows us to coordinate the syncing of bugs to and from that bug tracker with the responsible people on the other side.';
COMMENT ON COLUMN BugTracker.baseurl IS 'The base URL for this bug tracker. Using our knowledge of the bugtrackertype, and the details in the BugWatch table we are then able to calculate relative URL\'s for relevant pages in the bug tracker based on this baseurl.';
COMMENT ON COLUMN BugTracker.owner IS 'The person who created this bugtracker entry and who thus has permission to modify it. Ideally we would like this to be the person who coordinates the running of the actual bug tracker upstream.';


/* BugCve */

COMMENT ON TABLE BugCve IS 'A table that records the link between a given malone bug number, and a CVE entry.';


/* CVE */

COMMENT ON TABLE CVE IS 'A CVE Entry. The formal database of CVE entries is available at http://cve.mitre.org/ and we sync that database into Launchpad on a regular basis.';
COMMENT ON COLUMN CVE.sequence IS 'The official CVE entry number. It takes the form XXXX-XXXX where the first four digits are a year indicator, like 2004, and the latter four are the sequence number of the vulnerability in that year.';
COMMENT ON COLUMN CVE.status IS 'The current status of the CVE. The values are documented in dbschema.CVEState, and are Entry, Candidate, and Deprecated.';
COMMENT ON COLUMN CVE.datemodified IS 'The last time this CVE entry changed in some way - including addition or modification of references.';


/* CveReference */

COMMENT ON TABLE CveReference IS 'A reference in the CVE system that shows what outside tracking numbers are associated with the CVE. These are tracked in the CVE database and extracted from the daily XML dump that we fetch.';
COMMENT ON COLUMN CveReference.source IS 'The SOURCE of the CVE reference. This is a text string, like XF or BUGTRAQ or MSKB. Each string indicates a different kind of reference. The list of known types is documented on the CVE web site. At some future date we might turn this into an enum rather than a text, but for the moment we prefer to keep it fluid and just suck in what CVE gives us. This means that CVE can add new source types without us having to update our code.';
COMMENT ON COLUMN CveReference.url IS 'The URL to this reference out there on the web, if it was present in the CVE database.';
COMMENT ON COLUMN CveReference.content IS 'The content of the ref in the CVE database. This is sometimes a comment, sometimes a description, sometimes a bug number... it is not predictable.';


-- DevelopmentManifest
COMMENT ON TABLE DevelopmentManifest IS 'A table that keeps track of the "intermediate commits" during the development of a source package. A developer using HCT will make regular commits (stored locally, as Bazaar revisions). On occasion, the developer will "publish" the current state of the package. This results in the Bazaar branches being made available on a public server, and a DevelopmentManifest being created. Other people will then see the existence of the Development Manifest and know that the person is currently working on a variation of the package. When the developer believes that the page is actually ready to build, they can "release" the package. This results in a SourcePackageRelease being assembled, based on the existing development manifest.';
COMMENT ON COLUMN DevelopmentManifest.distrorelease IS 'The distribution release for which this source package is being developed. Note that the source package may very well be built and published in other releases as well - this information is purely a starting point indicator.';
COMMENT ON COLUMN DevelopmentManifest.sourcepackagename IS 'Again, this is just an indicator of the place the developer is primarily targeting the work. This same package may actually be uploaded under a different name somewhere else eventually.';


/* DistributionSourcePackageCache */

COMMENT ON TABLE DistributionSourcePackageCache IS 'A cache of the text associated with binary and source packages in the distribution. This table allows for fast queries to find a source packagename that matches a given text.';
COMMENT ON COLUMN DistributionSourcePackageCache.distribution IS 'The distribution in which we are checking.';
COMMENT ON COLUMN DistributionSourcePackageCache.sourcepackagename IS 'The source package name for which we are caching details.';
COMMENT ON COLUMN DistributionSourcePackageCache.name IS 'The source package name itself. This is just a copy of the value of sourcepackagename.name. We have it here so it can be part of the full text index.';
COMMENT ON COLUMN DistributionSourcePackageCache.binpkgnames IS 'The binary package names of binary packages generated from these source packages across all architectures.';
COMMENT ON COLUMN DistributionSourcePackageCache.binpkgsummaries IS 'The aggregated summaries of all the binary packages generated from these source packages in this distribution.';
COMMENT ON COLUMN DistributionSourcePackageCache.binpkgdescriptions IS 'The aggregated description of all the binary packages generated from these source packages in this distribution.';


/* DistroReleasePackageCache */

COMMENT ON TABLE DistroReleasePackageCache IS 'A cache of the text associated with binary packages in the distrorelease. This table allows for fast queries to find a binary packagename that matches a given text.';
COMMENT ON COLUMN DistroReleasePackageCache.distrorelease IS 'The distrorelease in which we are checking.';
COMMENT ON COLUMN DistroReleasePackageCache.binarypackagename IS 'The binary package name for which we are caching details.';
COMMENT ON COLUMN DistroReleasePackageCache.name IS 'The binary package name itself. This is just a copy of the value of binarypackagename.name. We have it here so it can be part of the full text index.';
COMMENT ON COLUMN DistroReleasePackageCache.summary IS 'A single summary for one of the binary packages of this name in this distrorelease. We could potentially have binary packages in different architectures with the same name and different summaries, so this is a way of collapsing to one arbitrarily-chosen one, for display purposes. The chances of actually having different summaries and descriptions is pretty small. It could happen, though, because of the way package superseding works when a package does not build on a specific architecture.';
COMMENT ON COLUMN DistroReleasePackageCache.summaries IS 'The aggregated summaries of all the binary packages with this name in this distrorelease.';
COMMENT ON COLUMN DistroReleasePackageCache.descriptions IS 'The aggregated description of all the binary packages with this name in this distrorelease.';


-- EmailAddress

COMMENT ON COLUMN EmailAddress.email IS 'An email address used by a Person. The email address is stored in a casesensitive way, but must be case insensitivly unique.';
COMMENT ON INDEX emailaddress_person_key IS 'Ensures that a person only has one preferred email address';


-- KarmaCategory

COMMENT ON TABLE KarmaCategory IS 'A category of karma. This allows us to
present an overall picture of the different areas where a user has been
active.';


-- LaunchpadStatistic

COMMENT ON TABLE LaunchpadStatistic IS 'A store of system-wide statistics or other integer values, keyed by names. The names are unique and the values can be any integer. Each field has a place to store the timestamp when it was last updated, so it is possible to know how far out of date any given statistic is.';


-- Product
COMMENT ON TABLE Product IS 'Product: a DOAP Product. This table stores core information about an open source product. In Launchpad, anything that can be shipped as a tarball would be a product, and in some cases there might be products for things that never actually ship, depending on the project. For example, most projects will have a \'website\' product, because that allows you to file a Malone bug against the project website. Note that these are not actual product releases, which are stored in the ProductRelease table.';
COMMENT ON COLUMN Product.owner IS 'The Product owner would typically be the person who createed this product in Launchpad. But we will encourage the upstream maintainer of a product to become the owner in Launchpad. The Product owner can edit any aspect of the Product, as well as appointing people to specific roles with regard to the Product. Also, the owner can add a new ProductRelease and also edit Rosetta POTemplates associated with this product.';
COMMENT ON COLUMN Product.summary IS 'A brief summary of the product. This will be displayed in bold at the top of the product page, above the description.';
COMMENT ON COLUMN Product.description IS 'A detailed description of the product, highlighting primary features of the product that may be of interest to end-users. The description may also include links and other references to useful information on the web about this product. The description will be displayed on the product page, below the product summary.';
COMMENT ON COLUMN Product.project IS 'Every Product belongs to one and only one Project, which is referenced in this column.';
COMMENT ON COLUMN Product.listurl IS 'This is the URL where information about a mailing list for this Product can be found. The URL might point at a web archive or at the page where one can subscribe to the mailing list.';
COMMENT ON COLUMN Product.programminglang IS 'This field records, in plain text, the name of any significant programming languages used in this product. There are no rules, conventions or restrictions on this field at present, other than basic sanity. Examples might be "Python", "Python, C" and "Java".';
COMMENT ON COLUMN Product.downloadurl IS 'The download URL for a Product should be the best place to download that product, typically off the relevant Project web site. This should not point at the actual file, but at a web page with download information.';
COMMENT ON COLUMN Product.lastdoap IS 'This column stores a cached copy of the last DOAP description we saw for this product. See the Project.lastdoap field for more info.';
COMMENT ON COLUMN Product.sourceforgeproject IS 'The SourceForge project name for this product. This is not unique as SourceForge doesn\'t use the same project/product structure as DOAP.';
COMMENT ON COLUMN Product.freshmeatproject IS 'The FreshMeat project name for this product. This is not unique as FreshMeat does not have the same project/product structure as DOAP';
COMMENT ON COLUMN Product.reviewed IS 'Whether or not someone at Canonical has reviewed this product.';
COMMENT ON COLUMN Product.active IS 'Whether or not this product should be considered active.';
COMMENT ON COLUMN Product.translationgroup IS 'The TranslationGroup that is responsible for translations for this product. Note that the Product may be part of a Project which also has a TranslationGroup, in which case the translators from both the product and project translation group have permission to edit the translations of this product.';
COMMENT ON COLUMN Product.translationpermission IS 'The level of openness of this product\'s translation process. The enum lists different approaches to translation, from the very open (anybody can edit any translation in any language) to the completely closed (only designated translators can make any changes at all).';
COMMENT ON COLUMN Product.releaseroot IS 'The URL to the directory which holds upstream releases for this product. This allows us to monitor the upstream site and detect new upstream release tarballs.  This URL is used when the associated ProductSeries does not have a URL to use. It is also used to find files outside of any registered series.';
COMMENT ON COLUMN Product.calendar IS 'The calendar associated with this product.';
COMMENT ON COLUMN Product.official_rosetta IS 'Whether or not this product upstream uses Rosetta for its official translation team and coordination. This is a useful indicator in terms of whether translations in Rosetta for this upstream will quickly move upstream.';
COMMENT ON COLUMN Product.official_malone IS 'Whether or not this product upstream uses Malone for an official bug tracker. This is useful to help indicate whether or not people are likely to pick up on bugs registered in Malone.';
COMMENT ON COLUMN Product.bugcontact IS 'Person who will be automatically subscribed to bugs targetted to this product';
COMMENT ON COLUMN Product.security_contact IS 'The person or team who handles security-related issues in the product.';
COMMENT ON COLUMN Product.driver IS 'This is a driver for the overall product. This driver will be able to approve nominations of bugs and specs to any series in the product, including backporting to old stable series. You want the smallest group of "overall drivers" here, because you can add specific drivers to each series individually.';

/* ProductLabel */

COMMENT ON TABLE ProductLabel IS 'The Product label table. We have not yet clearly defined the nature of product labels, so please do not refer to this table yet. If you have a need for tags or labels on Products, please contact Mark.';


-- ProductRelease

COMMENT ON TABLE ProductRelease IS 'A Product Release. This is table stores information about a specific \'upstream\' software release, like Apache 2.0.49 or Evolution 1.5.4.';
COMMENT ON COLUMN ProductRelease.version IS 'This is a text field containing the version string for this release, such as \'1.2.4\' or \'2.0.38\' or \'7.4.3\'.';
--COMMENT ON COLUMN ProductRelease.codename IS 'This is the GSV Name of this release, like \'that, and a pair of testicles\' or \'All your base-0 are belong to us\'. Many upstream projects are assigning fun names to their releases - these go in this field.';
COMMENT ON COLUMN ProductRelease.summary IS 'A summary of this ProductRelease. This should be a very brief overview of changes and highlights, just a short paragraph of text. The summary is usually displayed in bold at the top of a page for this product release, above the more detailed description or changelog.';
COMMENT ON COLUMN ProductRelease.productseries IS 'A pointer to the Product Series this release forms part of. Using a Product Series allows us to distinguish between releases on stable and development branches of a product even if they are interspersed in time.';


-- ProductSeries
COMMENT ON TABLE ProductSeries IS 'A ProductSeries is a set of product releases that are related to a specific version of the product. Typically, each major release of the product starts a new ProductSeries. These often map to a branch in the revision control system of the project, such as "2_0_STABLE". A few conventional Series names are "head" for releases of the HEAD branch, "1.0" for releases with version numbers like "1.0.0" and "1.0.1".';
COMMENT ON COLUMN ProductSeries.name IS 'The name of the ProductSeries is like a unix name, it should not contain any spaces and should start with a letter or number. Good examples are "2.0", "3.0", "head" and "development".';
COMMENT ON COLUMN ProductSeries.summary IS 'A summary of this Product Series. A good example would include the date the series was initiated and whether this is the current recommended series for people to use. The summary is usually displayed at the top of the page, in bold, just beneath the title and above the description, if there is a description field.';
COMMENT ON COLUMN ProductSeries.driver IS 'This is a person or team who can approve spes and bugs for implementation or fixing in this specific series. Note that the product drivers and project drivers can also do this for any series in the product or project, so use this only for the specific team responsible for this specific series.';
COMMENT ON COLUMN ProductSeries.importstatus IS 'A status flag which
gives the state of our efforts to import the upstream code from its revision
control system and publish that in the baz revision control system. The
allowed values are documented in dbschema.BazImportStatus.';
COMMENT ON COLUMN ProductSeries.rcstype IS 'The revision control system used
by upstream for this product series. The value is defined in
dbschema.RevisionControlSystems.  If NULL, then there should be no CVS or
SVN information attached to this productseries, otherwise the relevant
fields for CVS or SVN etc should be filled out.';
COMMENT ON COLUMN ProductSeries.cvsroot IS 'The CVS root where this
productseries hosts its code. Only used if rcstype is CVS.';
COMMENT ON COLUMN ProductSeries.cvsmodule IS 'The CVS module which contains
the upstream code for this productseries. Only used if rcstype is CVS.';
COMMENT ON COLUMN ProductSeries.cvsmodule IS 'The CVS branch that contains
the upstream code for this productseries.  Only used if rcstype is CVS.';
COMMENT ON COLUMN ProductSeries.cvstarfileurl IS 'The URL of a tarfile of
the CVS repository for this productseries. This is an optimisation of the
CVS import process - instead of hitting the server to pass us every set of
changes in history, we can sometimes arrange to be given a tarfile of the
CVS repository and then process it all locally. Once imported, we switch
back to using the CVS server for ongoing syncronization.  Only used if
rcstype is CVS.';
COMMENT ON COLUMN ProductSeries.svnrepository IS 'The URL of the SVN branch
where the upstream productseries code can be found. This single URL is the
equivalent of the cvsroot, cvsmodule and cvsbranch for CVS. Only used if
rcstype is SVN.';
COMMENT ON COLUMN ProductSeries.bkrepository IS 'The URL of the BK branch
where the upstream productseries code can be found. This single URL is the
equivalent of the cvsroot, cvsmodule and cvsbranch. Only used if rcstype is
BK.';
COMMENT ON COLUMN ProductSeries.releaseroot IS 'The URL to the directory
which holds upstream releases for this productseries. This allows us to
monitor the upstream site and detect new upstream release tarballs.';
COMMENT ON COLUMN ProductSeries.releasefileglob IS 'A fileglob that lets us
see which files in the releaseroot directory are potentially new upstream
tarball releases. For example: linux-*.*.*.gz.';
COMMENT ON COLUMN ProductSeries.releaseverstyle IS 'An enum giving the style
of this product series release version numbering system.  The options are
documented in dbschema.UpstreamReleaseVersionStyle.  Most applications use
Gnu style numbering, but there are other alternatives.';
COMMENT ON COLUMN ProductSeries.targetarchcategory IS 'The category name of
the bazaar branch to which we publish new changesets detected in the
upstream revision control system.';
COMMENT ON COLUMN ProductSeries.targetarchbranch IS 'The branch name of the
bazaar branch to which we publish new changesets detected in the upstream
revision control system.';
COMMENT ON COLUMN ProductSeries.targetarchversion IS 'The version of the
bazaar branch to which we publish new changesets detected in the upstream
revision control system.';
COMMENT ON COLUMN ProductSeries.dateprocessapproved IS 'The timestamp when
this upstream import was certified for processing. Processing means it has
passed autotesting, and is being moved towards production syncing. If the
sync goes well, it will be approved for sync and then be fully in
production.';
COMMENT ON COLUMN ProductSeries.datesyncapproved IS 'The timestamp when this
upstream import was certified for ongoing syncronisation.';
COMMENT ON COLUMN ProductSeries.dateautotested IS 'This upstream revision
control system target has passed automatic testing. It can probably be moved
towards production sync status. This date is the timestamp when it passed
the autotester. The autotester allows us to find the low hanging fruit that
is easily brought into the bazaar import system by highlighting repositories
which had no apparent difficulty in being imported.';
COMMENT ON COLUMN ProductSeries.datestarted IS 'The timestamp when we last
initiated an import test or sync of this upstream repository.';
COMMENT ON COLUMN ProductSeries.datefinished IS 'The timestamp when we last
completed an import test or sync of this upstream repository. If this is
NULL and datestarted is NOT NULL, then there is a sync in progress.';


-- Project
COMMENT ON TABLE Project IS 'Project: A DOAP Project. This table is the core of the DOAP section of the Launchpad database. It contains details of a single open source Project and is the anchor point for products, potemplates, and translationefforts.';
COMMENT ON COLUMN Project.owner IS 'The owner of the project will initially be the person who creates this Project in the system. We will encourage upstream project leaders to take on this role. The Project owner is able to edit the project.';
COMMENT ON COLUMN Project.driver IS 'This person or team has the ability to approve specs as goals for any series in any product in the project. Similarly, this person or team can approve bugs as targets for fixing in any series, or backporting of fixes to any series.';
COMMENT ON COLUMN Project.summary IS 'A brief summary of this project. This
will be displayed in bold text just above the description and below the
title. It should be a single paragraph of not more than 80 words.';
COMMENT ON COLUMN Project.description IS 'A detailed description of this
project. This should primarily be focused on the organisational aspects of
the project, such as the people involved and the structures that the project
uses to govern itself. It might refer to the primary products of the project
but the detailed descriptions of those products should be in the
Product.description field, not here. So, for example, useful information
such as the dates the project was started and the way the project
coordinates itself are suitable here.';
COMMENT ON COLUMN Project.homepageurl IS 'The home page URL of this project. Note that this could well be the home page of the main product of this project as well, if the project is too small to have a separate home page for project and product.';
COMMENT ON COLUMN Project.wikiurl IS 'This is the URL of a wiki that includes information about the project. It might be a page in a bigger wiki, or it might be the top page of a wiki devoted to this project.';
COMMENT ON COLUMN Project.lastdoap IS 'This column stores a cached copy of the last DOAP description we saw for this project. We cache the last DOAP fragment for this project because there may be some aspects of it which we are unable to represent in the database (such as multiple homepageurl\'s instead of just a single homepageurl) and storing the DOAP file allows us to re-parse it later and recover this information when our database model has been updated appropriately.';
COMMENT ON COLUMN Project.name IS 'A short lowercase name uniquely identifying the product. Use cases include being used as a key in URL traversal.';
COMMENT ON COLUMN Project.sourceforgeproject IS 'The SourceForge project name for this project. This is not unique as SourceForge doesn\'t use the same project/product structure as DOAP.';
COMMENT ON COLUMN Project.freshmeatproject IS 'The FreshMeat project name for this project. This is not unique as FreshMeat does not have the same project/product structure as DOAP';
COMMENT ON COLUMN Project.reviewed IS 'Whether or not someone at Canonical has reviewed this project.';
COMMENT ON COLUMN Project.active IS 'Whether or not this project should be considered active.';
COMMENT ON COLUMN Project.translationgroup IS 'The translation group that has permission to edit translations across all products in this project. Note that individual products may have their own translationgroup, in which case those translators will also have permission to edit translations for that product.';
COMMENT ON COLUMN Project.translationpermission IS 'The level of openness of
this project\'s translation process. The enum lists different approaches to
translation, from the very open (anybody can edit any translation in any
language) to the completely closed (only designated translators can make any
changes at all).';
COMMENT ON COLUMN Project.calendar IS 'The calendar associated with this project.';


-- ProjectRelationship
COMMENT ON TABLE ProjectRelationship IS 'Project Relationships. This table stores information about the way projects are related to one another in the open source world. The actual nature of the relationship is stored in the \'label\' field, and possible values are given by the ProjectRelationship enum in dbschema.py. Examples are AGGREGATES ("the Gnome Project AGGREGATES EOG and Evolution and Gnumeric and AbiWord") and SIMILAR ("the Evolution project is SIMILAR to the Mutt project").';
COMMENT ON COLUMN ProjectRelationship.subject IS 'The subject of the relationship. Relationships are generally unidirectional - A AGGREGATES B is not the same as B AGGREGATES A. In the example "Gnome AGGREGATES Evolution", Gnome is the subject.';
COMMENT ON COLUMN ProjectRelationship.object IS 'The object of the relationship. In the example "Gnome AGGREGATES Evolution", Evolution is the object.';
COMMENT ON COLUMN ProjectRelationship.label IS 'The nature of the relationship. This integer takes one of the values enumerated in dbschema.py ProjectRelationship';


-- POTMsgSet
COMMENT ON TABLE POTMsgSet IS 'POTMsgSet: This table is stores a collection of msgids without their translations and all kind of information associated to that set of messages that could be found in a potemplate file.';

COMMENT ON COLUMN POTMsgSet.primemsgid IS 'The id of a pomgsid that identify this message set.';
COMMENT ON COLUMN POTMsgSet."sequence" IS 'The position of this message set inside the potemplate.';
COMMENT ON COLUMN POTMsgSet.potemplate IS 'The potemplate where this message set is stored.';
COMMENT ON COLUMN POTMsgSet.commenttext IS 'The comment text that is associated to this message set.';
COMMENT ON COLUMN POTMsgSet.filereferences IS 'The list of files and their line number where this message set was extracted from.';
COMMENT ON COLUMN POTMsgSet.sourcecomment IS 'The comment that was extracted from the source code.';
COMMENT ON COLUMN POTMsgSet.flagscomment IS 'The flags associated with this set (like c-format).';

-- POTemplate
COMMENT ON TABLE POTemplate IS 'This table stores a pot file for a given product.';
COMMENT ON COLUMN POTemplate.sourcepackagename IS 'A reference to a sourcepackage name from where this POTemplate comes.';
COMMENT ON COLUMN POTemplate.distrorelease IS 'A reference to the distribution from where this POTemplate comes.';
COMMENT ON COLUMN POTemplate.sourcepackageversion IS 'The sourcepackage version string from where this potemplate was imported last time with our buildd <-> Rosetta gateway.';
COMMENT ON COLUMN POTemplate.header IS 'The header of a .pot file when we import it. Most important info from it is POT-Creation-Date and custom headers.';
COMMENT ON COLUMN POTemplate.potemplatename IS 'A reference to a POTemplateName row that tells us the name/domain for this POTemplate.';
COMMENT ON COLUMN POTemplate.productseries IS 'A reference to a ProductSeries from where this POTemplate comes.';
COMMENT ON COLUMN POTemplate.path IS 'The path to the .pot source file inside the tarball tree, including the filename.';
COMMENT ON COLUMN POTemplate.from_sourcepackagename IS 'The sourcepackagename from where the last .pot file came (only if it\'s different from POTemplate.sourcepackagename)';

-- POTemplateName
COMMENT ON TABLE POTemplateName IS 'POTemplate Name. This table stores the domains/names of a set of POTemplate rows.';
COMMENT ON COLUMN POTemplateName.name IS 'The name of the POTemplate set. It must be unique';
COMMENT ON COLUMN POTemplateName.title IS 'The title we are going to use every time that we render a view of this POTemplateName row.';
COMMENT ON COLUMN POTemplateName.description IS 'A brief text about this POTemplateName so the user could know more about it.';
COMMENT ON COLUMN POTemplateName.translationdomain IS 'The translation domain name for this POTemplateName';

-- POFile
COMMENT ON TABLE POFile IS 'This table stores a PO file for a given PO template.';
COMMENT ON COLUMN POFile.exportfile IS 'The Library file alias of an export of this PO file.';
COMMENT ON COLUMN POFile.exporttime IS 'The time at which the file referenced by exportfile was generated.';
COMMENT ON COLUMN POFile.path IS 'The path (included the filename) inside the tree from where the content was imported.';
COMMENT ON COLUMN POFile.from_sourcepackagename IS 'The sourcepackagename from where the last .po file came (only if it\'s different from POFile.potemplate.sourcepackagename)';

-- POSelection
COMMENT ON TABLE POSelection IS 'This table captures the full set
of all the translations ever submitted for a given pomsgset and pluralform.
It also indicates which of those is currently active.';
COMMENT ON COLUMN POSelection.pomsgset IS 'The messageset for
which we are recording a selection.';
COMMENT ON COLUMN POSelection.pluralform IS 'The pluralform of
this selected translation.';
COMMENT ON COLUMN POSelection.activesubmission IS 'The submission which made
this the active translation in rosetta for this pomsgset and pluralform.';
COMMENT ON COLUMN POSelection.publishedsubmission IS 'The submission in which
we noted this as the current translation published in revision control (or
in the public po files for this translation template, in the package or
tarball or branch which is considered the source of it).';

-- POSubmission
COMMENT ON TABLE POSubmission IS 'This table records the fact
that we saw, or someone submitted, a particular translation for a particular
msgset under a particular licence, at a specific time.';
COMMENT ON COLUMN POSubmission.pomsgset IS 'The message set for which the
submission or sighting was made.';
COMMENT ON COLUMN POSubmission.pluralform IS 'The plural form of the
submission which was made.';
COMMENT ON COLUMN POSubmission.potranslation IS 'The translation that was
submitted or sighted.';
COMMENT ON COLUMN POSubmission.person IS 'The person that made
the submission through the web to rosetta, or the last-translator on the
pofile that we are processing, or the person who uploaded that pofile to
rosetta. In short, our best guess as to the person who is contributing that
translation.';
COMMENT ON COLUMN POSubmission.origin IS 'The source of this
translation. This indicates whether the translation was in a pofile that we
parsed (probably one published in a package or branch or tarball), or was
submitted through the web.';
COMMENT ON COLUMN POSubmission.validationstatus IS 'Says whether or not we have validated this translation. Its value is specified by dbschema.TranslationValidationStatus, with 0 the value that says this row has not been validated yet.';

-- POMsgSet
COMMENT ON COLUMN POMsgSet.publishedfuzzy IS 'This indicates that this
POMsgSet was fuzzy when it was last imported from a published PO file. By
comparing the current fuzzy state (in the "fuzzy" field) to that, we know if
we have changed the fuzzy condition of the messageset in Rosetta.';
COMMENT ON COLUMN POMsgSet.publishedcomplete IS 'This indicates that this
POMsgSet was complete when it was last imported from a published PO file. By
"complete" we mean "has a translation for every expected plural form". We
can compare the current completeness state (in the "iscomplete" field) to
this, to know if we have changed the completeness of the messageset in
Rosetta since it was imported.';
COMMENT ON COLUMN POMsgSet.isfuzzy IS 'This indicates if the msgset is
currently fuzzy in Rosetta. The other indicator, publishedfuzzy, shows the
same status for the last published pofile we pulled in.';
COMMENT ON COLUMN POMsgSet.iscomplete IS 'This indicates if we believe that
Rosetta has an active translation for every expected plural form of this
message set.';


/* Sprint */
COMMENT ON TABLE Sprint IS 'A meeting, sprint or conference. This is a convenient way to keep track of a collection of specs that will be discussed, and the people that will be attending.';
COMMENT ON COLUMN Sprint.driver IS 'The driver (together with the registrant or owner) is responsible for deciding which topics will be accepted onto the agenda of the sprint.';
COMMENT ON COLUMN Sprint.time_zone IS 'The timezone of the sprint, stored in text format from the Olsen database names, like "US/Eastern".';


/* SprintAttendance */
COMMENT ON TABLE SprintAttendance IS 'The record that someone will be attending a particular sprint or meeting.';
COMMENT ON COLUMN SprintAttendance.time_starts IS 'The time from which the person will be available to participate in meetings at the sprint.';
COMMENT ON COLUMN SprintAttendance.time_ends IS 'The time of departure from the sprint or conference - this is the last time at which the person is available for meetings during the sprint.';


/* SprintSpecification */
COMMENT ON TABLE SprintSpecification IS 'The link between a sprint and a specification, so that we know which specs are going to be discussed at which sprint.';
COMMENT ON COLUMN SprintSpecification.status IS 'Whether or not the spec has been approved on the agenda for this sprint.';
COMMENT ON COLUMN SprintSpecification.whiteboard IS 'A place to store comments specifically related to this spec being on the agenda of this meeting.';
COMMENT ON COLUMN SprintSpecification.registrant IS 'The person who nominated this specification for the agenda of the sprint.';
COMMENT ON COLUMN SprintSpecification.decider IS 'The person who approved or declined this specification for the sprint agenda.';
COMMENT ON COLUMN SprintSpecification.date_decided IS 'The date this specification was approved or declined for the agenda.';


/* Ticket */
COMMENT ON TABLE Ticket IS 'A trouble ticket, or support request, for a distribution or for an application. Such tickets are created by end users who need support on a particular feature or package or product.';
COMMENT ON COLUMN Ticket.assignee IS 'The person who has been assigned to resolve this support ticket. Note that there is no requirement that every ticket be assigned somebody. Anybody can chip in to help resolve a ticket, and if they think they have done so we call them the "answerer".';
COMMENT ON COLUMN Ticket.answerer IS 'The person who last claimed to have "answered" this support ticket, giving a response that they believe should be sufficient to close the ticket. This will move the status of the ticket to "answered". Note that the only person who can actually set the status to "closed" (other than an admin) is the person who made the support request.';
COMMENT ON COLUMN Ticket.answer IS 'The TicketMessage that was accepted by the submitter as the "answer" the request.';
COMMENT ON COLUMN Ticket.product IS 'The upstream product to which this support request is related. Note that a support request MUST be linked either to a product, or to a distribution. In future, we may allow a request to be linked to both.';
COMMENT ON COLUMN Ticket.distribution IS 'The distribution for which a support request was filed. Note that a request MUST be linked either to a product or a distribution, and in future, we may allow it to be linked to both.';
COMMENT ON COLUMN Ticket.sourcepackagename IS 'An optional source package name. This only makes sense if the ticket is bound to a distribution. It then allows us to guess the correct upstream product, allowing the user to "publish this request upstream too".';
COMMENT ON COLUMN Ticket.datelastquery IS 'The date we last saw a comment from the requester (owner).';
COMMENT ON COLUMN Ticket.datelastresponse IS 'The date we last saw a comment from somebody other than the requester.';
COMMENT ON COLUMN Ticket.dateaccepted IS 'The date we "confirmed" or "accepted" this support request. It is usually set to the date of the first response by someone other than the requester. This allows us to track the time between first request and first response.';
COMMENT ON COLUMN Ticket.datedue IS 'The date this ticket is "due", if such a date can be established. Usually this will be set automatically on the basis of a support contract SLA commitment.';
COMMENT ON COLUMN Ticket.dateanswered IS 'The date this ticket was last "answered", in the sense of receiving a comment from someone other than the requester that they considered sufficient to close the ticket.';
COMMENT ON COLUMN Ticket.dateclosed IS 'The date the requester marked this ticket CLOSED.';
COMMENT ON COLUMN Ticket.whiteboard IS 'A general status whiteboard. This is a scratch space to which arbitrary data can be added (there is only one constant whiteboard with no history). It is displayed at the top of the ticket. So its a useful way for projects to add their own semantics or metadata to the support tracker.';

/* TicketBug */

COMMENT ON TABLE TicketBug IS 'A link between a ticket and a bug, showing that the bug is somehow related to this support request.';

/* TicketMessage */

COMMENT ON TABLE TicketMessage IS 'A link between a support ticket and a message. This means that the message will be displayed on the ticket page.';
COMMENT ON COLUMN TicketMessage.action IS 'The action on the ticket that was done with this message. This is a value from the TicketAction enum.';
COMMENT ON COLUMN TicketMessage.newstatus IS 'The status of the ticket after this message.';

/* TicketReopening */

COMMENT ON TABLE TicketReopening IS 'A record of the times when a ticket was re-opened. In each case we store the time that it happened, the person who did it, and the person who had previously answered / rejected the ticket.';
COMMENT ON COLUMN TicketReopening.reopener IS 'The person who reopened the ticket.';
COMMENT ON COLUMN TicketReopening.answerer IS 'The person who was previously listed as the answerer of the ticket.';
COMMENT ON COLUMN TicketReopening.priorstate IS 'The state of the ticket before it was reopened. You can reopen a ticket that is ANSWERED, or CLOSED, or REJECTED.';


/* TicketSubscription */

COMMENT ON TABLE TicketSubscription IS 'A subscription of a person to a particular support request.';


/* DistroReleaseLanguage */

COMMENT ON TABLE DistroReleaseLanguage IS 'A cache of the current translation status of that language across an entire distrorelease.';
COMMENT ON COLUMN DistroReleaseLanguage.dateupdated IS 'The date these statistucs were last updated.';
COMMENT ON COLUMN DistroReleaseLanguage.currentcount IS 'As per IRosettaStats.';
COMMENT ON COLUMN DistroReleaseLanguage.updatescount IS 'As per IRosettaStats.';
COMMENT ON COLUMN DistroReleaseLanguage.rosettacount IS 'As per IRosettaStats.';
COMMENT ON COLUMN DistroReleaseLanguage.contributorcount IS 'The total number of contributors to the translation of this distrorelease into this language.';

/* Manifest */

COMMENT ON TABLE Manifest IS 'A Manifest describes the branches that go into
making up a source package or product release. This allows us to describe
the source package or product release in a way that HCT can pull down the
sources directly from The Bazaar and allow people to branch and edit
immediately. Note that a Manifest does not have an owner, please ensure that
ANYTHING that points TO a manifest, such as ProductRelease or
SourcePackageRelease, has an owner, so that we do not end up with orphaned
manifests.';

/* Calendar */

COMMENT ON TABLE Calendar IS 'A Calendar attached to some other Launchpad object (currently People, Projects or Products)';
COMMENT ON COLUMN Calendar.title IS 'The title of the Calendar';
COMMENT ON COLUMN Calendar.revision IS 'An monotonically increasing counter indicating a particular version of the calendar';


-- CalendarSubscription
COMMENT ON TABLE CalendarSubscription IS 'A subscription relationship between two calendars';
COMMENT ON COLUMN CalendarSubscription.subject IS 'The subject of the subscription relationship';
COMMENT ON COLUMN CalendarSubscription.object IS 'The object of the subscription relationship';
COMMENT ON COLUMN CalendarSubscription.colour IS 'The colour used to display events from calendar \'object\' when in the context of calendar \'subject\'';

COMMENT ON TABLE CalendarEvent IS 'Events belonging to calendars';
COMMENT ON COLUMN CalendarEvent.uid IS 'A globally unique identifier for the event.  This identifier should be preserved through when importing events from a desktop calendar application';
COMMENT ON COLUMN CalendarEvent.calendar IS 'The calendar this event belongs to';
COMMENT ON COLUMN CalendarEvent.dtstart IS 'The start time for the event in UTC';
COMMENT ON COLUMN CalendarEvent.duration IS 'The duration of the event';
COMMENT ON COLUMN CalendarEvent.title IS 'A one line description of the event';
COMMENT ON COLUMN CalendarEvent.description IS 'A multiline description of the event';
COMMENT ON COLUMN CalendarEvent.location IS 'A location associated with the event';

COMMENT ON COLUMN SourcePackageName.name IS
    'A lowercase name identifying one or more sourcepackages';
COMMENT ON COLUMN BinaryPackageName.name IS
    'A lowercase name identifying one or more binarypackages';
COMMENT ON COLUMN BinaryPackageRelease.architecturespecific IS 'This field indicates whether or not a binarypackage is architecture-specific. If it is not specific to any given architecture then it can automatically be included in all the distroarchreleases which pertain.';


/* Distribution */

COMMENT ON COLUMN Distribution.lucilleconfig IS 'Configuration
information which lucille will use when processing uploads and
generating archives for this distribution';
COMMENT ON COLUMN Distribution.members IS 'Person or team with upload and commit priviledges relating to this distribution. Other rights may be assigned to this role in the future.';
COMMENT ON COLUMN Distribution.mirror_admin IS 'Person or team with privileges to mark a mirror as official.';
COMMENT ON COLUMN Distribution.driver IS 'The team or person responsible for approving goals for each release in the distribution. This should usually be a very small team because the Distribution driver can approve items for backporting to past releases as well as the current release under development. Each distrorelease has its own driver too, so you can have the small superset in the Distribution driver, and then specific teams per distrorelease for backporting, for example, or for the current release management team on the current development focus release.';
COMMENT ON COLUMN Distribution.translationgroup IS 'The translation group that is responsible for all translation work in this distribution.';
COMMENT ON COLUMN Distribution.translationpermission IS 'The level of openness of this distribution\'s translation process. The enum lists different approaches to translation, from the very open (anybody can edit any translation in any language) to the completely closed (only designated translators can make any changes at all).';
COMMENT ON COLUMN Distribution.bugcontact IS 'Person who will be automatically subscribed to every bug targeted to this distribution.';
COMMENT ON COLUMN Distribution.security_contact IS 'The person or team who handles security-related issues in the distribution.';
COMMENT ON COLUMN Distribution.official_rosetta IS 'Whether or not this distribution uses Rosetta for its official translation team and coordination.';
COMMENT ON COLUMN Distribution.official_malone IS 'Whether or not this distribution uses Malone for an official bug tracker.';
COMMENT ON COLUMN Distribution.translation_focus IS 'The DistroRelease that should get the translation effort focus.';

/* DistroRelease */

COMMENT ON COLUMN DistroRelease.lucilleconfig IS 'Configuration
information which lucille will use when processing uploads and
generating archives for this distro release';
COMMENT ON COLUMN DistroRelease.summary IS 'A brief summary of the distro release. This will be displayed in bold at the top of the distrorelease page, above the distrorelease description. It should include any high points that are particularly important to draw to the attention of users.';
COMMENT ON COLUMN DistroRelease.description IS 'An extensive list of the features in this release of the distribution. This will be displayed on the main distro release page, below the summary.';
COMMENT ON COLUMN DistroRelease.datelastlangpack IS
'The date we last generated a base language pack for this release. Language
update packs for this release will only include translations added after that
date.';
COMMENT ON COLUMN DistroRelease.messagecount IS 'This is a cached value and may be a few hours out of sync with reality. It should, however, be in sync with the values in DistroReleaseLanguage, and should never be updated separately. The total number of translation messages in this distro release, as per IRosettaStats.';
COMMENT ON COLUMN DistroRelease.nominatedarchindep IS 'This is the DistroArchRelease nominated to build architecture independent packages within this DistroRelase, it is mandatory for buildable distroreleases, i.e., Auto Build System will avoid to create build jobs for a DistroRelease with no nominatedarchindep, but the database model allow us to do it (for non-buildable DistroReleases). See further info in NominatedArchIndep specification.';
COMMENT ON COLUMN DistroRelease.binarycount IS 'A cache of the number of distinct binary package names published in this distro release.';
COMMENT ON COLUMN DistroRelease.sourcecount IS 'A cache of the number of distinct source package names published in this distro release.';

-- DistroReleaseQueue
COMMENT ON TABLE DistroReleaseQueue IS 'An upload queue item. This table stores information pertaining to in-progress package uploads to a given DistroRelease.';

COMMENT ON COLUMN DistroReleaseQueue.status IS 'This is an integer field containing the current queue status of the queue item. Possible values are given by the DistroQueueStatus class in dbschema.py';

COMMENT ON COLUMN DistroReleaseQueue.distrorelease IS 'This integer field refers to the DistroRelease to which this upload is targeted';

COMMENT ON COLUMN DistroReleaseQueue.pocket IS 'This is the pocket the upload is targeted at.';

COMMENT ON COLUMN DistroReleaseQueue.changesfile IS 'The changes file associated with this upload.';

-- DistroReleaseQueueSource
COMMENT ON TABLE DistroReleaseQueueSource IS 'An upload queue source package. This table stores information pertaining to the source files in an in-progress package upload.';

COMMENT ON COLUMN DistroReleaseQueueSource.distroreleasequeue IS 'This integer field refers to the DistroQueue row that this source belongs to.';

COMMENT ON COLUMN DistroReleaseQueueSource.sourcepackagerelease IS 'This integer field refers to the SourcePackageRelease record related to this upload.';

-- DistroReleaseQueueBuild
COMMENT ON TABLE DistroReleaseQueueBuild IS 'An upload queue binary build. This table stores information pertaining to the builds in an in-progress package upload.';

COMMENT ON COLUMN DistroReleaseQueueBuild.distroreleasequeue IS 'This integer field refers to the DistroQueue row that this source belongs to.';

COMMENT ON COLUMN DistroReleaseQueueBuild.build IS 'This integer field refers to the Build record related to this upload.';

-- DistroReleaseQueueCustom
COMMENT ON TABLE DIstroReleaseQueueCustom IS 'An upload queue custom format upload. This table stores information pertaining to the custom upload formats in an in-progress package upload.';

COMMENT ON COLUMN DistroReleaseQueueCustom.distroreleasequeue IS 'The queue item this refers to.';

COMMENT ON COLUMN DistroReleaseQueueCustom.customformat IS 'The format of this particular custom uploaded file.';

COMMENT ON COLUMN DistroReleaseQueueCustom.libraryfilealias IS 'The actual file as a librarian alias.';

-- SourcePackageName
COMMENT ON COLUMN SourcePackageName.name IS
    'A lowercase name identifying one or more sourcepackages';
COMMENT ON COLUMN BinaryPackageName.name IS
    'A lowercase name identifying one or more binarypackages';

COMMENT ON COLUMN BinaryPackageRelease.architecturespecific IS 'This field indicates whether or not a binarypackage is architecture-specific. If it is not specific to any given architecture then it can automatically be included in all the distroarchreleases which pertain.';


-- SourcePackageRelease
COMMENT ON COLUMN SourcePackageRelease.section IS 'This integer field references the Section which the source package claims to be in';

/* SourcePackagePublishing and BinaryPackagePublishing */

COMMENT ON COLUMN SourcePackagePublishing.datepublished IS 'This column contains the timestamp at which point the SourcePackageRelease progressed from a pending publication to being published in the respective DistroRelease';

COMMENT ON COLUMN SourcePackagePublishing.scheduleddeletiondate IS 'This column is only used when the the publishing record is PendingRemoval. It indicates the earliest time that this record can be removed. When a publishing record is removed, the files it embodies are made candidates for removal from the pool.';

COMMENT ON COLUMN SourcePackagePublishing.datepublished IS 'This column contains the timestamp at which point the Build progressed from a pending publication to being published in the respective DistroRelease';

COMMENT ON COLUMN SourcePackagePublishing.scheduleddeletiondate IS 'This column is only used when the the publishing record is PendingRemoval. It indicates the earliest time that this record can be removed. When a publishing record is removed, the files it embodies are made candidates for removal from the pool.';

COMMENT ON COLUMN SourcePackagePublishing.status IS 'This column contains the status of the publishing record. The valid states are described in dbschema.py in PackagePublishingStatus. Example states are "Pending" and "Published"';

COMMENT ON COLUMN BinaryPackagePublishing.status IS 'This column contains the status of the publishing record. The valid states are described in dbschema.py in PackagePublishingStatus. Example states are "Pending" and "Published"';

-- SecureBinaryPackagePublishingHistory
COMMENT ON TABLE SecureBinaryPackagePublishingHistory IS 'PackagePublishingHistory: The history of a BinaryPackagePublishing record. This table represents the lifetime of a publishing record from inception to deletion. Records are never removed from here and in time the publishing table may become a view onto this table. A column being NULL indicates there''s no data for that state transition. E.g. a package which is removed without being superseded won''t have datesuperseded or supersededby filled in.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.binarypackagerelease IS 'The binarypackage being published.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.distroarchrelease IS 'The distroarchrelease into which the binarypackage is being published.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.status IS 'The current status of the publishing.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.component IS 'The component into which the publishing takes place.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.section IS 'The section into which the publishing takes place.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.priority IS 'The priority at which the publishing takes place.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.datecreated IS 'The date/time on which the publishing record was created.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.datepublished IS 'The date/time on which the source was actually published into an archive.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.datesuperseded IS 'The date/time on which the source was superseded by a new source.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.supersededby IS 'The build which superseded this package. This seems odd but it is important because a new build may not actually build a given binarypackage and we need to supersede it appropriately';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.datemadepending IS 'The date/time on which this publishing record was made to be pending removal from the archive.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.scheduleddeletiondate IS 'The date/time at which the package is/was scheduled to be deleted.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.dateremoved IS 'The date/time at which the package was actually deleted.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.pocket IS 'The pocket into which this record is published. The RELEASE pocket (zero) provides behaviour as normal. Other pockets may append things to the distrorelease name such as the UPDATES pocket (-updates) or the SECURITY pocket (-security).';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.embargo IS 'The publishing record is embargoed from publication if this is set to TRUE. When TRUE, this column prevents the publication record from even showing up in the publishing tables.';
COMMENT ON COLUMN SecureBinaryPackagePublishingHistory.embargolifted IS 'The date and time when we lifted the embargo on this publishing record. I.E. when embargo was set to FALSE having previously been set to TRUE.';
COMMENT ON VIEW BinaryPackagePublishingHistory IS 'View on SecureBinaryPackagePublishingHistory that restricts access to embargoed entries';

COMMENT ON VIEW PublishedPackageView IS
    'A very large view that brings together all the information about
    packages that are currently being published within a distribution. This
    view was designed for the page which shows packages published in the
    distribution, but may be more widely used.';

-- ProcessorFamily

COMMENT ON TABLE ProcessorFamily IS 'An architecture, that might consist of several actual processors. Different distributions call these architectures different things, so we have an "architecturetag" in DistroArchRelease that might be different to the architecture\'s name.';
COMMENT ON COLUMN ProcessorFamily.name IS 'The name of the architecture. This is a short unix-style name such as i386 or amd64';
COMMENT ON COLUMN ProcessorFamily.title IS 'A title for the architecture. For example "Intel i386 Compatible".';
COMMENT ON COLUMN ProcessorFamily.description IS 'A description for this processor family. It might include any gotchas such as the fact that i386 does not necessarily mean that code would run on a 386... Ubuntu for example requires a 486.';

-- Processor

COMMENT ON TABLE Processor IS 'A single processor for which code might be compiled. For example, i386, P2, P3, P4, Itanium1, Itanium2... each processor belongs to a ProcessorFamily, and it might be that a package is compiled several times for a given Family, with different optimisation settings for each processor.';
COMMENT ON COLUMN Processor.name IS 'The name of this processor, for example, i386, Pentium, P2, P3, P4, Itanium, Itanium2, K7, Athlon, Opteron... it should be short and unique.';
COMMENT ON COLUMN Processor.family IS 'The ProcessorFamily for this Processor.';

-- DistroArchRelease

COMMENT ON COLUMN DistroArchRelease.processorfamily IS 'A link to the ProcessorFamily table, giving the architecture of this DistroArchRelease.';
COMMENT ON COLUMN DistroArchRelease.architecturetag IS 'The name of this architecture in the context of this specific distro release. For example, some distributions might label amd64 as amd64, others might call is x86_64. This information is used, for example, in determining the names of the actual package files... such as the "amd64" part of "apache2_2.0.56-1_amd64.deb"';
COMMENT ON COLUMN DistroArchRelease.official IS 'Whether or not this architecture or "port" is an official release. If it is not official then you may not be able to install it or get all the packages for it.';
COMMENT ON COLUMN DistroArchRelease.package_count IS 'A cache of the number of binary packages published in this distro arch release. The count only includes packages published in the release pocket.';

-- LauncpadDatabaseRevision
COMMENT ON TABLE LaunchpadDatabaseRevision IS 'This table has a single row which specifies the most recently applied patch number.';
COMMENT ON COLUMN LaunchpadDatabaseRevision.major IS 'Major number. This is incremented every update to production.';
COMMENT ON COLUMN LaunchpadDatabaseRevision.minor IS 'Minor number. Patches made during development each increment the minor number.';
COMMENT ON COLUMN LaunchpadDatabaseRevision.patch IS 'The patch number will hopefully always be ''0'', as it exists to support emergency patches made to the production server. eg. If production is running ''4.0.0'' and needs to have a patch applied ASAP, we would create a ''4.0.1'' patch and roll it out. We then may need to refactor all the existing ''4.x.0'' patches.';

-- Karma
COMMENT ON TABLE Karma IS 'Used to quantify all the ''operations'' a user performs inside the system, which maybe reporting and fixing bugs, uploading packages, end-user support, wiki editting, etc.';
COMMENT ON COLUMN Karma.action IS 'A foreign key to the KarmaAction table.';
COMMENT ON COLUMN Karma.datecreated IS 'A timestamp for the assignment of this Karma.';
COMMENT ON COLUMN Karma.Person IS 'The Person for wich this Karma was assigned.';
COMMENT ON COLUMN Karma.product IS 'The Product on which a person performed an action that resulted on this karma.';
COMMENT ON COLUMN Karma.distribution IS 'The Distribution on which a person performed an action that resulted on this karma.';
COMMENT ON COLUMN Karma.sourcepackagename IS 'The SourcePackageName on which a person performed an action that resulted on this karma.';

-- KarmaAction
COMMENT ON TABLE KarmaAction IS 'Stores all the actions that would give karma to the user which performed it.';
COMMENT ON COLUMN KarmaAction.name IS 'The unique name of this action.';
COMMENT ON COLUMN KarmaAction.category IS 'A dbschema value used to group actions together.';
COMMENT ON COLUMN KarmaAction.points IS 'The number of points this action is worth of.';

-- KarmaCache
COMMENT ON TABLE KarmaCache IS 'Stores a cached value of a person\'s karma points, grouped by the action category and the context where that action was performed.';
COMMENT ON COLUMN KarmaCache.Person IS 'The person which performed the actions of this category, and thus got the karma.';
COMMENT ON COLUMN KarmaCache.Category IS 'The category of the actions.';
COMMENT ON COLUMN KarmaCache.KarmaValue IS 'The karma points of all actions of this category performed by this person on this context (product/distribution).';
COMMENT ON COLUMN Karma.product IS 'The Product on which a person performed an action that resulted on this karma.';
COMMENT ON COLUMN Karma.distribution IS 'The Distribution on which a person performed an action that resulted on this karma.';
COMMENT ON COLUMN Karma.sourcepackagename IS 'The SourcePackageName on which a person performed an action that resulted on this karma.';

-- KarmaPersonCategoryCacheView
COMMENT ON VIEW KarmaPersonCategoryCacheView IS 'A View to store a cached value of a person\'s karma points, grouped by the action category.';
COMMENT ON COLUMN KarmaPersonCategoryCacheView.id IS 'The id in this view is the smallest id of all KarmaCache entries for a given person and category. We need to do this because SQLObject requires an id column and we use a GROUP BY when creating the view.';
COMMENT ON COLUMN KarmaPersonCategoryCacheView.Person IS 'The person which performed the actions of this category, and thus got the karma.';
COMMENT ON COLUMN KarmaPersonCategoryCacheView.Category IS 'The category of the actions.';
COMMENT ON COLUMN KarmaPersonCategoryCacheView.KarmaValue IS 'The karma points of all actions of this category performed by this person.';

-- Person
COMMENT ON TABLE Person IS 'Central user and group storage. A row represents a person if teamowner is NULL, and represents a team (group) if teamowner is set.';
COMMENT ON COLUMN Person.displayname IS 'Person or group''s name as it should be rendered to screen';
COMMENT ON COLUMN Person.password IS 'SSHA digest encrypted password.';
COMMENT ON COLUMN Person.teamowner IS 'id of the team owner. Team owners will have authority to add or remove people from the team.';
COMMENT ON COLUMN Person.teamdescription IS 'Informative description of the team. Format and restrictions are as yet undefined.';
COMMENT ON COLUMN Person.name IS 'Short mneumonic name uniquely identifying this person or team. Useful for url traversal or in places where we need to unambiguously refer to a person or team (as displayname is not unique).';
COMMENT ON COLUMN Person.language IS 'Preferred language for this person (unset for teams). UI should be displayed in this language wherever possible.';
COMMENT ON COLUMN Person.calendar IS 'The calendar associated with this person.';
COMMENT ON COLUMN Person.timezone IS 'The name of the time zone this person prefers (if unset, UTC is used).  UI should display dates and times in this time zone wherever possible.';
COMMENT ON COLUMN Person.homepage_content IS 'A home page for this person in the Launchpad. In short, this is like a personal wiki page. The person will get to edit their own page, and it will be published on /people/foo/. Note that this is in text format, and will migrate to being in Moin format as a sort of mini-wiki-homepage.';
COMMENT ON COLUMN Person.emblem IS 'The library file alias to a small image (16x16 max, it\'s a tiny little thing) to be used as an emblem or icon whenever we are referring to that person.';
COMMENT ON COLUMN Person.hackergotchi IS 'The library file alias of a hackergotchi image to display as the "face" of a person, on their home page.';

COMMENT ON TABLE ValidPersonOrTeamCache IS 'A materialized view listing the Person.ids of all valid people and teams.';

-- PersonLanguage
COMMENT ON TABLE PersonLanguage IS 'PersonLanguage: This table stores the preferred languages that a Person has, it''s used in Rosetta to select the languages that should be showed to be translated.';
COMMENT ON COLUMN PersonLanguage.person IS 'This field is a reference to a Person object that has this preference.';
COMMENT ON COLUMN PersonLanguage.language IS 'This field is a reference to a Language object that says that the Person associated to this row knows how to translate/understand this language.';

-- Bounty
COMMENT ON TABLE Bounty IS 'A set of bounties for work to be done by the open source community. These bounties will initially be offered only by Canonical, but later we will create the ability for people to offer the bounties themselves, using us as a clearing house.';
COMMENT ON COLUMN Bounty.usdvalue IS 'This is the ESTIMATED value in US Dollars of the bounty. We say "estimated" because the bounty might one day be offered in one of several currencies, or people might contribute different amounts in different currencies to each bounty. This field will reflect an estimate based on recent currency exchange rates of the value of this bounty in USD.';
COMMENT ON COLUMN Bounty.difficulty IS 'An estimate of the difficulty of the bounty, as a dbschema.BountyDifficulty.';
COMMENT ON COLUMN Bounty.bountystatus IS 'The current status of this bounty
- an indicator of whether or not it is open, closed, or withdrawn.';
COMMENT ON COLUMN Bounty.reviewer IS 'The person who will review this bounty regularly for progress. The reviewer is the person who is responsible for establishing when the bounty is complete.';
COMMENT ON COLUMN Bounty.owner IS 'The person who created the bounty. The owner can update the specification of the bounty, and appoints the reviewer.';

COMMENT ON TABLE BountySubscription IS 'This table records whether or not someone it interested in a bounty. Subscribers will show up on the page with the bounty details.';
COMMENT ON COLUMN BountySubscription.bounty IS 'The bounty to which the person is subscribed.';
COMMENT ON COLUMN BountySubscription.person IS 'The person being subscribed to this bounty.';

COMMENT ON TABLE ProductBounty IS 'This table records a simple link between a bounty and a product. This bounty will be listed on the product web page, and the product will be mentioned on the bounty web page.';

COMMENT ON TABLE DistributionBounty IS 'This table records a simple link between a bounty and a distribution. This bounty will be listed on the distribution web page, and the distribution will be mentioned on the bounty web page.';

COMMENT ON TABLE ProjectBounty IS 'This table records a simple link between a bounty and a project. This bounty will be listed on the project web page, and the project will be mentioned on the bounty web page.';

-- Messaging subsytem
COMMENT ON TABLE BugMessage IS 'This table maps a message to a bug. In other words, it shows that a particular message is associated with a particular bug.';
COMMENT ON TABLE Message IS 'This table stores a single RFC822-style message. Messages can be threaded (using the parent field). These messages can then be referenced from elsewhere in the system, such as the BugMessage table, integrating messageboard facilities with the rest of The Launchpad.';
COMMENT ON COLUMN Message.parent IS 'A "parent message". This allows for some level of threading in Messages.';
COMMENT ON COLUMN Message.subject IS 'The title text of the message, or the subject if it was an email.';
COMMENT ON COLUMN Message.distribution IS 'The distribution in which this message originated, if we know it.';
COMMENT ON COLUMN Message.raw IS 'The original unadulterated message if it arrived via email. This is required to provide access to the original, undecoded message.';

COMMENT ON TABLE MessageChunk IS 'This table stores a single chunk of a possibly multipart message. There will be at least one row in this table for each message. text/* parts are stored in the content column. All other parts are stored in the Librarian and referenced via the blob column. If both content and blob are NULL, then this chunk has been removed (eg. offensive, legal reasons, virus etc.)';
COMMENT ON COLUMN MessageChunk.content IS 'Text content for this chunk of the message. This content is full text searchable.';
COMMENT ON COLUMN MessageChunk.blob IS 'Binary content for this chunk of the message.';
COMMENT ON COLUMN MessageChunk.sequence IS 'Order of a particular chunk. Chunks are orders in ascending order starting from 1.';

-- Comments on Lucille views
COMMENT ON VIEW SourcePackageFilePublishing IS 'This view is used mostly by Lucille while performing publishing and unpublishing operations. It lists all the files associated with a sourcepackagerelease and collates all the textual representations needed for publishing components etc to allow rapid queries from SQLObject.';
COMMENT ON VIEW BinaryPackageFilePublishing IS 'This view is used mostly by Lucille while performing publishing and unpublishing operations. It lists all the files associated with a binarypackage and collates all the textual representations needed for publishing components etc to allow rapid queries from SQLObject.';
COMMENT ON VIEW SourcePackagePublishingView IS 'This view is used mostly by Lucille while performing publishing¸ unpublishing, domination, superceding and other such operations. It provides an ID equal to the underlying SourcePackagePublishing record to permit as direct a change to publishing details as is possible. The view also collates useful textual data to permit override generation etc.';
COMMENT ON VIEW BinaryPackagePublishingView IS 'This view is used mostly by Lucille while performing publishing¸ unpublishing, domination, superceding and other such operations. It provides an ID equal to the underlying BinaryPackagePublishing record to permit as direct a change to publishing details as is possible. The view also collates useful textual data to permit override generation etc.';

-- SourcePackageRelease

COMMENT ON TABLE SourcePackageRelease IS 'SourcePackageRelease: A source
package release. This table represents a specific release of a source
package. Source package releases may be published into a distrorelease, or
even multiple distroreleases.';
COMMENT ON COLUMN SourcePackageRelease.creator IS 'The creator of this
sourcepackagerelease. This is the person referred to in the top entry in the
package changelog in debian terms. Note that a source package maintainer in
Ubuntu might be person A, but a particular release of that source package
might in fact have been created by a different person B. The maintainer
would be recorded in the Maintainership table, while the creator of THIS
release would be recorded in the SourcePackageRelease.creator field.';
COMMENT ON COLUMN SourcePackageRelease.version IS 'The version string for
this source package release. E.g. "1.0-2" or "1.4-5ubuntu9.1". Note that, in
ubuntu-style and redhat-style distributions, the version+sourcepackagename
is unique, even across distroreleases. In other words, you cannot have a
foo-1.2-1 package in Hoary that is different from foo-1.2-1 in Warty.';
COMMENT ON COLUMN SourcePackageRelease.dateuploaded IS 'The date/time that
this sourcepackagerelease was first uploaded to the Launchpad.';
COMMENT ON COLUMN SourcePackageRelease.urgency IS 'The urgency of the
upload. This is generally used to prioritise buildd activity but may also be
used for "testing" systems or security work in the future. The "urgency" is
set by the uploader, in the DSC file.';
COMMENT ON COLUMN SourcePackageRelease.dscsigningkey IS 'The GPG key used to
sign the DSC. This is not necessarily the maintainer\'s key, or the
creator\'s key. For example, it\'s possible to produce a package, then ask a
sponsor to upload it.';
COMMENT ON COLUMN SourcePackageRelease.component IS 'The component in which
this sourcepackagerelease is intended (by the uploader) to reside. E.g.
main, universe, restricted. Note that the distribution managers will often
override this data and publish the package in an entirely different
component.';
COMMENT ON COLUMN SourcePackageRelease.changelog IS 'The changelog of this
source package release.';
COMMENT ON COLUMN SourcePackageRelease.builddepends IS 'The build
dependencies for this source package release.';
COMMENT ON COLUMN SourcePackageRelease.builddependsindep IS 'The
architecture-independant build dependancies for this source package release.';
COMMENT ON COLUMN SourcePackageRelease.architecturehintlist IS 'The
architectures which this source package release believes it should be built.
This is used as a hint to the build management system when deciding what
builds are still needed.';
COMMENT ON COLUMN SourcePackageRelease.format IS 'The format of this
sourcepackage release, e.g. DPKG, RPM, EBUILD, etc. This is an enum, and the
values are listed in dbschema.SourcePackageFormat';
COMMENT ON COLUMN SourcePackageRelease.dsc IS 'The "Debian Source Control"
file for the sourcepackagerelease, from its upload into Ubuntu for the
first time.';
COMMENT ON COLUMN SourcePackageRelease.uploaddistrorelease IS 'The
distrorelease into which this source package release was uploaded into
Launchpad / Ubuntu for the first time. In general, this will be the
development Ubuntu release into which this package was uploaded. For a
package which was unchanged between warty and hoary, this would show Warty.
For a package which was uploaded into Hoary, this would show Hoary.';



-- SourcePackageName

COMMENT ON TABLE SourcePackageName IS 'SourcePackageName: A soyuz source package name.';

-- Specification
COMMENT ON TABLE Specification IS 'A feature specification. At the moment we do not store the actual specification, we store a URL for the spec, which is managed in a wiki somewhere else. We store the overall state of the spec, as well as queueing information about who needs to review the spec, and why.';
COMMENT ON COLUMN Specification.assignee IS 'The person who has been assigned to implement this specification.';
COMMENT ON COLUMN Specification.drafter IS 'The person who has been asked to draft this specification. They are responsible for getting the spec to "approved" state.';
COMMENT ON COLUMN Specification.approver IS 'The person who is responsible for approving the specification in due course, and who will probably be required to review the code itself when it is being implemented.';
COMMENT ON COLUMN Specification.product IS 'The product for which this is a feature specification. The specification must be connected either to a product, or to a distribution.';
COMMENT ON COLUMN Specification.distribution IS 'The distribution for which this is a feature specification. The specification must be connected either to a product, or to a distribution.';
COMMENT ON COLUMN Specification.distrorelease IS 'If this is not NULL, then it means that the release managers have targeted this feature to be released in the given distrorelease. It is not necessary to target a distrorelease, but this is a useful way of know which specifications are, for example, BreezyGoals.';
COMMENT ON COLUMN Specification.productseries IS 'This is an indicator that the specification is planned, or targeted, for implementation in a given product series. It is not necessary to target a spec to a series, but it is a useful way of showing which specs are planned to implement for a given series.';
COMMENT ON COLUMN Specification.milestone IS 'This is an indicator that the feature defined in this specification is expected to be delivered for a given milestone. Note that milestones are not necessarily releases, they are a way of identifying a point in time and grouping bugs and features around that.';
COMMENT ON COLUMN Specification.informational IS 'An indicator as to whether or not the spec is purely informational, or is actually supposed to be implemented. High level overview specs, for example, are often marked "informational" and will be considered implemented once the spec is approved.';
COMMENT ON COLUMN Specification.status IS 'An enum called SpecificationStatus that shows what the current status (new, draft, implemented etc) the spec is currently in.';
COMMENT ON COLUMN Specification.priority IS 'An enum that gives the implementation priority (low, medium, high, emergency) of the feature defined in this specification.';
COMMENT ON COLUMN Specification.specurl IS 'The URL where the specification itself can be found. This is usually a wiki page somewhere.';
COMMENT ON COLUMN Specification.whiteboard IS 'As long as the specification is somewhere else (i.e. not in Launchpad) it will be useful to have a place to hold some arbitrary message or status flags that have meaning to the project, not Launchpad. This whiteboard is just the place for it.';
COMMENT ON COLUMN Specification.superseded_by IS 'The specification which replaced this specification.';
COMMENT ON COLUMN Specification.delivery IS 'The implementation status of this
specification. This field is used to track the actual delivery of the feature
(implementing the spec), as opposed to the definition of expected behaviour
(writing the spec).';
COMMENT ON COLUMN Specification.goalstatus IS 'Whether or not the drivers for the goal product series or distro release have accepted this specification as a goal.';
COMMENT ON COLUMN Specification.goal_proposer IS 'The person who proposed this spec as a goal for the productseries or distrorelease.';
COMMENT ON COLUMN Specification.date_goal_proposed IS 'The date the spec was proposed as a goal.';
COMMENT ON COLUMN Specification.goal_decider IS 'The person who approved or declined this goal.';
COMMENT ON COLUMN Specification.date_goal_decided IS 'The date this goal was accepted or declined.';
COMMENT ON COLUMN Specification.completer IS 'The person who changed the state of the spec in such a way that it was determined to be completed.';
COMMENT ON COLUMN Specification.date_completed IS 'The date this specification was completed or marked obsolete. This lets us chart the progress of a project (or a release) over time in terms of features implemented.';
COMMENT ON CONSTRAINT specification_completion_recorded_chk ON Specification IS 'A constraint to ensure that we have recorded the date of completion if the specification is in fact considered completed. The SQL behind the completion test is repeated at a code level in database/specification.py: as Specification.completeness, please ensure that the constraint is kept in sync with the code.';
COMMENT ON CONSTRAINT specification_completion_fully_recorded_chk ON Specification IS 'A constraint that ensures, where we have a date_completed, that we also have a completer. This means that the resolution was fully recorded.';

-- SpecificationFeedback
COMMENT ON TABLE SpecificationFeedback IS 'A table representing a review request of a specification, from one user to another, with an optional message.';
COMMENT ON COLUMN SpecificationFeedback.reviewer IS 'The person who has been asked to do the review.';
COMMENT ON COLUMN SpecificationFeedback.requester IS 'The person who made the request.';
COMMENT ON COLUMN SpecificationFeedback.queuemsg IS 'An optional text message for the reviewer, from the requester.';

-- SpecificationBug
COMMENT ON TABLE SpecificationBug IS 'A table linking a specification and a bug. This is used to provide for easy navigation from bugs to related specs, and vice versa.';

-- SpecificationSubscription
COMMENT ON TABLE SpecificationSubscription IS 'A table capturing a subscription of a person to a specification.';
COMMENT ON COLUMN SpecificationSubscription.essential IS 'A field that indicates whether or not this person is essential to discussions on the planned feature. This is used by the meeting scheduler to ensure that all the essential people are at any automatically scheduled BOFs discussing that spec.';

-- SpecificationDependency
COMMENT ON TABLE SpecificationDependency IS 'A table that stores information about which specification needs to be implemented before another specification can be implemented. We can create a chain of dependencies, and use that information for scheduling and prioritisation of work.';
COMMENT ON COLUMN SpecificationDependency.specification IS 'The spec for which we are creating a dependency.';
COMMENT ON COLUMN SpecificationDependency.dependency IS 'The spec on which it is dependant.';

-- BinaryPackageRelease

COMMENT ON TABLE BinaryPackageRelease IS 'BinaryPackageRelease: A soyuz binary package representation. This table stores the records for each binary package uploaded into the system. Each sourcepackagerelease may build various binarypackages on various architectures.';
COMMENT ON COLUMN BinaryPackageRelease.binarypackagename IS 'A reference to the name of the binary package';
COMMENT ON COLUMN BinaryPackageRelease.version IS 'The version of the binary package. E.g. "1.0-2"';
COMMENT ON COLUMN BinaryPackageRelease.summary IS 'A summary of the binary package. Commonly used on listings of binary packages';
COMMENT ON COLUMN BinaryPackageRelease.description IS 'A longer more detailed description of the binary package';
COMMENT ON COLUMN BinaryPackageRelease.build IS 'The build in which this binarypackage was produced';
COMMENT ON COLUMN BinaryPackageRelease.binpackageformat IS 'The binarypackage format. E.g. RPM, DEB etc';
COMMENT ON COLUMN BinaryPackageRelease.component IS 'The archive component that this binarypackage is in. E.g. main, universe etc';
COMMENT ON COLUMN BinaryPackageRelease.section IS 'The archive section that this binarypackage is in. E.g. devel, libdevel, editors';
COMMENT ON COLUMN BinaryPackageRelease.priority IS 'The priority that this package has. E.g. Base, Standard, Extra, Optional';
COMMENT ON COLUMN BinaryPackageRelease.shlibdeps IS 'The shared library dependencies of this binary package';
COMMENT ON COLUMN BinaryPackageRelease.depends IS 'The list of packages this binarypackage depends on';
COMMENT ON COLUMN BinaryPackageRelease.recommends IS 'The list of packages this binarypackage recommends. Recommended packages often enhance the behaviour of a package.';
COMMENT ON COLUMN BinaryPackageRelease.suggests IS 'The list of packages this binarypackage suggests.';
COMMENT ON COLUMN BinaryPackageRelease.conflicts IS 'The list of packages this binarypackage conflicts with.';
COMMENT ON COLUMN BinaryPackageRelease.replaces IS 'The list of packages this binarypackage replaces files in. Often this is used to provide an upgrade path between two binarypackages of different names';
COMMENT ON COLUMN BinaryPackageRelease.provides IS 'The list of virtual packages (or real packages under some circumstances) which this binarypackage provides.';
COMMENT ON COLUMN BinaryPackageRelease.essential IS 'Whether or not this binarypackage is essential to the smooth operation of a base system';
COMMENT ON COLUMN BinaryPackageRelease.installedsize IS 'What the installed size of the binarypackage is. This is represented as a number of kilobytes of storage.';
COMMENT ON COLUMN BinaryPackageRelease.copyright IS 'The copyright associated with this binarypackage. Often in the case of debian packages this is found in /usr/share/doc/<binarypackagename>/copyright';
COMMENT ON COLUMN BinaryPackageRelease.licence IS 'The licence that this binarypackage is under.';


-- BinaryPackageFile

COMMENT ON TABLE BinaryPackageFile IS 'BinaryPackageFile: A soyuz <-> librarian link table. This table represents the ownership in the librarian of a file which represents a binary package';
COMMENT ON COLUMN BinaryPackageFile.binarypackagerelease IS 'The binary package which is represented by the file';
COMMENT ON COLUMN BinaryPackageFile.libraryfile IS 'The file in the librarian which represents the package';
COMMENT ON COLUMN BinaryPackageFile.filetype IS 'The "type" of the file. E.g. DEB, RPM';

-- BinaryPackageName

COMMENT ON TABLE BinaryPackageName IS 'BinaryPackageName: A soyuz binary package name.';

-- Distribution

COMMENT ON TABLE Distribution IS 'Distribution: A soyuz distribution. A distribution is a collection of DistroReleases. Distributions often group together policy and may be referred to by a name such as "Ubuntu" or "Debian"';
COMMENT ON COLUMN Distribution.name IS 'The unique name of the distribution as a short lowercase name suitable for use in a URL.';
COMMENT ON COLUMN Distribution.title IS 'The title of the distribution. More a "display name" as it were. E.g. "Ubuntu" or "Debian GNU/Linux"';
COMMENT ON COLUMN Distribution.description IS 'A description of the distribution. More detailed than the title, this column may also contain information about the project this distribution is run by.';
COMMENT ON COLUMN Distribution.domainname IS 'The domain name of the distribution. This may be used both for linking to the distribution and for context-related stuff.';
COMMENT ON COLUMN Distribution.owner IS 'The person in launchpad who is in ultimate-charge of this distribution within launchpad.';
COMMENT ON COLUMN Distribution.upload_sender IS 'The email address (and name) of the default sender used by the upload processor. If NULL, we fall back to the default sender in the launchpad config.';
COMMENT ON COLUMN Distribution.upload_admin IS 'Person foreign key which have access to modify the queue ui. If NULL, we fall back to launchpad admin members';

-- DistroRelease

COMMENT ON TABLE DistroRelease IS 'DistroRelease: A soyuz distribution release. A DistroRelease is a given version of a distribution. E.g. "Warty" "Hoary" "Sarge" etc.';
COMMENT ON COLUMN DistroRelease.distribution IS 'The distribution which contains this distrorelease.';
COMMENT ON COLUMN DistroRelease.name IS 'The unique name of the distrorelease. This is a short name in lower case and would be used in sources.list configuration and in generated URLs. E.g. "warty" "sarge" "sid"';
COMMENT ON COLUMN DistroRelease.title IS 'The display-name title of the distrorelease E.g. "Warty Warthog"';
COMMENT ON COLUMN DistroRelease.description IS 'The long detailed description of the release. This may describe the focus of the release or other related information.';
COMMENT ON COLUMN DistroRelease.version IS 'The version of the release. E.g. warty would be "4.10" and hoary would be "5.4"';
COMMENT ON COLUMN DistroRelease.releasestatus IS 'The current release status of this distrorelease. E.g. "pre-release freeze" or "released"';
COMMENT ON COLUMN DistroRelease.datereleased IS 'The date on which this distrorelease was released. (obviously only valid for released distributions)';
COMMENT ON COLUMN DistroRelease.parentrelease IS 'The parent release on which this distribution is based. This is related to the inheritance stuff.';
COMMENT ON COLUMN DistroRelease.owner IS 'The ultimate owner of this distrorelease.';
COMMENT ON COLUMN DistroRelease.driver IS 'This is a person or team who can act as a driver for this specific release - note that the distribution drivers can also set goals for any release.';
COMMENT ON COLUMN DistroRelease.changeslist IS 'The email address (name name) of the changes announcement list for this distrorelease. If NULL, no announcement mail will be sent.';


-- DistroArchRelease

COMMENT ON TABLE DistroArchRelease IS 'DistroArchRelease: A soyuz distribution release for a given architecture. A distrorelease runs on various architectures. The distroarchrelease groups that architecture-specific stuff.';
COMMENT ON COLUMN DistroArchRelease.distrorelease IS 'The distribution which this distroarchrelease is part of.';


-- DistroComponentUploader

COMMENT ON TABLE DistroComponentUploader IS 'DistroComponentUploader: A record of who can upload what to where. Distributions are permitted to have multiple components. Those components are often subject to different uploader constraints. This table represents those variable constraints by linking a team to a distribution,component tuple.';
COMMENT ON COLUMN DistroComponentUploader.distribution IS 'The distribution to which this upload permission applies.';
COMMENT ON COLUMN DistroComponentUploader.component IS 'The component to which this upload permission applies.';
COMMENT ON COLUMN DIstroComponentUploader.uploader IS 'The uploader(s) permitted to upload to the given component in the given distribution. This is commonly a team but may be a single person in the case of a simple distribution.';


-- LibraryFileContent

COMMENT ON TABLE LibraryFileContent IS 'LibraryFileContent: A librarian file\'s contents. The librarian stores files in a safe and transactional way. This table represents the contents of those files within the database.';
COMMENT ON COLUMN LibraryFileContent.datecreated IS 'The date on which this librarian file was created';
COMMENT ON COLUMN LibraryFileContent.datemirrored IS 'When the file was mirrored from the librarian onto the backup server';
COMMENT ON COLUMN LibraryFileContent.filesize IS 'The size of the file';
COMMENT ON COLUMN LibraryFileContent.sha1 IS 'The SHA1 sum of the file\'s contents';
COMMENT ON COLUMN LibraryFileContent.md5 IS 'The MD5 sum of the file\'s contents';
COMMENT ON COLUMN LibraryFileContent.deleted IS 'This file has been removed from disk by the librarian garbage collector.';

-- LibraryFileAlias

COMMENT ON TABLE LibraryFileAlias IS 'LibraryFileAlias: A librarian file\'s alias. The librarian stores, along with the file contents, a record stating the file name and mimetype. This table represents it.';
COMMENT ON COLUMN LibraryFileAlias.content IS 'The libraryfilecontent which is the data in this file.';
COMMENT ON COLUMN LibraryFileAlias.filename IS 'The name of the file. E.g. "foo_1.0-1_i386.deb"';
COMMENT ON COLUMN LibraryFileAlias.mimetype IS 'The mime type of the file. E.g. "application/x-debian-package"';
COMMENT ON COLUMN LibraryFileAlias.expires IS 'The expiry date of this file. If NULL, this item may be removed as soon as it is no longer referenced. If set, the item will not be removed until this date. Once the date is passed, the file may be removed from disk even if this item is still being referenced (in which case content.deleted will be true)';
COMMENT ON COLUMN LibraryFileAlias.last_accessed IS 'Roughly when this file was last retrieved from the Librarian. Initially set to this item''s creation date.';

-- PackagePublishing

COMMENT ON VIEW BinaryPackagePublishing IS 'PackagePublishing: Publishing records for Soyuz/Lucille. Lucille publishes binarypackages in distroarchreleases. This view represents the publishing of each binarypackage not yet deleted from the distroarchrelease.';
COMMENT ON COLUMN BinaryPackagePublishing.binarypackagerelease IS 'The binarypackage which is being published';
COMMENT ON COLUMN BinaryPackagePublishing.distroarchrelease IS 'The distroarchrelease in which the binarypackage is published';
COMMENT ON COLUMN BinaryPackagePublishing.component IS 'The component in which the binarypackage is published';
COMMENT ON COLUMN BinaryPackagePublishing.section IS 'The section in which the binarypackage is published';
COMMENT ON COLUMN BinaryPackagePublishing.priority IS 'The priority at which the binarypackage is published';
COMMENT ON COLUMN BinaryPackagePublishing.scheduleddeletiondate IS 'The datetime at which this publishing entry is scheduled to be removed from the distroarchrelease';
COMMENT ON COLUMN BinaryPackagePublishing.status IS 'The current status of the packagepublishing record. For example "PUBLISHED" "PENDING" or "PENDINGREMOVAL"';

-- SourcePackagePublishing

COMMENT ON VIEW SourcePackagePublishing IS 'SourcePackagePublishing: Publishing records for Soyuz/Lucille. Lucille publishes sourcepackagereleases in distroreleases. This table represents the currently active publishing of each sourcepackagerelease. For history see SecureSourcePackagePublishingHistory.';
COMMENT ON COLUMN SourcePackagePublishing.distrorelease IS 'The distrorelease which is having the sourcepackagerelease being published into it.';
COMMENT ON COLUMN SourcePackagePublishing.sourcepackagerelease IS 'The sourcepackagerelease being published into the distrorelease.';
COMMENT ON COLUMN SourcePackagePublishing.status IS 'The current status of the sourcepackage publishing record. For example "PUBLISHED" "PENDING" or "PENDINGREMOVAL"';
COMMENT ON COLUMN SourcePackagePublishing.component IS 'The component in which the sourcepackagerelease is published';
COMMENT ON COLUMN SourcePackagePublishing.section IS 'The section in which the sourcepackagerelease is published';
COMMENT ON COLUMN SourcePackagePublishing.scheduleddeletiondate IS 'The datetime at which this publishing entry is scheduled to be removed from the distrorelease.';
COMMENT ON COLUMN SourcePackagePublishing.datepublished IS 'THIS COLUMN IS PROBABLY UNUSED';

-- SourcePackageReleaseFile

COMMENT ON TABLE SourcePackageReleaseFile IS 'SourcePackageReleaseFile: A soyuz source package release file. This table links sourcepackagerelease records to the files which comprise the input.';
COMMENT ON COLUMN SourcePackageReleaseFile.libraryfile IS 'The libraryfilealias embodying this file';
COMMENT ON COLUMN SourcePackageReleaseFile.filetype IS 'The type of the file. E.g. TAR, DIFF, DSC';
COMMENT ON COLUMN SourcePackageReleaseFile.sourcepackagerelease IS 'The sourcepackagerelease that this file belongs to';

COMMENT ON TABLE LoginToken IS 'LoginToken stores one time tokens used for validating email addresses and other tasks that require verifying an email address is valid such as password recovery and account merging. This table will be cleaned occasionally to remove expired tokens. Expiry time is not yet defined.';
COMMENT ON COLUMN LoginToken.requester IS 'The Person that made this request. This will be null for password recovery requests.';
COMMENT ON COLUMN LoginToken.requesteremail IS 'The email address that was used to login when making this request. This provides an audit trail to help the end user confirm that this is a valid request. It is not a link to the EmailAddress table as this may be changed after the request is made. This field will be null for password recovery requests.';
COMMENT ON COLUMN LoginToken.email IS 'The email address that this request was sent to.';
COMMENT ON COLUMN LoginToken.created IS 'The timestamp that this request was made.';
COMMENT ON COLUMN LoginToken.tokentype IS 'The type of request, as per dbschema.TokenType.';
COMMENT ON COLUMN LoginToken.token IS 'The token (not the URL) emailed used to uniquely identify this request. This token will be used to generate a URL that when clicked on will continue a workflow.';
COMMENT ON COLUMN LoginToken.fingerprint IS 'The GPG key fingerprint to be validated on this transaction, it means that a new register will be created relating this given key with the requester in question. The requesteremail still passing for the same usual checks.';
COMMENT ON COLUMN LoginToken.date_consumed IS 'The date and time when this token was consumed. It\'s NULL if it hasn\'t been consumed yet.';

COMMENT ON TABLE Milestone IS 'An identifier that helps a maintainer group together things in some way, e.g. "1.2" could be a Milestone that bazaar developers could use to mark a task as needing fixing in bazaar 1.2.';
COMMENT ON COLUMN Milestone.name IS 'The identifier text, e.g. "1.2."';
COMMENT ON COLUMN Milestone.product IS 'The product for which this is a milestone.';
COMMENT ON COLUMN Milestone.distribution IS 'The distribution to which this milestone belongs, if it is a distro milestone.';
COMMENT ON COLUMN Milestone.distrorelease IS 'The distrorelease for which this is a milestone. A milestone on a distrorelease is ALWAYS also a milestone for the same distribution. This is because milestones started out on products/distributions but are moving to being on series/distroreleases.';
COMMENT ON COLUMN Milestone.productseries IS 'The productseries for which this is a milestone. A milestone on a productseries is ALWAYS also a milestone for the same product. This is because milestones started out on products/distributions but are moving to being on series/distroreleases.';
COMMENT ON COLUMN Milestone.dateexpected IS 'If set, the date on which we expect this milestone to be delivered. This allows for optional sorting by date.';
COMMENT ON COLUMN Milestone.visible IS 'Whether or not this milestone should be displayed in general listings. All milestones will be visible on the "page of milestones for product foo", but we want to be able to screen out obviously old milestones over time, for the general listings and vocabularies.';

COMMENT ON TABLE PushMirrorAccess IS 'Records which users can update which push mirrors';
COMMENT ON COLUMN PushMirrorAccess.name IS 'Name of an arch archive on the push mirror, e.g. lord@emf.net--2003-example';
COMMENT ON COLUMN PushMirrorAccess.person IS 'A person that has access to update the named archive';

-- Build
COMMENT ON TABLE Builder IS 'Build: This table stores the build procedure information of a sourcepackagerelease and its results (binarypackagereleases) for a given distroarchrelease.';
COMMENT ON COLUMN Build.datecreated IS 'When the build record was created.';
COMMENT ON COLUMN Build.datebuilt IS 'When the build record was processed.';
COMMENT ON COLUMN Build.buildduration IS 'How long this build took to be processed.';
COMMENT ON COLUMN Build.distroarchrelease IS 'Points the target Distroarchrelease for this build.';
COMMENT ON COLUMN Build.processor IS 'Points to the Distroarchrelease available processor target for this build.';
COMMENT ON COLUMN Build.sourcepackagerelease IS 'Sourcepackagerelease which originated this build.';
COMMENT ON COLUMN Build.buildstate IS 'Stores the current build procedure state.';
COMMENT ON COLUMN Build.buildlog IS 'Points to the buildlog file stored in librarian.';
COMMENT ON COLUMN Build.builder IS 'Points to the builder which has once processed it.';
COMMENT ON COLUMN Build.pocket IS 'Stores the target pocket identifier for this build.';
COMMENT ON COLUMN Build.dependencies IS 'Contains a debian-like dependency line specifying the current missing-dependencies for this package.';

-- Builder
COMMENT ON TABLE Builder IS 'Builder: This table stores the build-slave registry and status information as: name, url, trusted, builderok, builderaction, failnotes.';
COMMENT ON COLUMN Builder.builderok IS 'Should a builder fail for any reason, from out-of-disk-space to not responding to the buildd master, the builderok flag is set to false and the failnotes column is filled with a reason.';
COMMENT ON COLUMN Builder.failnotes IS 'This column gets filled out with a textual description of how/why a builder has failed. If the builderok column is true then the value in this column is irrelevant and should be treated as NULL or empty.';
COMMENT ON COLUMN Builder.trusted IS 'Whether or not the builder is cleared to do SECURITY pocket builds. Such a builder will have firewall access to the embargo archives etc.';
COMMENT ON COLUMN Builder.url IS 'The url to the build slave. There may be more than one build slave on a given host so this url includes the port number to use. The default port number for a build slave is 8221';
COMMENT ON COLUMN Builder.manual IS 'Whether or not builder was manual mode, i.e., collect any result from the it, but do not dispach anything to it automatically.';


-- BuildQueue
COMMENT ON TABLE BuildQueue IS 'BuildQueue: The queue of builds in progress/scheduled to run. This table is the core of the build daemon master. It lists all builds in progress or scheduled to start.';
COMMENT ON COLUMN BuildQueue.build IS 'The build for which this queue item exists. This is how the buildd master will find all the files it needs to perform the build';
COMMENT ON COLUMN BuildQueue.builder IS 'The builder assigned to this build. Some builds will have a builder assigned to queue them up; some will be building on the specified builder already; others will not have a builder yet (NULL) and will be waiting to be assigned into a builder''s queue';
COMMENT ON COLUMN BuildQueue.created IS 'The timestamp of the creation of this row. This is used by the buildd master scheduling algorithm to decide how soon to schedule a build to run on a given builder.';
COMMENT ON COLUMN BuildQueue.buildstart IS 'The timestamp of the start of the build run on the given builder. If this is NULL then the build is not running yet.';
COMMENT ON COLUMN BuildQueue.logtail IS 'The tail end of the log of the current build. This is updated regularly as the buildd master polls the buildd slaves. Once the build is complete; the full log will be lodged with the librarian and linked into the build table.';
COMMENT ON COLUMN BuildQueue.lastscore IS 'The last score ascribed to this build record. This can be used in the UI among other places.';
COMMENT ON COLUMN BuildQueue.manual IS 'Indicates if the current record was or not rescored manually, if so it get skipped from the auto-score procedure.';

-- Mirrors

COMMENT ON TABLE Mirror IS 'Stores general information about mirror sites. Both regular pull mirrors and top tier mirrors are included.';
COMMENT ON COLUMN Mirror.baseurl IS 'The base URL to the mirror, including protocol and optional trailing slash.';
COMMENT ON COLUMN Mirror.country IS 'The country where the mirror is located.';
COMMENT ON COLUMN Mirror.name IS 'Unique name for the mirror, suitable for use in URLs.';
COMMENT ON COLUMN Mirror.description IS 'Description of the mirror.';
COMMENT ON COLUMN Mirror.freshness IS 'dbschema.MirrorFreshness enumeration indicating freshness.';
COMMENT ON COLUMN Mirror.lastcheckeddate IS 'UTC timestamp of when the last check for freshness and consistency was made. NULL indicates no check has ever been made.';
COMMENT ON COLUMN Mirror.approved IS 'True if this mirror has been approved by the Ubuntu/Canonical mirror manager, otherwise False.';

COMMENT ON TABLE MirrorContent IS 'Stores which distroarchreleases and compoenents a given mirror has.';
COMMENT ON COLUMN MirrorContent.distroarchrelease IS 'A distroarchrelease that this mirror contains.';
COMMENT ON COLUMN MirrorContent.component IS 'What component of the distroarchrelease that this mirror contains.';

COMMENT ON TABLE MirrorSourceContent IS 'Stores which distrorelease and components a given mirror that includes source packages has.';
COMMENT ON COLUMN MirrorSourceContent.distrorelease IS 'A distrorelease that this mirror contains.';
COMMENT ON COLUMN MirrorSourceContent.component IS 'What component of the distrorelease that this sourcepackage mirror contains.';

-- SecureSourcePackagePublishingHistory
COMMENT ON TABLE SecureSourcePackagePublishingHistory IS 'SourcePackagePublishingHistory: The history of a SourcePackagePublishing record. This table represents the lifetime of a publishing record from inception to deletion. Records are never removed from here and in time the publishing table may become a view onto this table. A column being NULL indicates there''s no data for that state transition. E.g. a package which is removed without being superseded won''t have datesuperseded or supersededby filled in.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.sourcepackagerelease IS 'The sourcepackagerelease being published.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.distrorelease IS 'The distrorelease into which the sourcepackagerelease is being published.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.status IS 'The current status of the publishing.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.component IS 'The component into which the publishing takes place.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.section IS 'The section into which the publishing takes place.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.datecreated IS 'The date/time on which the publishing record was created.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.datepublished IS 'The date/time on which the source was actually published into an archive.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.datesuperseded IS 'The date/time on which the source was superseded by a new source.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.supersededby IS 'The source which superseded this one.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.datemadepending IS 'The date/time on which this publishing record was made to be pending removal from the archive.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.scheduleddeletiondate IS 'The date/time at which the source is/was scheduled to be deleted.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.dateremoved IS 'The date/time at which the source was actually deleted.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.pocket IS 'The pocket into which this record is published. The RELEASE pocket (zero) provides behaviour as normal. Other pockets may append things to the distrorelease name such as the UPDATES pocket (-updates), the SECURITY pocket (-security) and the PROPOSED pocket (-proposed)';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.embargo IS 'The publishing record is embargoed from publication if this is set to TRUE. When TRUE, this column prevents the publication record from even showing up in the publishing tables.';
COMMENT ON COLUMN SecureSourcePackagePublishingHistory.embargolifted IS 'The date and time when we lifted the embargo on this publishing record. I.E. when embargo was set to FALSE having previously been set to TRUE.';
COMMENT ON VIEW SourcePackagePublishingHistory IS 'A view on SecureSourcePackagePublishingHistory that restricts access to embargoed entries';


-- Packaging
COMMENT ON TABLE Packaging IS 'DO NOT JOIN THROUGH THIS TABLE. This is a set
of information linking upstream product series (branches) to distro
packages, but it\'s not planned or likely to be complete, in the sense that
we do not attempt to have information for every branch in every derivative
distro managed in Launchpad. So don\'t join through this table to get from
product to source package, or vice versa. Rather, use the
ProductSeries.sourcepackages attribute, or the
SourcePackage.productseries attribute. You may need to create a
SourcePackage with a given sourcepackagename and distrorelease, then use its
.productrelease attribute. The code behind those methods does more than just
join through the tables, it is also smart enough to look at related
distro\'s and parent distroreleases, and at Ubuntu in particular.';
COMMENT ON COLUMN Packaging.productseries IS 'The upstream product series
that has been packaged in this distrorelease sourcepackage.';
COMMENT ON COLUMN Packaging.sourcepackagename IS 'The source package name for
the source package that includes the upstream productseries described in
this Packaging record. There is no requirement that such a sourcepackage
actually be published in the distro.';
COMMENT ON COLUMN Packaging.distrorelease IS 'The distrorelease in which the
productseries has been packaged.';
COMMENT ON COLUMN Packaging.packaging IS 'A dbschema Enum (PackagingType)
describing the way the upstream productseries has been packaged. Generally
it will be of type PRIME, meaning that the upstream productseries is the
primary substance of the package, but it might also be INCLUDES, if the
productseries has been included as a statically linked library, for example.
This allows us to say that a given Source Package INCLUDES libneon but is a
PRIME package of tla, for example. By INCLUDES we mean that the code is
actually lumped into the package as ancilliary support material, rather
than simply depending on a separate packaging of that code.';
COMMENT ON COLUMN Packaging.owner IS 'This is not the "owner" in the sense
of giving the person any special privileges to edit the Packaging record,
it is simply a record of who told us about this packaging relationship. Note
that we do not keep a history of these, so if someone sets it correctly,
then someone else sets it incorrectly, we lose the first setting.';

-- Translator / TranslationGroup

COMMENT ON TABLE TranslationGroup IS 'This represents an organised translation group that spans multiple languages. Effectively it consists of a list of people (pointers to Person), and each Person is associated with a Language. So, for each TranslationGroup we can ask the question "in this TranslationGroup, who is responsible for translating into Arabic?", for example.';
COMMENT ON TABLE Translator IS 'A translator is a person in a TranslationGroup who is responsible for a particular language. At the moment, there can only be one person in a TranslationGroup who is the Translator for a particular language. If you want multiple people, then create a launchpad team and assign that team to the language.';
COMMENT ON COLUMN Translator.translationgroup IS 'The TranslationGroup for which this Translator is working.';
COMMENT ON COLUMN Translator.language IS 'The language for which this Translator is responsible in this TranslationGroup. Note that the same person may be responsible for multiple languages, but any given language can only have one Translator within the TranslationGroup.';
COMMENT ON COLUMN Translator.translator IS 'The Person who is responsible for this language in this translation group.';

-- PocketChroot
COMMENT ON TABLE PocketChroot IS 'PocketChroots: Which chroot belongs to which pocket of which distroarchrelease. Any given pocket of any given distroarchrelease needs a specific chroot in order to be built. This table links it all together.';
COMMENT ON COLUMN PocketChroot.distroarchrelease IS 'Which distroarchrelease this chroot applies to.';
COMMENT ON COLUMN PocketChroot.pocket IS 'Which pocket of the distroarchrelease this chroot applies to. Valid values are specified in dbschema.PackagePublishingPocket';
COMMENT ON COLUMN PocketChroot.chroot IS 'The chroot used by the pocket of the distroarchrelease.';

-- POExportRequest
COMMENT ON TABLE POExportRequest IS
'A request from a user that a PO template or a PO file be exported
asynchronously.';
COMMENT ON COLUMN POExportRequest.person IS
'The person who made the request.';
COMMENT ON COLUMN POExportRequest.potemplate IS
'The PO template being requested.';
COMMENT ON COLUMN POExportRequest.pofile IS
'The PO file being requested, or NULL.';
COMMENT ON COLUMN POExportRequest.format IS
'The format the user would like the export to be in. See the RosettaFileFormat DB schema for possible values.';

-- GPGKey
COMMENT ON TABLE GPGKey IS 'A GPG key belonging to a Person';
COMMENT ON COLUMN GPGKey.keyid IS 'The 8 character GPG key id, uppercase and no whitespace';
COMMENT ON COLUMN GPGKey.fingerprint IS 'The 40 character GPG fingerprint, uppercase and no whitespace';
COMMENT ON COLUMN GPGKey.active IS 'True if this key is active for use in Launchpad context, false could be deactivated by user or revoked in the global key ring.';
COMMENT ON COLUMN GPGKey.algorithm IS 'The algorithm used to generate this key. Valid values defined in dbschema.GPGKeyAlgorithms';
COMMENT ON COLUMN GPGKey.keysize IS 'Size of the key in bits, as reported by GPG. We may refuse to deal with keysizes < 768 bits in the future.';
COMMENT ON COLUMN GPGKey.can_encrypt IS 'Whether the key has been validated for use in encryption (as opposed to just signing)';

-- Poll
COMMENT ON TABLE Poll IS 'The polls belonging to teams.';
COMMENT ON COLUMN Poll.team IS 'The team this poll belongs to';
COMMENT ON COLUMN Poll.name IS 'The unique name of this poll.';
COMMENT ON COLUMN Poll.title IS 'The title of this poll.';
COMMENT ON COLUMN Poll.dateopens IS 'The date and time when this poll opens.';
COMMENT ON COLUMN Poll.datecloses IS 'The date and time when this poll closes.';
COMMENT ON COLUMN Poll.proposition IS 'The proposition that is going to be voted.';
COMMENT ON COLUMN Poll.type IS 'The type of this poll (Simple, Preferential, etc).';
COMMENT ON COLUMN Poll.allowspoilt IS 'If people can spoil their votes.';
COMMENT ON COLUMN Poll.secrecy IS 'If people votes are SECRET (no one can see), ADMIN (team administrators can see) or PUBLIC (everyone can see).';

-- PollOption
COMMENT ON TABLE PollOption IS 'The options belonging to polls.';
COMMENT ON COLUMN PollOption.poll IS 'The poll this options belongs to.';
COMMENT ON COLUMN PollOption.name IS 'The name of this option.';
COMMENT ON COLUMN PollOption.title IS 'A short title for this option.';
COMMENT ON COLUMN PollOption.active IS 'If TRUE, people will be able to vote on this option. Otherwise they don\'t.';

-- Vote
COMMENT ON TABLE Vote IS 'The table where we store the actual votes of people.  It may or may not have a reference to the person who voted, depending on the poll\'s secrecy.';
COMMENT ON COLUMN Vote.person IS 'The person who voted. It\'s NULL for secret polls.';
COMMENT ON COLUMN Vote.poll IS 'The poll for which this vote applies.';
COMMENT ON COLUMN Vote.preference IS 'Used to identify in what order the options were chosen by a given user (in case of preferential voting).';
COMMENT ON COLUMN Vote.option IS 'The choosen option.';
COMMENT ON COLUMN Vote.token IS 'A unique token that\'s give to the user so he can change his vote later.';

-- VoteCast
COMMENT ON TABLE VoteCast IS 'Here we store who has already voted in a poll, to ensure they do not vote again, and potentially to notify people that they may still vote.';
COMMENT ON COLUMN VoteCast.person IS 'The person who voted.';
COMMENT ON COLUMN VoteCast.poll IS 'The poll in which this person voted.';

-- ShippingRequest
COMMENT ON TABLE ShippingRequest IS 'A shipping request made through ShipIt.';
COMMENT ON COLUMN ShippingRequest.recipient IS 'The person who requested.';
COMMENT ON COLUMN ShippingRequest.daterequested IS 'The date this request was made.';
COMMENT ON COLUMN ShippingRequest.shockandawe IS 'The Shock and Awe program that generated this request, in case this is part of a SA program.';
COMMENT ON COLUMN ShippingRequest.status IS 'The status of the request.';
COMMENT ON COLUMN ShippingRequest.whoapproved IS 'The person who approved this.';
COMMENT ON COLUMN ShippingRequest.whocancelled IS 'The person who cancelled this.';
COMMENT ON COLUMN ShippingRequest.reason IS 'A comment from the requester explaining why he want the CDs.';
COMMENT ON COLUMN ShippingRequest.highpriority IS 'Is this a high priority request?';
COMMENT ON COLUMN ShippingRequest.city IS 'The city to which this request should be shipped.';
COMMENT ON COLUMN ShippingRequest.phone IS 'The phone number of the requester.';
COMMENT ON COLUMN ShippingRequest.country IS 'The country to which this request should be shipped.';
COMMENT ON COLUMN ShippingRequest.province IS 'The province to which this request should be shipped.';
COMMENT ON COLUMN ShippingRequest.postcode IS 'The postcode to which this request should be shipped.';
COMMENT ON COLUMN ShippingRequest.addressline1 IS 'The address (first line) to which this request should be shipped.';
COMMENT ON COLUMN ShippingRequest.addressline2 IS 'The address (second line) to which this request should be shipped.';
COMMENT ON COLUMN ShippingRequest.organization IS 'The organization requesting the CDs.';
COMMENT ON COLUMN ShippingRequest.recipientdisplayname IS 'Used as the recipient\'s name when a request is made by a ShipIt admin in behalf of someone else';
COMMENT ON COLUMN ShippingRequest.shipment IS 'The corresponding Shipment record for this request, generated on export.';

-- RequestedCDs
COMMENT ON TABLE RequestedCDs IS 'The requested CDs of a Shipping Request.';
COMMENT ON COLUMN RequestedCDs.quantity IS 'The number of CDs.';
COMMENT ON COLUMN RequestedCDs.quantityapproved IS 'The number of CDs that were approved for shipping, in case the request was approved.';
COMMENT ON COLUMN RequestedCDs.request IS 'The request itself.';
COMMENT ON COLUMN RequestedCDs.distrorelease IS 'The distrorelease of the CDs (e.g. Ubuntu Breezy).';
COMMENT ON COLUMN RequestedCDs.architecture IS 'The architecture the CDs are meant to be installed on (e.g. x86).';
COMMENT ON COLUMN RequestedCDs.flavour IS 'The flavour of the distrorelease (e.g. EdUbuntu).';

-- StandardShipItRequest
COMMENT ON TABLE StandardShipItRequest IS 'The Standard ShipIt Requests. This is what we want most of the people to choose, having only a few people placing custom requests.';
COMMENT ON COLUMN StandardShipItRequest.flavour IS 'The Distribution Flavour';
COMMENT ON COLUMN StandardShipItRequest.quantityx86 IS 'The quantity of X86 CDs';
COMMENT ON COLUMN StandardShipItRequest.quantityamd64 IS 'The quantity of AMD64 CDs';
COMMENT ON COLUMN StandardShipItRequest.quantityppc IS 'The quantity of PowerPC CDs';
COMMENT ON COLUMN StandardShipItRequest.isdefault IS 'Is this the order that is pre-selected in the options we give for the user?';

-- ShockAndAwe
COMMENT ON TABLE ShockAndAwe IS 'Information about specific Shock And Awe programs.';
COMMENT ON COLUMN ShockAndAwe.name IS 'The name of the Shock And Awe program';
COMMENT ON COLUMN ShockAndAwe.title IS 'The title of the Shock And Awe program';
COMMENT ON COLUMN ShockAndAwe.description IS 'The description of the Shock And Awe program';

-- Shipment
COMMENT ON TABLE Shipment IS 'A shipment is the link between a ShippingRequest and a ShippingRun. When a Shipment is created for a ShippingRequest, it gets locked and can\'t be changed anymore.';
COMMENT ON COLUMN Shipment.logintoken IS 'A unique token used to identify users that come back after receiving CDs as part of an shock and awe campaign.';
COMMENT ON COLUMN Shipment.shippingrun IS 'The shippingrun to which this shipment belongs.';
COMMENT ON COLUMN Shipment.dateshipped IS 'The date when this shipment was shipped by the shipping company.';
COMMENT ON COLUMN Shipment.shippingservice IS 'The shipping service used for this shipment.';
COMMENT ON COLUMN Shipment.trackingcode IS 'A code used to track the shipment after it\'s shipped.';

-- ShippingRun
COMMENT ON TABLE ShippingRun IS 'A shipping run is a set of shipments that are sent to the shipping company in the same date.';
COMMENT ON COLUMN ShippingRun.datecreated IS 'The date this shipping run was created.';
COMMENT ON COLUMN ShippingRun.sentforshipping IS 'The exported file was sent to the shipping company already?';
COMMENT ON COLUMN ShippingRun.csvfile IS 'A csv file with all requests of this shipping run, to be sent to the shipping company.';

-- Language
COMMENT ON TABLE Language IS 'A human language.';
COMMENT ON COLUMN Language.code IS 'The ISO 639 code for this language';
COMMENT ON COLUMN Language.englishname IS 'The english name for this language';
COMMENT ON COLUMN Language.nativename IS 'The name of this language in the language itself';
COMMENT ON COLUMN Language.pluralforms IS 'The number of plural forms this language has';
COMMENT ON COLUMN Language.pluralexpression IS 'The plural expression for this language, as used by gettext';
COMMENT ON COLUMN Language.visible IS 'Whether this language should usually be visible or not';
COMMENT ON COLUMN Language.direction IS 'The direction that text is written in this language';

-- PackageBugContact
COMMENT ON TABLE PackageBugContact IS 'Defines the bug contact for a given sourcepackage in a given distribution. The bug contact will be automatically subscribed to every bug filed on this sourcepackage in this distribution.';

-- ShipItReport
COMMENT ON TABLE ShipItReport IS 'A report generated with the ShipIt data.';
COMMENT ON COLUMN ShipItReport.datecreated IS 'The date this report run was created.';
COMMENT ON COLUMN ShipItReport.csvfile IS 'A csv file with the report';

-- Continent
COMMENT ON TABLE Continent IS 'A continent in this huge world.';
COMMENT ON COLUMN Continent.code IS 'A two-letter code for a continent.';
COMMENT ON COLUMN Continent.name IS 'The name of the continent.';

-- DistributionMirror
COMMENT ON TABLE DistributionMirror IS 'A mirror of a given distribution.';
COMMENT ON COLUMN DistributionMirror.distribution IS 'The distribution to which the mirror refers to.';
COMMENT ON COLUMN DistributionMirror.name IS 'The unique name of the mirror.';
COMMENT ON COLUMN DistributionMirror.http_base_url IS 'The HTTP URL used to access the mirror.';
COMMENT ON COLUMN DistributionMirror.ftp_base_url IS 'The FTP URL used to access the mirror.';
COMMENT ON COLUMN DistributionMirror.rsync_base_url IS 'The Rsync URL used to access the mirror.';
COMMENT ON COLUMN DistributionMirror.displayname IS 'The displayname of the mirror.';
COMMENT ON COLUMN DistributionMirror.description IS 'A description of the mirror.';
COMMENT ON COLUMN DistributionMirror.owner IS 'The owner of the mirror.';
COMMENT ON COLUMN DistributionMirror.speed IS 'The speed of the mirror\'s Internet link.';
COMMENT ON COLUMN DistributionMirror.country IS 'The country where the mirror is located.';
COMMENT ON COLUMN DistributionMirror.content IS 'The content that is mirrored.';
COMMENT ON COLUMN DistributionMirror.file_list IS 'A file containing the list of files the mirror contains. Used only in case the mirror\'s pulse_type is PULL';
COMMENT ON COLUMN DistributionMirror.official_candidate IS 'Is the mirror a candidate for becoming an official mirror?';
COMMENT ON COLUMN DistributionMirror.official_approved IS 'Is the mirror approved as one of the official ones?';
COMMENT ON COLUMN DistributionMirror.enabled IS 'Is this mirror enabled?';
COMMENT ON COLUMN DistributionMirror.pulse_type IS 'The method we should use to check if the mirror is up to date.';
COMMENT ON COLUMN DistributionMirror.pulse_source IS 'A URL that we will use to check if the mirror is up to date, when the pulse_type is PULL.';

-- MirrorDistroArchRelease
COMMENT ON TABLE MirrorDistroArchRelease IS 'The mirror of the packages of a given Distro Arch Release.';
COMMENT ON COLUMN MirrorDistroArchRelease.distribution_mirror IS 'The distribution mirror.';
COMMENT ON COLUMN MirrorDistroArchRelease.distro_arch_release IS 'The distro arch release.';
COMMENT ON COLUMN MirrorDistroArchRelease.status IS 'The status of the mirror, that is, how up-to-date it is.';
COMMENT ON COLUMN MirrorDistroArchRelease.pocket IS 'The PackagePublishingPocket.';

-- MirrorDistroReleaseSource
COMMENT ON TABLE MirrorDistroReleaseSource IS 'The mirror of a given Distro Release';
COMMENT ON COLUMN MirrorDistroReleaseSource.distribution_mirror IS 'The distribution mirror.';
COMMENT ON COLUMN MirrorDistroReleaseSource.distrorelease IS 'The Distribution Release.';
COMMENT ON COLUMN MirrorDistroReleaseSource.status IS 'The status of the mirror, that is, how up-to-date it is.';

-- MirrorCDImageDistroRelease
COMMENT ON TABLE MirrorCDImageDistroRelease IS 'The mirror of a given CD/DVD image.';
COMMENT ON COLUMN MirrorCDImageDistroRelease.distribution_mirror IS 'The distribution mirror.';
COMMENT ON COLUMN MirrorCDImageDistroRelease.distrorelease IS 'The Distribution Release.';
COMMENT ON COLUMN MirrorCDImageDistroRelease.flavour IS 'The Distribution Release Flavour.';

-- MirrorProbeRecord
COMMENT ON TABLE MirrorProbeRecord IS 'Records stored when a mirror is probed.';
COMMENT ON COLUMN MirrorProbeRecord.distribution_mirror IS 'The DistributionMirror.';
COMMENT ON COLUMN MirrorProbeRecord.log_file IS 'The log file of the probe.';
COMMENT ON COLUMN MirrorProbeRecord.date_created IS 'The date and time the probe was performed.';

-- TranslationImportQueueEntry
COMMENT ON TABLE TranslationImportQueueEntry IS 'Queue with translatable resources pending to be imported into Rosetta.';
COMMENT ON COLUMN TranslationImportQueueEntry.path IS 'The path (included the filename) where this file was stored when we imported it.';
COMMENT ON COLUMN TranslationImportQueueEntry.content IS 'The file content that is being imported.';
COMMENT ON COLUMN TranslationImportQueueEntry.importer IS 'The person that did the import.';
COMMENT ON COLUMN TranslationImportQueueEntry.dateimported IS 'The timestamp when the import was done.';
COMMENT ON COLUMN TranslationImportQueueEntry.distrorelease IS 'The distribution release related to this import.';
COMMENT ON COLUMN TranslationImportQueueEntry.sourcepackagename IS 'The source package name related to this import.';
COMMENT ON COLUMN TranslationImportQueueEntry.productseries IS 'The product series related to this import.';
COMMENT ON COLUMN TranslationImportQueueEntry.is_published IS 'Notes whether is a published upload.';
COMMENT ON COLUMN TranslationImportQueueEntry.pofile IS 'Link to the POFile where this import will end.';
COMMENT ON COLUMN TranslationImportQueueEntry.potemplate IS 'Link to the POTemplate where this import will end.';
COMMENT ON COLUMN TranslationImportQueueEntry.date_status_changed IS 'The date when the status of this entry was changed.';
COMMENT ON COLUMN TranslationImportQueueEntry.status IS 'The status of the import: 1 Approved, 2 Imported, 3 Deleted, 4 Failed, 5 Needs Review, 6 Blocked.';

-- SupportContact
COMMENT ON TABLE PackageBugContact IS 'Defines the support contact for a given ticket target. The support contact will be automatically subscribed to every support request filed on the ticket target.';

-- PersonalPackageArchive
COMMENT ON TABLE PersonalPackageArchive IS 'Contains the information about the archives generated based on personal packages.';
COMMENT ON COLUMN PersonalPackageArchive.person IS 'Owner of this personal archive.';
COMMENT ON COLUMN PersonalPackageArchive.distrorelease IS 'Target Distrorelease for this personal archive.';
COMMENT ON COLUMN PersonalPackageArchive.packages IS 'Cache of the generated Packages file.';
COMMENT ON COLUMN PersonalPackageArchive.sources IS 'Cache of the generated Sources file.';
COMMENT ON COLUMN PersonalPackageArchive.release IS 'Cache of the generated Release file.';
COMMENT ON COLUMN PersonalPackageArchive.release_gpg IS 'Cache of the detached GPG signature of the cached Release file.';
COMMENT ON COLUMN PersonalPackageArchive.datelastupdated IS 'Time when cache of the archive files was last updated.';

-- PersonalSourcepackagePublication
COMMENT ON TABLE PersonalSourcePackagePublication IS 'Contains the information about which sourcepackagerelease is included in a Personal Package Archive.';
COMMENT ON COLUMN PersonalSourcePackagePublication.personalpackagearchive IS 'Target Personal Package Archive.';
COMMENT ON COLUMN PersonalSourcePackagePublication.sourcepackagerelease IS 'Target Sourcepackagerelease.';


-- Component
COMMENT ON TABLE Component IS 'Known components in Launchpad';
COMMENT ON COLUMN Component.name IS 'Component name text';


-- Section
COMMENT ON TABLE Section IS 'Known sections in Launchpad';
COMMENT ON COLUMN Section.name IS 'Section name text';


-- ComponentSelection
COMMENT ON TABLE ComponentSelection IS 'Allowed components in a given distrorelease.';
COMMENT ON COLUMN ComponentSelection.distrorelease IS 'Refers to the distrorelease in question.';
COMMENT ON COLUMN ComponentSelection.component IS 'Refers to the component in qestion.';


-- SectionSelection
COMMENT ON TABLE SectionSelection IS 'Allowed sections in a given distrorelease.';
COMMENT ON COLUMN SectionSelection.distrorelease IS 'Refers to the distrorelease in question.';
COMMENT ON COLUMN SectionSelection.section IS 'Refers to the section in question.';

-- PillarName
COMMENT ON TABLE PillarName IS 'A cache of the names of our "Pillar''s" (distribution, product, project) to ensure uniqueness in this shared namespace. This is a materialized view maintained by database triggers.';

