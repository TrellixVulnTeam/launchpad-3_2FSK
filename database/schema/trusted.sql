-- Copyright 2004-2006 Canonical Ltd.  All rights reserved.

/* This is created as a function so the same definition can be used with
    many tables
*/

CREATE OR REPLACE FUNCTION valid_name(text) RETURNS boolean AS
$$
    import re
    name = args[0]
    pat = r"^[a-z0-9][a-z0-9\\+\\.\\-]*$"
    if re.match(pat, name):
        return 1
    return 0
$$ LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_name(text)
    IS 'validate a name.

    Names must contain only lowercase letters, numbers, ., & -. They
    must start with an alphanumeric. They are ASCII only. Names are useful 
    for mneumonic identifiers such as nicknames and as URL components.
    This specification is the same as the Debian product naming policy.

    Note that a valid name might be all integers, so there is a possible
    namespace conflict if URL traversal is possible by name as well as id.';


CREATE OR REPLACE FUNCTION valid_branch_name(text) RETURNS boolean AS '
    import re
    name = args[0]
    pat = r"^(?i)[a-z0-9][a-z0-9\\+\\.\\-\\@_]+$"
    if re.match(pat, name):
        return 1
    return 0
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_branch_name(text)
    IS 'validate a branch name.

    As per valid_name, except we allow uppercase and @';


CREATE OR REPLACE FUNCTION valid_bug_name(text) RETURNS boolean AS '
    import re
    name = args[0]
    pat = r"^[a-z][a-z0-9\\+\\.\\-]+$"
    if re.match(pat, name):
        return 1
    return 0
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_bug_name(text) IS 'validate a bug name

    As per valid_name, except numeric-only names are not allowed (including
    names that look like floats).';


CREATE OR REPLACE FUNCTION valid_version(text) RETURNS boolean AS '
    raise RuntimeError("Removed")
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;



CREATE OR REPLACE FUNCTION valid_debian_version(text) RETURNS boolean AS '
    import re
    m = re.search("""^(?ix)
        ([0-9]+:)?
        ([0-9a-z][a-z0-9+:.~-]*?)
        (-[a-z0-9+.~]+)?
        $""", args[0])
    if m is None:
        return 0
    epoch, version, revision = m.groups()
    if not epoch:
        # Can''t contain : if no epoch
        if ":" in version:
            return 0
    if not revision:
        # Can''t contain - if no revision
        if "-" in version:
            return 0
    return 1
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_debian_version(text) IS 'validate a version number as per Debian Policy';


CREATE OR REPLACE FUNCTION sane_version(text) RETURNS boolean AS '
    import re
    if re.search("""^(?ix)
        [0-9a-z]
        ( [0-9a-z] | [0-9a-z.-]*[0-9a-z] )*
        $""", args[0]):
        return 1
    return 0
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION sane_version(text) IS 'A sane version number for use by ProductRelease and DistroRelease. We may make it less strict if required, but it would be nice if we can enforce simple version strings because we use them in URLs';


CREATE OR REPLACE FUNCTION valid_cve(text) RETURNS boolean AS '
    import re
    name = args[0]
    pat = r"^(19|20)\\d{2}-\\d{4}$"
    if re.match(pat, name):
        return 1
    return 0
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_cve(text) IS 'validate a common vulnerability number

    As defined on www.cve.mitre.org, minus the CAN- or CVE- prefix.';


CREATE OR REPLACE FUNCTION valid_absolute_url(text) RETURNS boolean AS '
    from urlparse import urlparse
    (scheme, netloc, path, params, query, fragment) = urlparse(args[0])
    if scheme == "sftp":
        return 1
    if not (scheme and netloc):
        return 0
    return 1
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_absolute_url(text) IS 'Ensure the given test is a valid absolute URL, containing both protocol and network location';


CREATE OR REPLACE FUNCTION valid_fingerprint(text) RETURNS boolean AS '
    import re
    if re.match(r"[\\dA-F]{40}", args[0]) is not None:
        return 1
    else:
        return 0
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_fingerprint(text) IS 'Returns true if passed a valid GPG fingerprint. Valid GPG fingerprints are a 40 character long hexadecimal number in uppercase.';


CREATE OR REPLACE FUNCTION valid_keyid(text) RETURNS boolean AS '
    import re
    if re.match(r"[\\dA-F]{8}", args[0]) is not None:
        return 1
    else:
        return 0
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_keyid(text) IS 'Returns true if passed a valid GPG keyid. Valid GPG keyids are an 8 character long hexadecimal number in uppercase (in reality, they are 16 characters long but we are using the \'common\' definition.';


CREATE OR REPLACE FUNCTION valid_regexp(text) RETURNS boolean AS
$$
    import re
    try:
        re.compile(args[0])
    except:
        return False
    else:
        return True
$$ LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_regexp(text)
    IS 'Returns true if the input can be compiled as a regular expression.';


CREATE OR REPLACE FUNCTION sha1(text) RETURNS char(40) AS '
    import sha
    return sha.new(args[0]).hexdigest()
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION sha1(text) IS
    'Return the SHA1 one way cryptographic hash as a string of 40 hex digits';


CREATE OR REPLACE FUNCTION you_are_your_own_member() RETURNS trigger AS '
    BEGIN
        IF NEW.teamowner IS NULL THEN
            INSERT INTO TeamParticipation (person, team)
                VALUES (NEW.id, NEW.id);
        END IF;
        RETURN NULL;
    END;
' LANGUAGE plpgsql;

COMMENT ON FUNCTION you_are_your_own_member() IS
    'Trigger function to ensure that every row added to the Person table gets a corresponding row in the TeamParticipation table, as per the TeamParticipationUsage page on the Launchpad wiki';

SET check_function_bodies=false; -- Handle forward references

CREATE OR REPLACE FUNCTION is_team(integer) returns boolean AS '
    SELECT count(*)>0 FROM Person WHERE id=$1 AND teamowner IS NOT NULL;
' LANGUAGE sql STABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION is_team(integer) IS
    'True if the given id identifies a team in the Person table';


CREATE OR REPLACE FUNCTION is_team(text) returns boolean AS '
    SELECT count(*)>0 FROM Person WHERE name=$1 AND teamowner IS NOT NULL;
' LANGUAGE sql STABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION is_team(text) IS
    'True if the given name identifies a team in the Person table';

/*
CREATE OR REPLACE FUNCTION is_person(integer) returns boolean AS '
    SELECT count(*)>0 FROM Person WHERE id=$1 AND teamowner IS NULL;
' LANGUAGE sql STABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION is_person(integer) IS
    'True if the given id identifies a person in the Person table';
*/

CREATE OR REPLACE FUNCTION is_person(text) returns boolean AS '
    SELECT count(*)>0 FROM Person WHERE name=$1 AND teamowner IS NULL;
' LANGUAGE sql STABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION is_person(text) IS
    'True if the given name identifies a person in the Person table';
    
SET check_function_bodies=true;

CREATE OR REPLACE FUNCTION is_printable_ascii(text) RETURNS boolean AS '
    import re, string
    try:
        text = args[0].decode("ASCII")
    except UnicodeError:
        return False
    if re.search(r"^[%s]*$" % re.escape(string.printable), text) is None:
        return False
    return True
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION is_printable_ascii(text) IS
    'True if the string is pure printable US-ASCII';

CREATE OR REPLACE FUNCTION sleep_for_testing(double precision) RETURNS boolean
AS $$
    import time
    time.sleep(args[0])
    return True
$$ LANGUAGE plpythonu;

COMMENT ON FUNCTION sleep_for_testing(double precision) IS
    'Sleep for the given number of seconds and return True.  This function is intended to be used by tests to trigger timeout conditions.';


CREATE OR REPLACE FUNCTION mv_pillarname_distribution() RETURNS TRIGGER
VOLATILE SECURITY DEFINER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO PillarName (name, distribution)
        VALUES (NEW.name, NEW.id);
    ELSIF NEW.name != OLD.name THEN
        UPDATE PillarName SET name=NEW.name WHERE distribution=NEW.id;
    END IF;
    RETURN NULL; -- Ignored - this is an AFTER trigger
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION mv_pillarname_distribution() IS
    'Trigger maintaining the PillarName table';


CREATE OR REPLACE FUNCTION mv_pillarname_product() RETURNS TRIGGER
VOLATILE SECURITY DEFINER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO PillarName (name, product)
        VALUES (NEW.name, NEW.id);
    ELSIF NEW.name != OLD.name THEN
        UPDATE PillarName SET name=NEW.name WHERE product=NEW.id;
    END IF;
    RETURN NULL; -- Ignored - this is an AFTER trigger
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION mv_pillarname_product() IS
    'Trigger maintaining the PillarName table';


CREATE OR REPLACE FUNCTION mv_pillarname_project() RETURNS TRIGGER
VOLATILE SECURITY DEFINER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO PillarName (name, project)
        VALUES (NEW.name, NEW.id);
    ELSIF NEW.name != OLD.name THEN
        UPDATE PillarName SET name=NEW.name WHERE project=NEW.id;
    END IF;
    RETURN NULL; -- Ignored - this is an AFTER trigger
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION mv_pillarname_project() IS
    'Trigger maintaining the PillarName table';


CREATE OR REPLACE FUNCTION mv_validpersonorteamcache_person() RETURNS TRIGGER
VOLATILE SECURITY DEFINER AS $$
    # This trigger function could be simplified by simply issuing
    # one DELETE followed by one INSERT statement. However, we want to minimize
    # expensive writes so we use this more complex logic.
    PREF = 4 # Constant indicating preferred email address

    if not SD.has_key("delete_plan"):
        param_types = ["int4"]

        SD["delete_plan"] = plpy.prepare("""
            DELETE FROM ValidPersonOrTeamCache WHERE id = $1
            """, param_types)

        SD["maybe_insert_plan"] = plpy.prepare("""
            INSERT INTO ValidPersonOrTeamCache (id)
            SELECT Person.id
            FROM Person
                LEFT OUTER JOIN EmailAddress
                    ON Person.id = EmailAddress.person AND status = %(PREF)d
                LEFT OUTER JOIN ValidPersonOrTeamCache
                    ON Person.id = ValidPersonOrTeamCache.id
            WHERE Person.id = $1
                AND ValidPersonOrTeamCache.id IS NULL
                AND merged IS NULL
                AND (teamowner IS NOT NULL OR (
                    password IS NOT NULL AND EmailAddress.id IS NOT NULL
                    ))
            """ % vars(), param_types)

    new = TD["new"]
    old = TD["old"]

    # We should always have new, as this is not a DELETE trigger
    assert new is not None, 'New is None'

    person_id = new["id"]
    query_params = [person_id] # All the same

    # Short circuit if this is a new person (not team), as it cannot
    # be valid until a status == 4 EmailAddress entry has been created
    # (unless it is a team, in which case it is valid on creation)
    if old is None:
        if new["teamowner"] is not None:
            plpy.execute(SD["maybe_insert_plan"], query_params)
        return

    # Short circuit if there are no relevant changes
    if (new["teamowner"] == old["teamowner"]
        and new["password"] == old["password"]
        and new["merged"] == old["merged"]):
        return

    # This function is only dealing with updates to the Person table.
    # This means we do not have to worry about EmailAddress changes here

    if (new["merged"] is not None
        or (new["teamowner"] is None and new["password"] is None)
        ):
        plpy.execute(SD["delete_plan"], query_params)
    else:
        plpy.execute(SD["maybe_insert_plan"], query_params)
$$ LANGUAGE plpythonu;

COMMENT ON FUNCTION mv_validpersonorteamcache_person() IS 'A trigger for maintaining the ValidPersonOrTeamCache eager materialized view when changes are made to the Person table';


CREATE OR REPLACE FUNCTION mv_validpersonorteamcache_emailaddress()
RETURNS TRIGGER
VOLATILE SECURITY DEFINER AS $$
    # This trigger function keeps the ValidPersonOrTeamCache materialized
    # view in sync when updates are made to the EmailAddress table.
    # Note that if the corresponding person is a team, changes to this table
    # have no effect.
    PREF = 4 # Constant indicating preferred email address

    if not SD.has_key("delete_plan"):
        param_types = ["int4"]

        SD["is_team"] = plpy.prepare("""
            SELECT teamowner IS NOT NULL AS is_team FROM Person WHERE id = $1
            """, param_types)

        SD["delete_plan"] = plpy.prepare("""
            DELETE FROM ValidPersonOrTeamCache WHERE id = $1
            """, param_types)

        SD["insert_plan"] = plpy.prepare("""
            INSERT INTO ValidPersonOrTeamCache (id) VALUES ($1)
            """, param_types)

        SD["maybe_insert_plan"] = plpy.prepare("""
            INSERT INTO ValidPersonOrTeamCache (id)
            SELECT Person.id
            FROM Person
                JOIN EmailAddress ON Person.id = EmailAddress.person
                LEFT OUTER JOIN ValidPersonOrTeamCache
                    ON Person.id = ValidPersonOrTeamCache.id
            WHERE Person.id = $1
                AND ValidPersonOrTeamCache.id IS NULL
                AND status = %(PREF)d
                AND merged IS NULL
                AND password IS NOT NULL
            """ % vars(), param_types)

    def is_team(person_id):
        """Return true if person_id corresponds to a team"""
        if person_id is None:
            return False
        return plpy.execute(SD["is_team"], [person_id], 1)[0]["is_team"]

    class NoneDict:
        def __getitem__(self, key):
            return None

    old = TD["old"] or NoneDict()
    new = TD["new"] or NoneDict()

    #plpy.info("old.id     == %s" % old["id"])
    #plpy.info("old.person == %s" % old["person"])
    #plpy.info("old.status == %s" % old["status"])
    #plpy.info("new.id     == %s" % new["id"])
    #plpy.info("new.person == %s" % new["person"])
    #plpy.info("new.status == %s" % new["status"])

    # Short circuit if neither person nor status has changed
    if old["person"] == new["person"] and old["status"] == new["status"]:
        return

    # Short circuit if we are not mucking around with preferred email
    # addresses
    if old["status"] != PREF and new["status"] != PREF:
        return

    # Note that we have a constraint ensuring that there is only one
    # status == PREF email address per person at any point in time.
    # This simplifies our logic, as we know that if old.status == PREF,
    # old.person does not have any other preferred email addresses.
    # Also if new.status == PREF, we know new.person previously did not
    # have a preferred email address.

    if old["person"] != new["person"]:
        if old["status"] == PREF and not is_team(old["person"]):
            # old.person is no longer valid, unless they are a team
            plpy.execute(SD["delete_plan"], [old["person"]])
        if new["status"] == PREF and not is_team(new["person"]):
            # new["person"] is now valid, or unchanged if they are a team
            plpy.execute(SD["insert_plan"], [new["person"]])

    elif old["status"] == PREF and not is_team(old["person"]):
        # No longer valid, or unchanged if they are a team
        plpy.execute(SD["delete_plan"], [old["person"]])

    elif new["status"] == PREF and not is_team(new["person"]):
        # May now be valid, or unchanged if they are a team.
        plpy.execute(SD["maybe_insert_plan"], [new["person"]])

$$ LANGUAGE plpythonu;

COMMENT ON FUNCTION mv_validpersonorteamcache_emailaddress() IS 'A trigger for maintaining the ValidPersonOrTeamCache eager materialized view when changes are made to the EmailAddress table';

CREATE OR REPLACE FUNCTION person_sort_key(displayname text, name text)
RETURNS text AS
$$
    # NB: If this implementation is changed, the person_sort_idx needs to be
    # rebuilt along with any other indexes using it.
    import re

    try:
        strip_re = SD["strip_re"]
    except KeyError:
        strip_re = re.compile("(?:[^\w\s]|[\d_])", re.U)
        SD["strip_re"] = strip_re

    displayname, name = args

    # Strip noise out of displayname. We do not have to bother with
    # name, as we know it is just plain ascii.
    displayname = strip_re.sub('', displayname.decode('UTF-8').lower())
    return ("%s, %s" % (displayname.strip(), name)).encode('UTF-8')
$$ LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION person_sort_key(text,text) IS 'Return a string suitable for sorting people on, generated by stripping noise out of displayname and concatenating name';


CREATE OR REPLACE FUNCTION debversion_sort_key(version text)
RETURNS text AS
$$
    # If this method is altered, then any functional indexes using it
    # need to be rebuilt.
    import re

    VERRE = re.compile("(?:([0-9]+):)?(.+?)(?:-([^-]+))?$")

    MAP = "0123456789ABCDEFGHIJKLMNOPQRSTUV"

    epoch, version, release = VERRE.match(args[0]).groups()
    key = []
    for part, part_weight in ((epoch, 3000), (version, 2000), (release, 1000)):
        if not part:
            continue
        i = 0
        l = len(part)
        while i != l:
            c = part[i]
            if c.isdigit():
                key.append(part_weight)
                j = i
                while i != l and part[i].isdigit(): i += 1
                key.append(part_weight+int(part[j:i] or "0"))
            elif c == "~":
                key.append(0)
                i += 1
            elif c.isalpha():
                key.append(part_weight+ord(c))
                i += 1
            else:
                key.append(part_weight+256+ord(c))
                i += 1
        if not key or key[-1] != part_weight:
            key.append(part_weight)
            key.append(part_weight)
    key.append(1)

    # Encode our key and return it
    #
    result = []
    for value in key:
        if not value:
            result.append("000")
        else:
            element = []
            while value:
                element.insert(0, MAP[value & 0x1F])
                value >>= 5
            element_len = len(element)
            if element_len < 3:
                element.insert(0, "0"*(3-element_len))
            elif element_len == 3:
                pass
            elif element_len < 35:
                element.insert(0, MAP[element_len-4])
                element.insert(0, "X")
            elif element_len < 1027:
                element.insert(0, MAP[(element_len-4) & 0x1F])
                element.insert(0, MAP[(element_len-4) & 0x3E0])
                element.insert(0, "Y")
            else:
                raise ValueError("Number too large")
            result.extend(element)
    return "".join(result)
$$ LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION debversion_sort_key(text) IS 'Return a string suitable for sorting debian version strings on';

