/*
   LAUNCHPAD SAMPLE DATA
   
   This is some sample data for the launchpad system.  This requires the default
   data to be inserted first.
*/

/* 
 Sample data for Soyuz
*/
 
-- Component
INSERT INTO Component (name) VALUES ('default_component');

-- Section

INSERT INTO Section (name) VALUES ('default_section');

-- Schema
INSERT INTO schema (name, title, description, owner, extensible) VALUES('Mark schema', 'TITLE', 'description', (Select id from Person where displayname = 'Mark Shuttleworth'), true);
INSERT INTO Schema (name, title, description, owner, extensible) values('schema', 'SCHEMA', 'description', (Select id from Person where displayname = 'Mark Shuttleworth'), true);
INSERT INTO Schema (name, title, description, owner, extensible) values('trema', 'XCHEMA', 'description', (Select id from Person where displayname = 'Mark Shuttleworth'), true);
INSERT INTO Schema (name, title, description, owner, extensible) values('enema', 'ENHEMA', 'description', (Select id from Person where displayname = 'Mark Shuttleworth'), true);


 -- Label
INSERT INTO Label (schema, name, title, description)
VALUES ((SELECT id FROM Schema WHERE name = 'Mark schema'),
         'blah', 'blah', 'blah');
 -- ProcessorFamily
INSERT INTO ProcessorFamily (name, title, description, owner) 
VALUES ('x86', 'Intel 386 compatible chips', 'Bring back the 8086!', 
         (SELECT id FROM Person WHERE displayname = 'Mark Shuttleworth'));
 
 -- Processor
INSERT INTO Processor (family, name, title, description, owner)
VALUES ((SELECT id FROM ProcessorFamily WHERE name = 'x86'),
         '386', 'Intel 386', 'Intel 386 and its many derivatives and clones, the basic 32-bit chip in the x86 family',
        (SELECT id FROM Person WHERE displayname = 'Mark Shuttleworth'));

-- Distribution
INSERT INTO Distribution (name, title, description, domainname, owner) values ('ubuntu', 'Ubuntu Distribution', 'text ...', 'domain', 1);
INSERT INTO Distribution (name, title, description, domainname, owner) values ('redhat', 'Redhat Advanced Server', 'some text', 'domain', 1);
INSERT INTO Distribution (name, title, description, domainname, owner) values ('debian', 'Debian Crazy-Unstable', 'text ...', 'domain', 1);
INSERT INTO Distribution (name, title, description, domainname, owner) values ('gentoo', 'The Gentoo bits', 'another ...', 'domain', 1);
INSERT INTO Distribution (name, title, description, domainname, owner) values ('porkypigpolka', 'Porky Pig Polka Swine-oriented Distribution', 'blabla', 'domain', 1);

INSERT INTO Distrorelease (name, title, description, distribution, version, components, sections, releasestate, owner) values ('warty', 'Warty', 'text ...', 1, 'PONG', 1, 1, 0, 1);
INSERT INTO Distrorelease (name, title, description, distribution, version, components, sections, releasestate, owner) values ('6.0', 'Six Six Six', 'some text', 2, '12321.XX', 1, 1, 0, 1);
INSERT INTO Distrorelease (name, title, description, distribution, version, components, sections, releasestate, owner) values ('hoary', 'Hoary Crazy-Unstable', 'text ...', 1, 'EWEpp##', 1, 1, 0, 1);
INSERT INTO Distrorelease (name, title, description, distribution, version, components, sections, releasestate, owner) values ('7.0', 'Seven', 'another ...', 2, 'ACK ACK', 1, 1, 0, 1);
INSERT INTO Distrorelease (name, title, description, distribution, version, components, sections, releasestate, owner) values ('grumpy', 'G-R-U-M-P-Y', 'blabla', 1, 'PINKPY POLLY', 1, 1, 0, 1);


--DistroArchrelease
INSERT INTO Distroarchrelease(distrorelease, processorfamily, architecturetag, 
	owner) VALUES 
	((SELECT id FROM Distrorelease where name = 'warty'), 
	(SELECT id from Processorfamily where name = 'x86'), 
	'warty--x86--devel--0', 
	(SELECT id FROM Person WHERE displayname = 'Mark Shuttleworth')
	);

-- Build

INSERT INTO Build (datecreated, processor, distroarchrelease, buildstate)
	VALUES
	('2004-08-24',
	(SELECT id FROM Processor where name = '386'),
	1, -- hardcoded ?!?! use query instead
	1  -- ??
	);	

--Binarypackagename
INSERT INTO Binarypackagename(name) VALUES ('mozilla-firefox-0.8');
INSERT INTO Binarypackagename(name) VALUES ('mozilla-thunderbird-1.5');
INSERT INTO Binarypackagename(name) VALUES ('python-twisted-1.3');
INSERT INTO Binarypackagename(name) VALUES ('bugzilla-2.18');
INSERT INTO Binarypackagename(name) VALUES ('arch-1.0');
INSERT INTO Binarypackagename(name) VALUES ('kiwi-2.0');
INSERT INTO Binarypackagename(name) VALUES ('plone-1.0');




-- Binarypackage
INSERT INTO Binarypackage (sourcepackagerelease, binarypackagename, 
version, shortdesc, description, build, binpackageformat, component, 
section, priority) 
	VALUES (
(SELECT id from Sourcepackagerelease WHERE sourcepackage = 
	(SELECT id from Sourcepackage where name = 'mozilla-firefox')),
(SELECT id from Binarypackagename WHERE name = 'mozilla-firefox-0.8'), 
'0.8', 'Mozilla Firefox 0.8', 'some text', 
	1, -- hardcoded ?? use query instead
	1, -- DEB ?
	1, -- default component
	1, -- default section
	3); -- highest priority

INSERT INTO Binarypackage (sourcepackagerelease, binarypackagename, 
version, shortdesc, description, build, binpackageformat, component, 
section, priority) 
	VALUES (
(SELECT id from Sourcepackagerelease WHERE sourcepackage = 
	(SELECT id from Sourcepackage where name = 'mozilla-thunderbird')),
(SELECT id from Binarypackagename WHERE name = 'mozilla-thunderbird-1.5'), 
'1.5', 'Mozilla Thunderbird 1.5', 'some text', 
	1, -- hardcoded ?? use query instead
	1, -- DEB ?
	1, -- default component
	1, -- default section
	3); -- highest priority

INSERT INTO Binarypackage (sourcepackagerelease, binarypackagename, 
version, shortdesc, description, build, binpackageformat, component, 
section, priority) 
	VALUES (
(SELECT id from Sourcepackagerelease WHERE sourcepackage = 
	(SELECT id from Sourcepackage where name = 'python-twisted')),
(SELECT id from Binarypackagename WHERE name = 'python-twisted-1.3'), 
'1.3', 'Python Twisted 1.3', 'some text', 
	1, -- hardcoded ?? use query instead
	1, -- DEB ?
	1, -- default component
	1, -- default section
	3); -- highest priority

INSERT INTO Binarypackage (sourcepackagerelease, binarypackagename, 
version, shortdesc, description, build, binpackageformat, component, 
section, priority) 
	VALUES (
(SELECT id from Sourcepackagerelease WHERE sourcepackage = 
	(SELECT id from Sourcepackage where name = 'bugzilla')),
(SELECT id from Binarypackagename WHERE name = 'bugzilla-2.18'), 
'2.18', 'Bugzilla 2.18', 'some text', 
	1, -- hardcoded ?? use query instead
	1, -- DEB ?
	1, -- default component
	1, -- default section
	3); -- highest priority

INSERT INTO Binarypackage (sourcepackagerelease, binarypackagename, 
version, shortdesc, description, build, binpackageformat, component, 
section, priority) 
	VALUES (
(SELECT id from Sourcepackagerelease WHERE sourcepackage = 
	(SELECT id from Sourcepackage where name = 'arch')),
(SELECT id from Binarypackagename WHERE name = 'arch-1.0'), 
'1.0', 'ARCH 1.0', 'some text', 
	1, -- hardcoded ?? use query instead
	1, -- DEB ?
	1, -- default component
	1, -- default section
	3); -- highest priority

INSERT INTO Binarypackage (sourcepackagerelease, binarypackagename, 
version, shortdesc, description, build, binpackageformat, component, 
section, priority) 
	VALUES (
(SELECT id from Sourcepackagerelease WHERE sourcepackage = 
	(SELECT id from Sourcepackage where name = 'kiwi2')),
(SELECT id from Binarypackagename WHERE name = 'kiwi-2.0'), 
'2.0', 'Python Kiwi 2.0', 'some text', 
	1, -- hardcoded ?? use query instead
	1, -- DEB ?
	1, -- default component
	1, -- default section
	3); -- highest priority

INSERT INTO Binarypackage (sourcepackagerelease, binarypackagename, 
version, shortdesc, description, build, binpackageformat, component, 
section, priority) 
	VALUES (
(SELECT id from Sourcepackagerelease WHERE sourcepackage = 
	(SELECT id from Sourcepackage where name = 'plone')),
(SELECT id from Binarypackagename WHERE name = 'plone-1.0'), 
'1.0', 'Plone 1.0', 'some text', 
	1, -- hardcoded ?? use query instead
	1, -- DEB ?
	1, -- default component
	1, -- default section
	3); -- highest priority

-- Packagepublishing

INSERT INTO Packagepublishing (binarypackage, distroarchrelease, component, 
	section, priority) 
	VALUES
	((SELECT id FROM Binarypackage where binarypackagename = 
	  (SELECT id FROM Binarypackagename where name = 'mozilla-firefox-0.8')
	),
	(SELECT id FROM Distroarchrelease WHERE architecturetag = 
	   'warty--x86--devel--0'),
	1, -- default_component
	1, -- default_section
	3); -- ???

INSERT INTO Packagepublishing (binarypackage, distroarchrelease, component, 
	section, priority) 
	VALUES
	((SELECT id FROM Binarypackage where binarypackagename = 
	  (SELECT id FROM Binarypackagename where name = 
	     'mozilla-thunderbird-1.5')
	),
	(SELECT id FROM Distroarchrelease WHERE architecturetag = 
	   'warty--x86--devel--0'),
	1, -- default_component
	1, -- default_section
	3); -- ???

INSERT INTO Packagepublishing (binarypackage, distroarchrelease, component, 
	section, priority) 
	VALUES
	((SELECT id FROM Binarypackage where binarypackagename = 
	  (SELECT id FROM Binarypackagename where name = 'python-twisted-1.3')
	),
	(SELECT id FROM Distroarchrelease WHERE architecturetag = 
	   'warty--x86--devel--0'),
	1, -- default_component
	1, -- default_section
	3); -- ???

INSERT INTO Packagepublishing (binarypackage, distroarchrelease, component, 
	section, priority) 
	VALUES
	((SELECT id FROM Binarypackage where binarypackagename = 
	  (SELECT id FROM Binarypackagename where name = 'kiwi-2.0')
	),
	(SELECT id FROM Distroarchrelease WHERE architecturetag = 
           'warty--x86--devel--0'),
	1, -- default_component
	1, -- default_section
	3); -- ???


--SourcePackageUpload


INSERT INTO Sourcepackageupload (distrorelease, sourcepackagerelease, 
				uploadstatus) 
VALUES ((SELECT id FROM Distrorelease WHERE name = 'warty'),
        (SELECT id FROM Sourcepackagerelease WHERE 
	 sourcepackage = (SELECT id from Sourcepackage where name = 'plone')),
	1);
INSERT INTO Sourcepackageupload (distrorelease, sourcepackagerelease, 
				uploadstatus) 
VALUES ((SELECT id FROM Distrorelease WHERE name = 'warty'),
        (SELECT id FROM Sourcepackagerelease WHERE 
	 sourcepackage = (SELECT id from Sourcepackage where name = 'kiwi2')),
	1);
INSERT INTO Sourcepackageupload (distrorelease, sourcepackagerelease, 
				uploadstatus) 
VALUES ((SELECT id FROM Distrorelease WHERE name = 'warty'),
        (SELECT id FROM Sourcepackagerelease WHERE 
	 sourcepackage = (SELECT id from Sourcepackage where name = 'mozilla-firefox')),
	1);
INSERT INTO Sourcepackageupload (distrorelease, sourcepackagerelease, 
				uploadstatus) 
VALUES ((SELECT id FROM Distrorelease WHERE name = 'warty'),
        (SELECT id FROM Sourcepackagerelease WHERE 
	 sourcepackage = (SELECT id from Sourcepackage where name = 'mozilla-thunderbird')),
	1);
INSERT INTO Sourcepackageupload (distrorelease, sourcepackagerelease, 
				uploadstatus) 
VALUES ((SELECT id FROM Distrorelease WHERE name = 'hoary'),
        (SELECT id FROM Sourcepackagerelease WHERE 
	 sourcepackage = (SELECT id from Sourcepackage where name = 'python-twisted')),
	1);
INSERT INTO Sourcepackageupload (distrorelease, sourcepackagerelease, 
				uploadstatus) 
VALUES ((SELECT id FROM Distrorelease WHERE name = 'hoary'),
        (SELECT id FROM Sourcepackagerelease WHERE 
	 sourcepackage = (SELECT id from Sourcepackage where name = 'kiwi2')),
	1);
INSERT INTO Sourcepackageupload (distrorelease, sourcepackagerelease, 
				uploadstatus) 
VALUES ((SELECT id FROM Distrorelease WHERE name = 'hoary'),
        (SELECT id FROM Sourcepackagerelease WHERE 
	sourcepackage = (SELECT id from Sourcepackage where name = 'bugzilla')),
	1);

INSERT INTO Sourcepackageupload (distrorelease, sourcepackagerelease, 
				uploadstatus) 
VALUES ((SELECT id FROM Distrorelease WHERE name = 'grumpy'),
        (SELECT id FROM Sourcepackagerelease WHERE 
	sourcepackage = (SELECT id from Sourcepackage where name = 'bugzilla')),
	1);

INSERT INTO Sourcepackageupload (distrorelease, sourcepackagerelease, 
				uploadstatus) 
VALUES ((SELECT id FROM Distrorelease WHERE name = 'grumpy'),
        (SELECT id FROM Sourcepackagerelease WHERE 
	sourcepackage = (SELECT id from Sourcepackage where name = 'arch')),
	1);

/*
 * Sample data for Rosetta
 */

INSERT INTO Person ( displayname, givenname, familyname ) VALUES ( 'Carlos Perelló Marín', 'Carlos', 'Perelló Marín' );
INSERT INTO Project ( owner, name, displayname, title, shortdesc, description, homepageurl )
VALUES ((SELECT id FROM Person WHERE displayname='Carlos Perelló Marín'),
	'gnome', 'GNOME', 'The GNOME Project', 'foo', 'bar', 'http://www.gnome.org/' );
INSERT INTO Project ( owner, name, displayname, title, shortdesc, description, homepageurl )
VALUES ((SELECT id FROM Person WHERE displayname='Carlos Perelló Marín'),
	'iso-codes', 'iso-codes', 'iso-codes', 'foo', 'bar', 'http://www.gnome.org/' );
INSERT INTO Product ( project, owner, name, displayname, title, shortdesc, description, homepageurl )
VALUES ((SELECT id FROM Project WHERE name='gnome'),
	(SELECT id FROM Person WHERE displayname='Carlos Perelló Marín'),
	'evolution', 'Evolution', 'The Evolution Groupware', 'foo', 'bar', 'http://www.novell.com/' );
INSERT INTO Product ( project, owner, name, displayname, title, shortdesc, description, homepageurl )
VALUES ((SELECT id FROM Project WHERE name='gnome'),
	(SELECT id FROM Person WHERE displayname='Carlos Perelló Marín'),
	'gnome-terminal', 'GNOME Terminal', 'The GNOME terminal emulator', 'foo', 'bar', 'http://www.gnome.org/' );
INSERT INTO Product ( project, owner, name, displayname, title, shortdesc, description, homepageurl )
VALUES ((SELECT id FROM Project WHERE name='iso-codes'),
	(SELECT id FROM Person WHERE displayname='Carlos Perelló Marín'),
	'iso-codes', 'iso-codes', 'The iso-codes', 'foo', 'bar', 'http://www.novell.com/' );
INSERT INTO ArchArchive (name, title, description, visible)
VALUES ('gnome', 'GNOME', 'The GNOME Project', false);
INSERT INTO ArchArchive (name, title, description, visible)
VALUES ('iso-codes', 'iso-codes', 'The iso-codes', false);
INSERT INTO ArchNamespace (archarchive, category, branch, version, visible)
VALUES ((SELECT id FROM ArchArchive WHERE name = 'gnome'), 'gnome', 'evolution',
	'2.0', false);
INSERT INTO ArchNamespace (archarchive, category, branch, version, visible)
VALUES ((SELECT id FROM ArchArchive WHERE name = 'iso-codes'), 'iso-codes', 'iso-codes',
	'0.35', false);
INSERT INTO Branch (archnamespace, title, description, owner)
VALUES ((SELECT id FROM ArchNamespace
	 WHERE category = 'gnome' AND
	       branch = 'evolution' AND
	       version = '2.0'),
	'Evolution 2.0', 'text',
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'));
INSERT INTO Branch (archnamespace, title, description, owner)
VALUES ((SELECT id FROM ArchNamespace
	 WHERE category = 'iso-codes' AND
	       branch = 'iso-codes' AND
	       version = '0.35'),
	'Iso-codes 0.35', 'text',
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'));

INSERT INTO License (legalese) VALUES ('GPL-2');

/* Sample POTemplate file */

INSERT INTO POTemplate (product, branch, priority, name, title,
			description, copyright, license, datecreated,
			path, iscurrent, messagecount, owner)
VALUES ((SELECT id FROM Product WHERE name = 'evolution'),
        (SELECT id FROM Branch
	WHERE title = 'Evolution 2.0'),
	2, 'evolution-2.0',
	'Main POT file for the Evolution 2.0 development branch',
	'I suppose we should create a long description here....',
	'Copyright (C) 2003  Ximian Inc.',
	(SELECT id FROM License WHERE legalese = 'GPL-2'),
	timestamp '2004-08-17 09:10',
	'po/', TRUE, 3, 	
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'));

INSERT INTO POTemplate (product, branch, priority, name, title,
			description, copyright, license, datecreated,
			path, iscurrent, messagecount, owner)
VALUES ((SELECT id FROM Product WHERE name = 'iso-codes'),
        (SELECT id FROM Branch
	WHERE title = 'Iso-codes 0.35'),
	2, 'iso_639',
	'POT file for the iso_639 strings',
	'I suppose we should create a long description here....',
	'Copyright',
	(SELECT id FROM License WHERE legalese = 'GPL-2'),
	timestamp '2004-08-17 09:10',
	'iso_639/', TRUE, 3, 	
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'));


--  1
INSERT INTO POMsgID (msgid) VALUES ('evolution addressbook');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences)
VALUES (1, 1, 1, FALSE, FALSE, FALSE,
	'a11y/addressbook/ea-addressbook-view.c:94\n'
	'a11y/addressbook/ea-addressbook-view.c:103\n'
	'a11y/addressbook/ea-minicard-view.c:119');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (1, 1, now(), now(), TRUE, 0);
--  2
INSERT INTO POMsgID (msgid) VALUES ('current addressbook folder');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences)
VALUES (2, 2, 1, FALSE, FALSE, FALSE,
	'a11y/addressbook/ea-minicard-view.c:101');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (2, 2, now(), now(), TRUE, 0);
--  3
INSERT INTO POMsgID (msgid) VALUES ('have ');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences)
VALUES (3, 3, 1, FALSE, FALSE, FALSE,
	'a11y/addressbook/ea-minicard-view.c:102');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (3, 3, now(), now(), TRUE, 0);
--  4
INSERT INTO POMsgID (msgid) VALUES ('has ');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences)
VALUES (4, 4, 1, FALSE, FALSE, FALSE,
	'a11y/addressbook/ea-minicard-view.c:102');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (4, 4, now(), now(), TRUE, 0);
--  5
INSERT INTO POMsgID (msgid) VALUES (' cards');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences)
VALUES (5, 5, 1, FALSE, FALSE, FALSE,
	'a11y/addressbook/ea-minicard-view.c:104');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (5, 5, now(), now(), TRUE, 0);
--  6
INSERT INTO POMsgID (msgid) VALUES (' card');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences)
VALUES (6, 6, 1, FALSE, FALSE, FALSE,
	'a11y/addressbook/ea-minicard-view.c:104');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (6, 6, now(), now(), TRUE, 0);
--  7
INSERT INTO POMsgID (msgid) VALUES ('contact\'s header: ');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences)
VALUES (7, 7, 1, FALSE, FALSE, FALSE,
	'a11y/addressbook/ea-minicard-view.c:105');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (7, 7, now(), now(), TRUE, 0);
--  8
INSERT INTO POMsgID (msgid) VALUES ('evolution minicard');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences)
VALUES (8, 8, 1, FALSE, FALSE, FALSE,
	'a11y/addressbook/ea-minicard.c:166');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (8, 8, now(), now(), TRUE, 0);
--  9
INSERT INTO POMsgID (msgid) VALUES ('This addressbook could not be opened.');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences, sourcecomment)
VALUES (9, 9, 1, FALSE, FALSE, FALSE,
	'addressbook/addressbook-errors.xml.h:2',
	'addressbook:ldap-init primary');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (9, 9, now(), now(), TRUE, 0);
-- 10
INSERT INTO POMsgID (msgid) VALUES ('This addressbook server might unreachable or the server name may be misspelled or your network connection could be down.');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences, sourcecomment)
VALUES (10, 10, 1, FALSE, FALSE, FALSE,
	'addressbook/addressbook-errors.xml.h:4',
	'addressbook:ldap-init secondary');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (10, 10, now(), now(), TRUE, 0);
-- 11
INSERT INTO POMsgID (msgid) VALUES ('Failed to authenticate with LDAP server.');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences, sourcecomment)
VALUES (11, 11, 1, FALSE, FALSE, FALSE,
	'addressbook/addressbook-errors.xml.h:6',
	'addressbook:ldap-auth primary');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (11, 11, now(), now(), TRUE, 0);
-- 12
INSERT INTO POMsgID (msgid) VALUES ('Check to make sure your password is spelled correctly and that you are using a supported login method. Remember that many passwords are case sensitive; your caps lock might be on.');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences, sourcecomment)
VALUES (12, 12, 1, FALSE, FALSE, FALSE,
	'addressbook/addressbook-errors.xml.h:8',
	'addressbook:ldap-auth secondary');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (12, 12, now(), now(), TRUE, 0);
-- 13
INSERT INTO POMsgID (msgid) VALUES ('This addressbook server does not have any suggested search bases.');
-- 14
INSERT INTO POMsgID (msgid) VALUES ('This LDAP server may use an older version of LDAP, which does not support this functionality or it may be misconfigured. Ask your administrator for supported search bases.');
-- 15
INSERT INTO POMsgID (msgid) VALUES ('This server does not support LDAPv3 schema information.');
-- 16
INSERT INTO POMsgID (msgid) VALUES ('Could not get schema information for LDAP server.');
-- 17
INSERT INTO POMsgID (msgid) VALUES ('LDAP server did not respond with valid schema information.');
-- 18
INSERT INTO POMsgID (msgid) VALUES ('Could not remove addressbook.');
-- 19
INSERT INTO POMsgID (msgid) VALUES ('{0}');
-- 20
INSERT INTO POMsgID (msgid) VALUES ('Category editor not available.');
-- 21
INSERT INTO POMsgID (msgid) VALUES ('{1}');
-- 22
INSERT INTO POMsgID (msgid) VALUES ('Unable to open addressbook');
-- 23
INSERT INTO POMsgID (msgid) VALUES ('Error loading addressbook.');
-- 24
INSERT INTO POMsgID (msgid) VALUES ('Unable to perform search.');
-- 25
INSERT INTO POMsgID (msgid) VALUES ('Would you like to save your changes?');
-- 26
INSERT INTO POMsgID (msgid) VALUES ('You have made modifications to this contact. Do you want to save these changes?');
-- 27
INSERT INTO POMsgID (msgid) VALUES ('_Discard');
-- 28
INSERT INTO POMsgID (msgid) VALUES ('Cannot move contact.');
-- 29
INSERT INTO POMsgID (msgid) VALUES ('You are attempting to move a contact from one addressbook to another but it cannot be removed from the source. Do you want to save a copy instead?');
-- 30
INSERT INTO POMsgID (msgid) VALUES ('Unable to save contact(s).');
-- 31
INSERT INTO POMsgID (msgid) VALUES ('Error saving contacts to {0}: {1}');
-- 32
INSERT INTO POMsgID (msgid) VALUES ('The Evolution addressbook has quit unexpectedly.');
-- 33
INSERT INTO POMsgID (msgid) VALUES ('Your contacts for {0} will not be available until Evolution is restarted.');
-- 34
INSERT INTO POMsgID (msgid) VALUES ('Default Sync Address:');
-- 35
INSERT INTO POMsgID (msgid) VALUES ('Could not load addressbook');
-- 36
INSERT INTO POMsgID (msgid) VALUES ('Could not read pilot\'s Address application block');
-- 37
INSERT INTO POMsgID (msgid) VALUES ('*Control*F2');
-- 38
INSERT INTO POMsgID (msgid) VALUES ('Autocompletion');
-- 39
INSERT INTO POMsgID (msgid) VALUES ('C_ontacts');
-- 40
INSERT INTO POMsgID (msgid) VALUES ('Certificates');
-- 41
INSERT INTO POMsgID (msgid) VALUES ('Configure autocomplete here');
-- 42
INSERT INTO POMsgID (msgid) VALUES ('Contacts');
-- 43
INSERT INTO POMsgID (msgid) VALUES ('Evolution Addressbook');
-- 44
INSERT INTO POMsgID (msgid) VALUES ('Evolution Addressbook address pop-up');
-- 45
INSERT INTO POMsgID (msgid) VALUES ('Evolution Addressbook address viewer');
-- 46
INSERT INTO POMsgID (msgid) VALUES ('Evolution Addressbook card viewer');
-- 47
INSERT INTO POMsgID (msgid) VALUES ('Evolution Addressbook component');
-- 48
INSERT INTO POMsgID (msgid) VALUES ('Evolution S/Mime Certificate Management Control');
-- 49
INSERT INTO POMsgID (msgid) VALUES ('Evolution folder settings configuration control');
-- 50
INSERT INTO POMsgID (msgid) VALUES ('Manage your S/MIME certificates here');
-- 51
INSERT INTO POMsgID (msgid) VALUES ('New Contact');
-- 52
INSERT INTO POMsgID (msgid) VALUES ('_Contact');
-- 53
INSERT INTO POMsgID (msgid) VALUES ('Create a new contact');
-- 54
INSERT INTO POMsgID (msgid) VALUES ('New Contact List');
-- 55
INSERT INTO POMsgID (msgid) VALUES ('Contact _List');
-- 56
INSERT INTO POMsgID (msgid) VALUES ('Create a new contact list');
-- 57
INSERT INTO POMsgID (msgid) VALUES ('New Address Book');
-- 58
INSERT INTO POMsgID (msgid) VALUES ('Address _Book');
-- 59
INSERT INTO POMsgID (msgid) VALUES ('Create a new address book');
-- 60
INSERT INTO POMsgID (msgid) VALUES ('Failed upgrading Addressbook settings or folders.');
-- 61
INSERT INTO POMsgID (msgid) VALUES ('Migrating...');
-- 62
INSERT INTO POMsgID (msgid) VALUES ('Migrating \`%s\':');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences, flagscomment)
VALUES (62, 13, 1, FALSE, FALSE, FALSE,
	'addressbook/gui/component/addressbook-migrate.c:124\n'
	'calendar/gui/migration.c:188 mail/em-migrate.c:1201',
	'c-format');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (13, 62, now(), now(), TRUE, 0);
-- 63
INSERT INTO POMsgID (msgid) VALUES ('On This Computer');
-- 64
INSERT INTO POMsgID (msgid) VALUES ('Personal');
-- 65
INSERT INTO POMsgID (msgid) VALUES ('On LDAP Servers');
-- 66
INSERT INTO POMsgID (msgid) VALUES ('LDAP Servers');
-- 67
INSERT INTO POMsgID (msgid) VALUES ('Autocompletion Settings');
-- 68
INSERT INTO POMsgID (msgid) VALUES ('The location and hierarchy of the Evolution contact folders has changed since Evolution 1.x.\n\nPlease be patient while Evolution migrates your folders...');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences)
VALUES (68, 14, 1, FALSE, FALSE, FALSE,
	'addressbook/gui/component/addressbook-migrate.c:1123');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (14, 68, now(), now(), TRUE, 0);
-- 69
INSERT INTO POMsgID (msgid) VALUES ('The format of mailing list contacts has changed.\n\nPlease be patient while Evolution migrates your folders...');
-- 70
INSERT INTO POMsgID (msgid) VALUES ('The way Evolution stores some phone numbers has changed.\n\nPlease be patient while Evolution migrates your folders...');
-- 71
INSERT INTO POMsgID (msgid) VALUES ('Evolution\'s Palm Sync changelog and map files have changed.\n\nPlease be patient while Evolution migrates your Pilot Sync data...');
-- 72
INSERT INTO POMsgID (msgid) VALUES ('Address book \'%s\' will be removed. Are you sure you want to continue?');
-- 73
INSERT INTO POMsgID (msgid) VALUES ('Delete');
-- 74
INSERT INTO POMsgID (msgid) VALUES ('Properties...');
-- 75
INSERT INTO POMsgID (msgid) VALUES ('Accessing LDAP Server anonymously');
-- 76
INSERT INTO POMsgID (msgid) VALUES ('Failed to authenticate.\n');
-- 77
INSERT INTO POMsgID (msgid) VALUES ('%sEnter password for %s (user %s)');
-- 78
INSERT INTO POMsgID (msgid) VALUES ('EFolderList xml for the list of completion uris');
-- 79
INSERT INTO POMsgID (msgid) VALUES ('Position of the vertical pane in main view');
-- 80
INSERT INTO POMsgID (msgid) VALUES ('The number of characters that must be typed before evolution will attempt to autocomplete');
-- 81
INSERT INTO POMsgID (msgid) VALUES ('URI for the folder last used in the select names dialog');
-- 82
INSERT INTO POMsgID (msgid) VALUES ('*');
-- 83
INSERT INTO POMsgID (msgid) VALUES ('1');
-- 84
INSERT INTO POMsgID (msgid) VALUES ('3268');
-- 85
INSERT INTO POMsgID (msgid) VALUES ('389');
-- 86
INSERT INTO POMsgID (msgid) VALUES ('5');
-- 87
INSERT INTO POMsgID (msgid) VALUES ('636');
-- 88
INSERT INTO POMsgID (msgid) VALUES ('<b>Authentication</b>');
-- 89
INSERT INTO POMsgID (msgid) VALUES ('<b>Display</b>');
-- 90
INSERT INTO POMsgID (msgid) VALUES ('<b>Downloading</b>');
-- 91
INSERT INTO POMsgID (msgid) VALUES ('<b>Searching</b>');
-- 92
INSERT INTO POMsgID (msgid) VALUES ('<b>Server Information</b>');
/* A plural form: */
-- 93
INSERT INTO POMsgID (msgid) VALUES ('%d contact');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, iscomplete, obsolete,
		      fuzzy, filereferences, flagscomment)
VALUES (93, 15, 1, FALSE, FALSE, FALSE,
	'addressbook/gui/widgets/e-addressbook-model.c:151',
	'c-format');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (15, 93, now(), now(), TRUE, 0);
-- 94
INSERT INTO POMsgID (msgid) VALUES ('%d contacts');
INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			     datelastseen, inlastrevision, pluralform)
VALUES (15, 94, now(), now(), TRUE, 0);
-- 95
INSERT INTO POMsgID (msgid) VALUES ('_Add Group');


INSERT INTO POFile (potemplate, language, topcomment, header, fuzzyheader,
		    lasttranslator, currentcount, updatescount, rosettacount,
		    pluralforms)
VALUES ((SELECT id FROM POTemplate WHERE name = 'evolution-2.0'),
        (SELECT id FROM Language WHERE code = 'es'),
	' traducción de es.po al Spanish\n'
        ' translation of es.po to Spanish\n'
        ' translation of evolution.HEAD to Spanish\n'
        ' Copyright © 2000-2002 Free Software Foundation, Inc.\n'
        ' This file is distributed under the same license as the evolution package.\n'
        ' Carlos Perelló Marín <carlos@gnome-db.org>, 2000-2001.\n'
        ' Héctor García Álvarez <hector@scouts-es.org>, 2000-2002.\n'
        ' Ismael Olea <Ismael@olea.org>, 2001, (revisiones) 2003.\n'
        ' Eneko Lacunza <enlar@iname.com>, 2001-2002.\n'
        ' Héctor García Álvarez <hector@scouts-es.org>, 2002.\n'
        ' Pablo Gonzalo del Campo <pablodc@bigfoot.com>,2003 (revisión).\n'
        ' Francisco Javier F. Serrador <serrador@cvs.gnome.org>, 2003, 2004.\n'
        '\n'
        '\n',
        'Project-Id-Version: es\n'
        'POT-Creation-Date: 2004-08-17 11:10+0200\n'
        'PO-Revision-Date: 2004-08-15 19:32+0200\n'
        'Last-Translator: Francisco Javier F. Serrador <serrador@cvs.gnome.org>\n'
        'Language-Team: Spanish <traductores@es.gnome.org>\n'
        'MIME-Version: 1.0\n'
        'Content-Type: text/plain; charset=UTF-8\n'
        'Content-Transfer-Encoding: 8bit\n'
        'Report-Msgid-Bugs-To: serrador@hispalinux.es\n'
        'X-Generator: KBabel 1.3.1\n'
        'Plural-Forms:  nplurals=2; plural=(n != 1);\n',
	FALSE,
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'),
	2, 0, 1, 2);

INSERT INTO POFile (potemplate, language, topcomment, header, fuzzyheader,
		    lasttranslator, currentcount, updatescount, rosettacount,
		    pluralforms)
VALUES ((SELECT id FROM POTemplate WHERE name = 'iso_639'),
        (SELECT id FROM Language WHERE code = 'cy'),
        '\n',
        '\n',
	FALSE,
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'),
	0, 0, 0, 0);

INSERT INTO POFile (potemplate, language, topcomment, header, fuzzyheader,
		    lasttranslator, currentcount, updatescount, rosettacount,
		    pluralforms)
VALUES ((SELECT id FROM POTemplate WHERE name = 'iso_639'),
        (SELECT id FROM Language WHERE code = 'es'),
        '\n',
        '\n',
	FALSE,
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'),
	0, 0, 0, 0);

INSERT INTO POTranslation (translation)
VALUES ('libreta de direcciones de Evolution');

INSERT INTO POMsgSet (primemsgid, sequence, potemplate, pofile, iscomplete,
		      obsolete, fuzzy) 
VALUES (1, 1, 1, 1, TRUE, FALSE, FALSE);

INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			      datelastseen, inlastrevision, pluralform)
VALUES (16, 1, now(), now(), TRUE, 0);

INSERT INTO POTranslationSighting (pomsgset, potranslation, license, datefirstseen, datelastactive, 
				   inlastrevision, pluralform, person, origin)
VALUES (16, 1, 1, now(), now(), TRUE, 0,
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'),
	0);

INSERT INTO POTranslation (translation)
VALUES ('carpeta de libretas de direcciones actual');

INSERT INTO POMsgSet (primemsgid, sequence, potemplate, pofile, iscomplete, obsolete,
		      fuzzy) 
VALUES (2, 2, 1, 1, TRUE, FALSE, FALSE);

INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			      datelastseen, inlastrevision, pluralform)
VALUES (17, 2, now(), now(), TRUE, 0);

INSERT INTO POTranslationSighting (pomsgset, potranslation, license, datefirstseen, datelastactive, 
				   inlastrevision, pluralform, person, origin)
VALUES (17, 2, 1, now(), now(), TRUE, 0,
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'),
	0);
	
/* An example for a fuzzy string */
INSERT INTO POTranslation (translation)
VALUES ('tiene');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, pofile, iscomplete, obsolete,
		      fuzzy) 
VALUES (3, 3, 1, 1, FALSE, FALSE, TRUE);

INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			      datelastseen, inlastrevision, pluralform)
VALUES (18, 3, now(), now(), TRUE, 0);

INSERT INTO POTranslationSighting (pomsgset, potranslation, license, datefirstseen, datelastactive, 
				   inlastrevision, pluralform, person, origin)
VALUES (18, 3, 1, now(), now(), TRUE, 0,
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'),
	0);

/* An example for plural forms */
INSERT INTO POTranslation (translation)
VALUES ('%d contacto');

INSERT INTO POTranslation (translation)
VALUES ('%d contactos');

INSERT INTO POMsgSet (primemsgid, sequence, potemplate, pofile, iscomplete, obsolete,
		      fuzzy) 
VALUES (93, 4, 1, 1, TRUE, FALSE, FALSE);

INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			      datelastseen, inlastrevision, pluralform)
VALUES (19, 93, now(), now(), TRUE, 0);

INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			      datelastseen, inlastrevision, pluralform)
VALUES (19, 94, now(), now(), TRUE, 1);

INSERT INTO POTranslationSighting (pomsgset, potranslation, license, datefirstseen, datelastactive, 
				   inlastrevision, pluralform, person, origin)
VALUES (19, 4, 1, now(), now(), TRUE, 0,
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'),
	0);

INSERT INTO POTranslationSighting (pomsgset, potranslation, license, datefirstseen, datelastactive, 
				   inlastrevision, pluralform, person, origin)
VALUES (19, 5, 1, now(), now(), TRUE, 1,
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'),
	0);

/* An example for obsolete string */
INSERT INTO POTranslation (translation)
VALUES ('_Añadir grupo');
INSERT INTO POMsgSet (primemsgid, sequence, potemplate, pofile, iscomplete, obsolete,
		      fuzzy) 
VALUES (95, 5, 1, 1, TRUE, TRUE, FALSE);

INSERT INTO POMsgIDSighting (pomsgset, pomsgid, datefirstseen,
			      datelastseen, inlastrevision, pluralform)
VALUES (20, 95, now(), now(), TRUE, 0);

INSERT INTO POTranslationSighting (pomsgset, potranslation, license, datefirstseen, datelastactive, 
				   inlastrevision, pluralform, person, origin)
VALUES (20, 6, 1, now(), now(), TRUE, 0,
	(SELECT id FROM Person WHERE displayname = 'Carlos Perelló Marín'),
	0);



/* Malone sample data */
INSERT INTO Person (displayname, givenname, familyname)
VALUES  ('Dave Miller', 'David', 'Miller');

INSERT INTO Person (displayname) VALUES ('Sample Person');

INSERT INTO EmailAddress (email, person, status) VALUES (
'justdave@bugzilla.org',
(SELECT id FROM Person WHERE displayname='Dave Miller'),
2
);
INSERT INTO BugSystemType (name, title, description, homepage, owner)
VALUES ('bugzilla', 'BugZilla', 'Dave Miller\'s Labour of Love, '
|| 'the Godfather of Open Source project issue tracking.',
'http://www.bugzilla.org/', 
(SELECT id FROM Person WHERE displayname='Dave Miller')
);
INSERT INTO Project (owner, name, displayname, title, shortdesc, 
description, homepageurl)
VALUES (
(SELECT id FROM Person WHERE displayname='Sample Person'),
'mozilla', 'The Mozilla Project', 'The Mozilla Project',
'The Mozilla Project is the largest open source web browser collaborative project.',
'The Mozilla Project is the largest open source web browser '
|| 'collaborative project. The Mozilla Project produces several internet '
|| 'applications that are very widely used, and is also a center for '
|| 'collaboration on internet standards work by open source groups.',
'http://www.mozilla.org/'
);
INSERT INTO Product (project, owner, name, displayname,  title, shortdesc,
description)
VALUES (
(SELECT id FROM Project WHERE name='mozilla'),
(SELECT id FROM Person WHERE displayname='Sample Person'),
'firefox', 'Mozilla Firefox', 'Mozilla Firefox',
'The Mozilla Firefox web browser',
'The Mozilla Firefox web browser'
);
INSERT INTO ProductRelease (product, datereleased, version, owner)
VALUES (
(SELECT id FROM Product WHERE name='firefox'),
timestamp '2004-06-28 00:00', 'mozilla-firefox-0.9.1',
(SELECT id FROM Person WHERE displayname='Sample Person')
);

/* 
INSERT INTO Sourcepackage (maintainer, name, title, description)
VALUES (
(SELECT id FROM Person WHERE displayname='Sample Person'),
'mozilla-firefox',
'Ubuntu Mozilla Firefox Source Package', 'text'
);
*/
INSERT INTO SourcepackageRelease (sourcepackage, srcpackageformat, creator,
version, dateuploaded, urgency)
VALUES (
(SELECT id FROM Sourcepackage WHERE name='mozilla-firefox'),
1, (SELECT id FROM Person WHERE displayname='Sample Person'),
'0.9.1-1', timestamp '2004-06-29 00:00', 1
);

INSERT INTO Manifest (datecreated, owner)
VALUES (
timestamp '2004-06-29 00:00', 
(SELECT id FROM Person WHERE displayname='Sample Person')
);

INSERT INTO CodeRelease (sourcepackagerelease, manifest)
VALUES (
(SELECT id FROM Sourcepackage WHERE name='mozilla-firefox'),
(SELECT max(id) FROM Manifest)
);

INSERT INTO Bug (name, title, shortdesc, description, owner, communityscore,
communitytimestamp, activityscore, activitytimestamp, hits,
hitstimestamp)
VALUES ('bob', 'An odd problem', 'Something strange is wrong somewhere',
'Something strange is wrong somewhere',
(SELECT id FROM Person WHERE displayname='Sample Person'),
0, CURRENT_DATE, 0, CURRENT_DATE, 0, CURRENT_DATE
);

INSERT INTO BugActivity (bug, datechanged, person, whatchanged, oldvalue,
newvalue, message)
VALUES (
(SELECT id FROM Bug WHERE name='bob'),
CURRENT_DATE, 1, 'title', 'A silly problem',
'An odd problem', 'Decided problem wasn\'t silly after all'
);

