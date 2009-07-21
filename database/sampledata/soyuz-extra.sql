-- Copyright 2009 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

-- Packaging
INSERT INTO Packaging (sourcepackage, packaging, product)
VALUES ((SELECT id FROM SourcePackage WHERE id = 
	 (SELECT id from SourcePackageName WHERE name = 'mozilla-firefox')),
	1, -- dbschema.Packaging.PRIME
	(SELECT id FROM Product WHERE name = 'firefox'));

-- Builder
INSERT INTO Builder (processor, url, name, title, description, owner, 
builderok) 
VALUES ((SELECT id from processor where name = '386'), 
	'http://localhost:8221/', 
	'bob', 'Bob The builder', 
	'The default build-slave', 
	1, 
	False);

-- Buildqueue
INSERT INTO BuildQueue (build, builder, logtail, created, lastscore) 
VALUES (2, 
	1,
	'Dummy sampledata entry, not processing', 
	'2005-06-15 09:14:12.820778', 
	1);


-- Add Nominated Architecures (trust ids)

UPDATE DistroRelease set nominatedarchindep=1 where id=1;
UPDATE DistroRelease set nominatedarchindep=6 where id=3;
