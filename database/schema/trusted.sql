
/* This is created as a function so the same definition can be used with
    many tables
*/
    
CREATE OR REPLACE FUNCTION valid_name(text) RETURNS boolean AS '
    import re
    name = args[0]
    pat = r"^[a-z0-9][a-z0-9\\+\\.\\-]+$"
    if re.match(pat, name):
        return 1
    return 0
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_name(text)
    IS 'validate a name.

    Names must contain only lowercase letters, numbers, ., & -. They
    must start with an alphanumeric. They are ASCII only. Names are useful 
    for mneumonic identifiers such as nicknames and as URL components.
    This specification is the same as the Debian product naming policy.

    Note that a valid name might be all integers, so there is a possible
    namespace conflict if URL traversal is possible by name as well as id.';


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
    import re
    name = args[0]
    pat = r"^[A-Za-z0-9\\+:\\.\\-\\~]+$"
    if re.match(pat, name):
        return 1
    return 0
' LANGUAGE plpythonu IMMUTABLE RETURNS NULL ON NULL INPUT;

COMMENT ON FUNCTION valid_version(text) IS 'validate a version number

    Note that this is more flexible than the Debian naming policy,
    as it states ''SHOULD'' rather than ''MUST'', and we have already
    imported packages that don''t match it. Note that versions
    may contain both uppercase and lowercase letters so we can''t use them
    in URLs. Also note that both a product name and a version may contain
    hypens, so we cannot join the product name and the version with a hypen
    to form a unique string (we need to use a space or some other character
    disallowed in the product name spec instead';


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

