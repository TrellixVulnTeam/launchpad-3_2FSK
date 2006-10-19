/*
 * This patch renames DistroReleaseQueue* to PackageUpload* and adds the
 * Archive table.
 */

SET client_min_messages=ERROR;

-- Remove the old PPA
DROP TABLE PersonalSourcePackagePublication;
DROP TABLE PersonalPackageArchive;


-- Create the new tables...
CREATE TABLE Archive (
	id SERIAL NOT NULL PRIMARY KEY
	);

CREATE TABLE PersonalPackageArchive (
	id SERIAL NOT NULL PRIMARY KEY,
	person INTEGER NOT NULL REFERENCES person(id),
	archive INTEGER NOT NULL REFERENCES archive(id),
	
	CONSTRAINT personalpackagearchive__unq UNIQUE
		   (person, archive)
	);


-- Drop all the views associated with publishing
DROP VIEW PublishedPackageView;
DROP VIEW BinaryPackageFilePublishing;
DROP VIEW SourcePackageFilePublishing;
DROP VIEW BinaryPackagePublishingView;
DROP VIEW SourcePackagePublishingView;
DROP VIEW BinaryPackagePublishing;
DROP VIEW SourcePackagePublishing;
DROP VIEW BinaryPackagePublishingHistory;
DROP VIEW SourcePackagePublishingHistory;

-- Add archive to publishing and distribution tables.

ALTER TABLE SecureSourcePackagePublishingHistory
    ADD COLUMN archive INTEGER;
ALTER TABLE SecureSourcePackagePublishingHistory
    ADD CONSTRAINT securesourcepackagepublishinghistory_archive_fk
    FOREIGN KEY (archive) REFERENCES archive(id);
ALTER TABLE SecureBinaryPackagePublishingHistory
    ADD COLUMN archive INTEGER;
ALTER TABLE SecureBinaryPackagePublishingHistory
    ADD CONSTRAINT securebinarypackagepublishinghistory_archive_fk
    FOREIGN KEY (archive) REFERENCES archive(id);

ALTER TABLE Distribution
    ADD COLUMN main_archive INTEGER;
ALTER TABLE Distribution
    ADD CONSTRAINT distribution_main_archive_fk
    FOREIGN KEY (main_archive) REFERENCES archive(id);

-- Rebuild the views to include archive...
--- Layer 1 of 3
CREATE VIEW SourcePackagePublishingHistory AS 
SELECT securesourcepackagepublishinghistory.id, 
       securesourcepackagepublishinghistory.archive,
       securesourcepackagepublishinghistory.sourcepackagerelease, 
       securesourcepackagepublishinghistory.distrorelease, 
       securesourcepackagepublishinghistory.status, 
       securesourcepackagepublishinghistory.component, 
       securesourcepackagepublishinghistory.section, 
       securesourcepackagepublishinghistory.datecreated, 
       securesourcepackagepublishinghistory.datepublished, 
       securesourcepackagepublishinghistory.datesuperseded, 
       securesourcepackagepublishinghistory.supersededby, 
       securesourcepackagepublishinghistory.datemadepending, 
       securesourcepackagepublishinghistory.scheduleddeletiondate, 
       securesourcepackagepublishinghistory.dateremoved, 
       securesourcepackagepublishinghistory.pocket, 
       securesourcepackagepublishinghistory.embargo, 
       securesourcepackagepublishinghistory.embargolifted
  FROM securesourcepackagepublishinghistory
 WHERE securesourcepackagepublishinghistory.embargo = false;

CREATE VIEW BinaryPackagePublishingHistory AS 
SELECT securebinarypackagepublishinghistory.id, 
       securebinarypackagepublishinghistory.archive,
       securebinarypackagepublishinghistory.binarypackagerelease, 
       securebinarypackagepublishinghistory.distroarchrelease, 
       securebinarypackagepublishinghistory.status, 
       securebinarypackagepublishinghistory.component, 
       securebinarypackagepublishinghistory.section, 
       securebinarypackagepublishinghistory.priority, 
       securebinarypackagepublishinghistory.datecreated, 
       securebinarypackagepublishinghistory.datepublished, 
       securebinarypackagepublishinghistory.datesuperseded, 
       securebinarypackagepublishinghistory.supersededby, 
       securebinarypackagepublishinghistory.datemadepending, 
       securebinarypackagepublishinghistory.scheduleddeletiondate, 
       securebinarypackagepublishinghistory.dateremoved, 
       securebinarypackagepublishinghistory.pocket, 
       securebinarypackagepublishinghistory.embargo, 
       securebinarypackagepublishinghistory.embargolifted
  FROM securebinarypackagepublishinghistory
 WHERE securebinarypackagepublishinghistory.embargo = false;

--- Layer 2 of 3
CREATE VIEW SourcePackagePublishing AS
SELECT sourcepackagepublishinghistory.id, 
       sourcepackagepublishinghistory.archive,
       sourcepackagepublishinghistory.sourcepackagerelease, 
       sourcepackagepublishinghistory.distrorelease, 
       sourcepackagepublishinghistory.status, 
       sourcepackagepublishinghistory.component, 
       sourcepackagepublishinghistory.section, 
       sourcepackagepublishinghistory.datecreated, 
       sourcepackagepublishinghistory.datepublished, 
       sourcepackagepublishinghistory.datesuperseded, 
       sourcepackagepublishinghistory.supersededby, 
       sourcepackagepublishinghistory.datemadepending, 
       sourcepackagepublishinghistory.scheduleddeletiondate, 
       sourcepackagepublishinghistory.dateremoved, 
       sourcepackagepublishinghistory.pocket, 
       sourcepackagepublishinghistory.embargo, 
       sourcepackagepublishinghistory.embargolifted
  FROM sourcepackagepublishinghistory
 WHERE sourcepackagepublishinghistory.status < 7;

CREATE VIEW BinaryPackagePublishing AS
SELECT binarypackagepublishinghistory.id, 
       binarypackagepublishinghistory.archive,
       binarypackagepublishinghistory.binarypackagerelease, 
       binarypackagepublishinghistory.distroarchrelease, 
       binarypackagepublishinghistory.status, 
       binarypackagepublishinghistory.component, 
       binarypackagepublishinghistory.section, 
       binarypackagepublishinghistory.priority, 
       binarypackagepublishinghistory.datecreated, 
       binarypackagepublishinghistory.datepublished, 
       binarypackagepublishinghistory.datesuperseded, 
       binarypackagepublishinghistory.supersededby, 
       binarypackagepublishinghistory.datemadepending, 
       binarypackagepublishinghistory.scheduleddeletiondate, 
       binarypackagepublishinghistory.dateremoved, 
       binarypackagepublishinghistory.pocket, 
       binarypackagepublishinghistory.embargo, 
       binarypackagepublishinghistory.embargolifted
  FROM binarypackagepublishinghistory
 WHERE binarypackagepublishinghistory.status < 7;

--- Layer 3 of 3
---- .PPV
CREATE VIEW SourcePackagePublishingView AS
SELECT sourcepackagepublishing.id, 
       distrorelease.name AS distroreleasename, 
       sourcepackagename.name AS sourcepackagename, 
       component.name AS componentname, 
       section.name AS sectionname, 
       distrorelease.distribution, 
       sourcepackagepublishing.status AS 
       publishingstatus, 
       sourcepackagepublishing.pocket,
       sourcepackagepublishing.archive
  FROM sourcepackagepublishing
  JOIN distrorelease ON
       sourcepackagepublishing.distrorelease = distrorelease.id
  JOIN sourcepackagerelease ON 
       sourcepackagepublishing.sourcepackagerelease = sourcepackagerelease.id
  JOIN sourcepackagename ON 
       sourcepackagerelease.sourcepackagename = sourcepackagename.id
  JOIN component ON sourcepackagepublishing.component = component.id
  JOIN section ON sourcepackagepublishing.section = section.id;

CREATE VIEW BinaryPackagePublishingView AS
SELECT binarypackagepublishing.id, 
       distrorelease.name AS distroreleasename, 
       binarypackagename.name AS binarypackagename, 
       component.name AS componentname, 
       section.name AS sectionname, 
       binarypackagepublishing.priority, 
       distrorelease.distribution, 
       binarypackagepublishing.status AS publishingstatus, 
       binarypackagepublishing.pocket,
       binarypackagepublishing.archive
  FROM binarypackagepublishing, 
       distrorelease, 
       distroarchrelease, 
       binarypackagerelease, 
       binarypackagename, 
       component, 
       section
 WHERE binarypackagepublishing.distroarchrelease = distroarchrelease.id 
   AND distroarchrelease.distrorelease = distrorelease.id
   AND binarypackagepublishing.binarypackagerelease = binarypackagerelease.id
   AND binarypackagerelease.binarypackagename = binarypackagename.id
   AND binarypackagepublishing.component = component.id
   AND binarypackagepublishing.section = section.id;

---- .PFP
CREATE VIEW SourcePackageFilePublishing AS
SELECT (libraryfilealias.id::text || '.'::text) || 
        sourcepackagepublishing.id::text AS id,
       distrorelease.distribution, 
       sourcepackagepublishing.id AS sourcepackagepublishing, 
       sourcepackagereleasefile.libraryfile AS libraryfilealias, 
       libraryfilealias.filename AS libraryfilealiasfilename, 
       sourcepackagename.name AS sourcepackagename, 
       component.name AS componentname, 
       distrorelease.name AS distroreleasename, 
       sourcepackagepublishing.status AS publishingstatus, 
       sourcepackagepublishing.pocket,
       sourcepackagepublishing.archive
  FROM sourcepackagepublishing
  JOIN sourcepackagerelease ON 
       sourcepackagepublishing.sourcepackagerelease = sourcepackagerelease.id
  JOIN sourcepackagename ON 
       sourcepackagerelease.sourcepackagename = sourcepackagename.id
  JOIN sourcepackagereleasefile ON 
       sourcepackagereleasefile.sourcepackagerelease = sourcepackagerelease.id
  JOIN libraryfilealias ON 
       libraryfilealias.id = sourcepackagereleasefile.libraryfile
  JOIN distrorelease ON 
       sourcepackagepublishing.distrorelease = distrorelease.id
  JOIN component ON sourcepackagepublishing.component = component.id;

CREATE VIEW BinaryPackageFilePublishing AS
SELECT (libraryfilealias.id::text || '.'::text) || 
        binarypackagepublishing.id::text AS id, 
       distrorelease.distribution, 
       binarypackagepublishing.id AS binarypackagepublishing, 
       component.name AS componentname, 
       libraryfilealias.filename AS libraryfilealiasfilename, 
       sourcepackagename.name AS sourcepackagename, 
       binarypackagefile.libraryfile AS libraryfilealias, 
       distrorelease.name AS distroreleasename, 
       distroarchrelease.architecturetag, 
       binarypackagepublishing.status AS publishingstatus, 
       binarypackagepublishing.pocket,
       binarypackagepublishing.archive
  FROM binarypackagepublishing
  JOIN binarypackagerelease ON 
       binarypackagepublishing.binarypackagerelease = binarypackagerelease.id
  JOIN build ON binarypackagerelease.build = build.id
  JOIN sourcepackagerelease ON 
       build.sourcepackagerelease = sourcepackagerelease.id
  JOIN sourcepackagename ON 
       sourcepackagerelease.sourcepackagename = sourcepackagename.id
  JOIN binarypackagefile ON 
       binarypackagefile.binarypackagerelease = binarypackagerelease.id
  JOIN libraryfilealias ON binarypackagefile.libraryfile = libraryfilealias.id
  JOIN distroarchrelease ON 
       binarypackagepublishing.distroarchrelease = distroarchrelease.id
  JOIN distrorelease ON distroarchrelease.distrorelease = distrorelease.id
  JOIN component ON binarypackagepublishing.component = component.id;

---- PPV
CREATE VIEW PublishedPackageView AS
SELECT binarypackagepublishing.id, 
       binarypackagepublishing.archive,
       distroarchrelease.id AS distroarchrelease, 
       distrorelease.distribution, 
       distrorelease.id AS distrorelease, 
       distrorelease.name AS distroreleasename, 
       processorfamily.id AS processorfamily, 
       processorfamily.name AS processorfamilyname, 
       binarypackagepublishing.status AS packagepublishingstatus, 
       component.name AS component, 
       section.name AS section, 
       binarypackagerelease.id AS binarypackagerelease, 
       binarypackagename.name AS binarypackagename, 
       binarypackagerelease.summary AS binarypackagesummary, 
       binarypackagerelease.description AS binarypackagedescription, 
       binarypackagerelease.version AS binarypackageversion, 
       build.id AS build, 
       build.datebuilt, 
       sourcepackagerelease.id AS sourcepackagerelease, 
       sourcepackagerelease.version AS sourcepackagereleaseversion, 
       sourcepackagename.name AS sourcepackagename, 
       binarypackagepublishing.pocket, 
       binarypackagerelease.fti AS binarypackagefti
  FROM binarypackagepublishing
  JOIN distroarchrelease ON
       distroarchrelease.id = binarypackagepublishing.distroarchrelease
  JOIN distrorelease ON distroarchrelease.distrorelease = distrorelease.id
  JOIN processorfamily ON
       distroarchrelease.processorfamily = processorfamily.id
  JOIN component ON binarypackagepublishing.component = component.id
  JOIN binarypackagerelease ON
       binarypackagepublishing.binarypackagerelease = binarypackagerelease.id
  JOIN section ON binarypackagepublishing.section = section.id
  JOIN binarypackagename ON
       binarypackagerelease.binarypackagename = binarypackagename.id
  JOIN build ON binarypackagerelease.build = build.id
  JOIN sourcepackagerelease ON
       build.sourcepackagerelease = sourcepackagerelease.id
  JOIN sourcepackagename ON
       sourcepackagerelease.sourcepackagename = sourcepackagename.id;

-- Data migration for distribution and publishing tables
--- Each distribution needs a main archive
INSERT INTO ARCHIVE (id) SELECT id FROM Distribution;
UPDATE Distribution SET main_archive = id;

--- Update the publishing tables to reference this archive
UPDATE SecureSourcePackagePublishingHistory
   SET archive = (
       SELECT distribution.main_archive
        FROM Distribution, DistroRelease
       WHERE distribution.id = distrorelease.distribution
         AND distrorelease.id =
             securesourcepackagepublishinghistory.distrorelease);

UPDATE SecureBinaryPackagePublishingHistory
   SET archive = (
       SELECT distribution.main_archive
        FROM Distribution, DistroRelease, DistroArchRelease
       WHERE distribution.id = distrorelease.distribution
         AND distrorelease.id = distroarchrelease.distrorelease
         AND distroarchrelease.id =
             securebinarypackagepublishinghistory.distroarchrelease);

-- Render the archive columns NOT NULL in the publishing tables
ALTER TABLE SecureSourcePackagePublishingHistory
    ALTER COLUMN archive SET NOT NULL;
ALTER TABLE SecureBinaryPackagePublishingHistory
    ALTER COLUMN archive SET NOT NULL;

-- Add some useful indexes for package publishing
CREATE INDEX securesourcepackagepublishinghistory__archive__idx
    ON SecureSourcePackagePublishingHistory (archive);
CREATE INDEX securebinarypackagepublishinghistory__archive__idx
    ON SecureBinaryPackagePublishingHistory (archive);


/*
 * Upload queue renaming and adding archive fk.
 */


-- DRQ -> UQ
ALTER TABLE DistroReleaseQueue DROP CONSTRAINT distroreleasequeue_changesfile_fk;
ALTER TABLE DistroReleaseQueue DROP CONSTRAINT distroreleasequeue_distrorelease_fk;
ALTER TABLE DistroReleaseQueue RENAME TO PackageUpload;
ALTER TABLE distroreleasequeue_id_seq RENAME TO packageupload_id_seq;
ALTER TABLE PackageUpload
    ALTER COLUMN id SET DEFAULT nextval('packageupload_id_seq');
ALTER INDEX distroreleasequeue_pkey RENAME TO packageupload_pkey;
ALTER INDEX distroreleasequeue_distrorelease_key RENAME TO packageupload_distrorelease_key;
ALTER TABLE PackageUpload ADD COLUMN Archive INTEGER;

UPDATE PackageUpload SET archive=(
       SELECT main_archive
         FROM Distribution, DistroRelease
        WHERE DistroRelease.id = PackageUpload.distrorelease
          AND Distribution.id = DistroRelease.distribution
          );


ALTER TABLE PackageUpload ALTER COLUMN Archive SET NOT NULL;
ALTER TABLE PackageUpload
         ADD CONSTRAINT packageupload_changesfile_fk 
            FOREIGN KEY (changesfile) REFERENCES libraryfilealias(id);
ALTER TABLE PackageUpload
         ADD CONSTRAINT packageupload_distrorelease_fk
	    FOREIGN KEY (distrorelease) REFERENCES distrorelease(id);
ALTER TABLE PackageUpload
         ADD CONSTRAINT packageupload_archive_fk
	    FOREIGN KEY (archive) REFERENCES archive(id);
	    
-- DRQS -> UQS
ALTER TABLE DistroReleaseQueueSource 
    DROP CONSTRAINT distroreleasequeuesource_distroreleasequeue_fk;
ALTER TABLE DistroReleaseQueueSource 
    DROP CONSTRAINT distroreleasequeuesource_sourcepackagerelease_fk;
ALTER TABLE DistroReleaseQueueSource RENAME TO PackageUploadSource;
ALTER TABLE PackageUploadSource RENAME COLUMN DistroReleaseQueue TO PackageUpload;
ALTER TABLE distroreleasequeuesource_id_seq RENAME TO packageuploadsource_id_seq;
ALTER TABLE PackageUploadSource
    ALTER COLUMN id SET DEFAULT nextval('packageuploadsource_id_seq');
ALTER INDEX distroreleasequeuesource_pkey RENAME TO packageuploadsource_pkey;
ALTER INDEX distroreleasequeuesource__distroreleasequeue__sourcepackagerele 
  RENAME TO packageuploadsource__distroreleasequeue__sourcepackagerelease;
ALTER INDEX distroreleasequeuesource__sourcepackagerelease__idx 
  RENAME TO packageuploadsource__sourcepackagerelease__idx;
ALTER TABLE PackageUploadSource
               ADD CONSTRAINT packageuploadsource_packageupload_fk
	          FOREIGN KEY (packageupload) REFERENCES PackageUpload(id);
ALTER TABLE PackageUploadSource
               ADD CONSTRAINT packageuploadsource_sourcepackagerelease_fk
	          FOREIGN KEY (sourcepackagerelease) 
		   REFERENCES SourcePackageRelease(id);
		  
-- DRQB -> UQB
ALTER TABLE DistroReleaseQueueBuild 
    DROP CONSTRAINT distroreleasequeuebuild_build_fk;
ALTER TABLE DistroReleaseQueueBuild
    DROP CONSTRAINT distroreleasequeuebuild_distroreleasequeue_fk;
ALTER TABLE DistroReleaseQueueBuild RENAME TO PackageUploadBuild;
ALTER TABLE PackageUploadBuild RENAME COLUMN DistroReleaseQueue TO PackageUpload;
ALTER TABLE distroreleasequeuebuild_id_seq RENAME TO packageuploadbuild_id_seq;
ALTER TABLE PackageUploadBuild
    ALTER COLUMN id SET DEFAULT nextval('packageuploadbuild_id_seq');
ALTER INDEX distroreleasequeuebuild_pkey RENAME TO packageuploadbuild_pkey;
ALTER INDEX distroreleasequeuebuild__distroreleasequeue__build__unique
  RENAME TO packageuploadbuild__packageupload__build__unique;
ALTER INDEX distroreleasequeuebuild__build__idx 
  RENAME TO packageuploadbuild__build__idx;
ALTER TABLE PackageUploadBuild 
    ADD CONSTRAINT packageuploadbuild_build_fk 
       FOREIGN KEY (build) REFERENCES Build(id);
ALTER TABLE PackageUploadBuild 
    ADD CONSTRAINT packageuploadbuild_packageupload_fk 
       FOREIGN KEY (packageupload) REFERENCES PackageUpload(id);
  

-- DRQC -> UQC
ALTER TABLE DistroReleaseQueueCustom
    DROP CONSTRAINT distroreleasequeuecustom_distroreleasequeue_fk;
ALTER TABLE DistroReleaseQueueCustom
    DROP CONSTRAINT distroreleasequeuecustom_libraryfilealias_fk;
ALTER TABLE DistroReleaseQueueCustom RENAME TO PackageUploadCustom;
ALTER TABLE PackageUploadCustom RENAME COLUMN DistroReleaseQueue TO PackageUpload;
ALTER TABLE distroreleasequeuecustom_id_seq RENAME TO packageuploadcustom_id_seq;
ALTER TABLE PackageUploadCustom
    ALTER COLUMN id SET DEFAULT nextval('packageuploadcustom_id_seq');
ALTER INDEX distroreleasequeuecustom_pkey RENAME TO packageuploadcustom_pkey;
ALTER TABLE PackageUploadCustom 
    ADD CONSTRAINT packageuploadcustom_packageupload_fk 
       FOREIGN KEY (packageupload) REFERENCES PackageUpload(id);
ALTER TABLE PackageUploadCustom 
    ADD CONSTRAINT packageuploadcustom_libraryfilealias_fk 
       FOREIGN KEY (libraryfilealias) REFERENCES LibraryFileAlias(id);

/* Miscellaneous extra archive columns */
ALTER TABLE SourcePackageRelease ADD COLUMN UploadArchive INTEGER;
UPDATE SourcePackageRelease SET UploadArchive=(
       SELECT main_archive
         FROM Distribution, DistroRelease
        WHERE DistroRelease.id = SourcePackageRelease.uploaddistrorelease
          AND Distribution.id = DistroRelease.distribution
          );
ALTER TABLE SourcePackageRelease ALTER COLUMN UploadArchive SET NOT NULL;
ALTER TABLE SourcePackageRelease 
    ADD CONSTRAINT sourcepackagerelease_uploadarchive_fk 
       FOREIGN KEY (uploadarchive) REFERENCES Archive(id);

ALTER TABLE Build ADD COLUMN archive INTEGER;
UPDATE Build SET archive=(
       SELECT main_archive
         FROM Distribution, DistroRelease, DistroArchRelease
        WHERE distribution.id = DistroRelease.distribution
          AND DistroRelease.id = DistroArchRelease.DistroRelease
	  AND DistroArchRelease.id = Build.distroarchrelease
	);
ALTER TABLE Build
    ADD CONSTRAINT build_archive_fk 
       FOREIGN KEY (archive) REFERENCES Archive(id);

INSERT INTO LaunchpadDatabaseRevision VALUES (67, 90, 0);
