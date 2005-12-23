#!/usr/bin/env python
"""
Add full text indexes to the launchpad database
"""

import _pythonpath

import sys, os.path, popen2, re
from optparse import OptionParser
import psycopg
from canonical.database.sqlbase import connect
from canonical import lp
from canonical.config import config
from canonical.launchpad.scripts import logger, logger_options, db_options

# Defines parser and locale to use.
DEFAULT_CONFIG = 'default'

PGSQL_BASE = '/usr/share/postgresql'

A, B, C, D = 'ABCD' # tsearch2 ranking constants

# This data structure defines all of our bull text indexes.
# Each tuple in the top level list creates a 'fti' column in the
# specified table.
ALL_FTI = [
    ('bug', [
            ('name', A),
            ('title', B),
            ('summary', C),
            ('description', D),
            ]),

    ('bugtask', [
            ('targetnamecache', B),
            ('statusexplanation', C),
            ]),

    ('binarypackagerelease', [
            ('summary', B),
            ('description', C),
            ]),

    ('cve', [
            ('sequence', A),
            ('description', B),
            ]),

    ('distributionsourcepackagecache', [
            ('name', A),
            ('binpkgnames', B),
            ('binpkgsummaries', C),
            ('binpkgdescriptions', D),
            ]),

    ('distroreleasepackagecache', [
            ('name', A),
            ('summaries', B),
            ('descriptions', C),
            ]),

    ('message', [
            ('subject', B),
            ]),

    ('messagechunk', [
            ('content', C),
            ]),

    ('person', [
            ('name', A),
            ('displayname', B),
            ('givenname', C),
            ('familyname', C),
            ]),

    ('product', [
            ('name', A),
            ('displayname', A),
            ('title', B),
            ('summary', C),
            ('description', D),
            ]),

    ('project', [
            ('name', A),
            ('displayname', A),
            ('title', B),
            ('summary', C),
            ('description', D),
            ]),

    ('shippingrequest', [
            ('recipientdisplayname', A),
            ]),

    ('ticket', [
            ('title', A),
            ('description', B),
            ('whiteboard', B),
            ])
    ]


def quote(s):
    """SQL quoted string"""
    if s is not None:
        return psycopg.QuotedString(s)
    else:
        return 'NULL'


def quote_identifier(identifier):
    """Quote an identifier like a table name or column name"""
    quote_dict = {'\"': '""', "\\": "\\\\"}
    for dkey in quote_dict.keys():
        if identifier.find(dkey) >= 0:
            identifier=quote_dict[dkey].join(identifier.split(dkey))
    return '"%s"' % identifier


def execute(con, sql, results=False, args=None):
    sql = sql.strip()
    log.debug('* %s' % sql)
    cur = con.cursor()
    if args is None:
        cur.execute(sql)
    else:
        cur.execute(sql, args)
    if results:
        return list(cur.fetchall())
    else:
        return None


def fti(con, table, columns, configuration=DEFAULT_CONFIG):
    """Setup full text indexing for a table"""

    index = quote_identifier("%s_fti" % table)
    table = quote_identifier(table)
    # Quote the columns
    columns = [
        (quote_identifier(column), weight) for column, weight in columns
        ]

    # Drop the trigger if it exists
    try:
        execute(con, "DROP TRIGGER tsvectorupdate ON %s" % table)
        con.commit()
    except psycopg.ProgrammingError:
        con.rollback()

    # Drop the fti index if it exists
    try:
        execute(con, "DROP INDEX %s" % index)
        con.commit()
    except psycopg.ProgrammingError:
        con.rollback()

    # Create the 'fti' column if it doesn't already exist
    try:
        execute(con, "SELECT fti FROM %s LIMIT 1" % table)
    except psycopg.ProgrammingError:
        con.rollback()
        execute(con, "ALTER TABLE %s ADD COLUMN fti tsvector" % table)

    # Create the trigger
    columns_and_weights = []
    for column, weight in columns:
        columns_and_weights.extend( (column, weight) )

    sql = """
        CREATE TRIGGER tsvectorupdate BEFORE UPDATE OR INSERT ON %s
        FOR EACH ROW EXECUTE PROCEDURE ftiupdate(%s)
        """ % (table, ','.join(columns_and_weights))
    execute(con, sql)

    # Rebuild the fti column, as the information it contains may be out
    # of date with recent configuration updates.
    execute(con, r"""UPDATE %s SET fti=NULL""" % table)

    # Create the fti index
    execute(con, "CREATE INDEX %s ON %s USING gist(fti)" % (
        index, table
        ))

    con.commit()


def setup(con, configuration=DEFAULT_CONFIG):
    """Setup and install tsearch2 if isn't already"""
    try:
        execute(con, 'SET search_path = ts2, public;')
    except psycopg.ProgrammingError:
        con.rollback()
        execute(con, 'CREATE SCHEMA ts2')
        execute(con, 'SET search_path = ts2, public;')
        con.commit()

    tsearch2_sql_path = get_tsearch2_sql_path(con)

    try:
        execute(con, 'SELECT * from pg_ts_cfg')
        log.debug('tsearch2 already installed. Updating dictionaries.')
        update_dicts(con)
        con.commit()
    except psycopg.ProgrammingError:
        con.rollback()
        log.debug('Installing tsearch2')
        if config.dbhost:
            cmd = 'psql -d %s -h %s -f -' % (config.dbname, config.dbhost)
        else:
            cmd = 'psql -d %s -f -' % (config.dbname, )
        if options.dbuser:
            cmd += ' -U %s' % options.dbuser
        p = popen2.Popen4(cmd)
        c = p.tochild
        print >> c, "SET client_min_messages=ERROR;"
        print >> c, "CREATE SCHEMA ts2;"
        print >> c, open(tsearch2_sql_path).read().replace(
                'public;','ts2, public;'
                )
        if get_pgversion(con).startswith('7.4.'):
            patch_sql_path = os.path.join(
                    os.path.dirname(__file__), 'regprocedure_update.sql'
                    )
            print >> c, open(patch_sql_path).read()
        p.tochild.close()
        rv = p.wait()
        if rv != 0:
            log.fatal('Error executing %s:', cmd)
            log.debug(p.fromchild.read())
            sys.exit(rv)

    # Create ftq helper and its sibling _ftq.
    # ftq(text) returns a tsquery, suitable for use querying the full text
    # indexes. _ftq(text) returns the string that would be parsed by
    # to_tsquery and is used to debug the query we generate.
    shared_func = r'''
        import re

        # Convert to Unicode and lowercase everything
        query = args[0].decode('utf8').lower()
        ## plpy.debug('1 query is %s' % repr(query))

        # Convert &, |, !, : and \ symbols to whitespace since they have
        # special meaning to tsearch2
        query = re.sub(r"[\&\|\!\:\\]+", " ", query)
        ## plpy.debug('2 query is %s' % repr(query))

        # Convert AND, OR and NOT to tsearch2 punctuation
        query = re.sub(r"\band\b", "&", query)
        query = re.sub(r"\bor\b", "|", query)
        query = re.sub(r"\bnot\b", "!", query)
        ## plpy.debug('3 query is %s' % repr(query))

        # Insert & between tokens without an existing boolean operator
        # Whitespace not proceded by (|&! not followed by &|
        query = re.sub(r"(?<![\(\|\&\!\s])\s+(?![\&\|\s])", "&", query)
        ## plpy.debug('4 query is %s' % repr(query))

        # Detect and repair syntax errors - we are lenient because
        # this input is generally from users.

        # Fix unbalanced brackets
        openings = query.count("(")
        closings = query.count(")")
        if openings > closings:
            query = query + " ) "*(openings-closings)
        elif closings > openings:
            query = " ( "*(closings-openings) + query
        ## plpy.debug('5 query is %s' % repr(query))

        # Brackets containing nothing but whitespace and booleans, recursive
        last = ""
        while last != query:
            last = query
            query = re.sub(r"\([\s\&\|\!]*\)", "", query)
        ## plpy.debug('6 query is %s' % repr(query))

        # An & or | following a (
        query = re.sub(r"(?<=\()[\&\|\s]+", "", query)
        ## plpy.debug('7 query is %s' % repr(query))

        # An &, | or ! immediatly before a )
        query = re.sub(r"[\&\|\!\s]*[\&\|\!]+(?=\))", "", query)
        ## plpy.debug('8 query is %s' % repr(query))

        # An &,| or ! followed by another boolean.
        query = re.sub(r"\s*([\&\|\!])\s*[\&\|]+", r"\1", query)
        ## plpy.debug('9 query is %s' % repr(query))

        # Leading & or |
        query = re.sub(r"^[\s\&\|]+", "", query)
        ## plpy.debug('10 query is %s' % repr(query))

        # Trailing &, | or !
        query = re.sub(r"[\&\|\!\s]+$", "", query)
        ## plpy.debug('11 query is %s' % repr(query))

        # If we have nothing but whitespace and tsearch2 operators,
        # return NULL.
        if re.search(r"^[\&\|\!\s\(\)]*$", query) is not None:
            return None

        # Convert back to UTF-8
        query = query.encode('utf8')
        ## plpy.debug('12 query is %s' % repr(query))
        '''
    text_func = shared_func + """
        return query or None
        """
    tsquery_func = shared_func + """
        p = plpy.prepare("SELECT to_tsquery('%s', $1) AS x", ["text"])
        query = plpy.execute(p, [query], 1)[0]["x"]
        return query or None
        """  % configuration
    execute(con, r"""
        CREATE OR REPLACE FUNCTION ts2._ftq(text) RETURNS text AS %s
        LANGUAGE plpythonu IMMUTABLE
        RETURNS NULL ON NULL INPUT
        """ % quote(text_func))
    #print psycopg.QuotedString(text_func)
    execute(con, r"""
        CREATE OR REPLACE FUNCTION ts2.ftq(text) RETURNS tsquery AS %s
        LANGUAGE plpythonu IMMUTABLE
        RETURNS NULL ON NULL INPUT
        """ % quote(tsquery_func))

    execute(con,
            r"COMMENT ON FUNCTION ftq(text) IS '"
            r"Convert a string to a tsearch2 query using the preferred "
            r"configuration. eg. "
            r""""SELECT * FROM Bug WHERE fti @@ ftq(''fatal crash'')". """
            r"The query is lowercased, and multiple words searched using AND.'"
            )
    execute(con,
            r"COMMENT ON FUNCTION ftq(text) IS '"
            r"Convert a string to an unparsed tsearch2 query'"
            )

    # Create our trigger function. The default one that ships with tsearch2
    # doesn't support weighting so we need our own. We remove safety belts
    # since we know we will be calling it correctly.
    execute(con, r"""
        CREATE OR REPLACE FUNCTION ftiupdate() RETURNS trigger AS '
            new = TD["new"]
            args = TD["args"][:]

            # Generate an SQL statement that turns the requested
            # column values into a weighted tsvector
            sql = []
            for i in range(0, len(args), 2):
                sql.append(
                        "setweight(to_tsvector(''default'', "
                        "coalesce($%d, '''')), $%d)" % (i+1,i+2))
                args[i] = new[args[i]]

            sql = "SELECT %s AS fti" % "||".join(sql)

            # Execute and store in the fti column
            plan = plpy.prepare(sql, ["text", "char"] * (len(args)/2))
            new["fti"] = plpy.execute(plan, args, 1)[0]["fti"]

            # Tell PostgreSQL we have modified the data
            return "MODIFY"
        ' LANGUAGE plpythonu
        """)
        
    execute(con,
        r"COMMENT ON FUNCTION ftiupdate() IS 'Trigger function that keeps "
        r"the fti tsvector column up to date.'"
        )

    con.commit()

    # Confirm database locale is valid, and set the 'default' tsearch2
    # configuration to use it.
    r = execute(con, r"""
            SELECT setting FROM pg_settings
            WHERE context='internal' AND name='lc_ctype'
            """, results=True)
    assert len(r) == 1, 'Unable to determine database locale'
    locale = r[0][0]
    assert locale.startswith('en_') or locale in ('C', 'en'), (
            "Non-english database locales are not supported with launchpad. "
            "Fresh initdb required."
            )
    r = locale.split('.',1)
    if len(r) > 1:
        assert r[1].upper() in ("UTF8", "UTF-8"), \
                "Only UTF8 encodings supported. Fresh initdb required."
    else:
        assert len(r) == 1, 'Invalid database locale %s' % repr(locale)

    execute(con, r"""
            UPDATE ts2.pg_ts_cfg SET locale=(
                SELECT setting FROM pg_settings
                WHERE context='internal' AND name='lc_ctype'
                )
            WHERE ts_name='default'
            """)
    

    # Don't bother with this - the setting is not exported with dumps
    # or propogated  when duplicating the database. Only reliable
    # way we can use is setting search_path in postgresql.conf
    #
    # Set the default schema search path so this stuff can be found
    #execute(con, 'ALTER DATABASE %s SET search_path = public,ts2;' % dbname)
    con.commit()


def needs_refresh(con, table, columns):
    '''Return true if the index needs to be rebuilt.

    We know this by looking in our cache to see what the previous
    definitions were, and the --force command line argument
    '''
    current_columns = repr(sorted(columns)) # Convert to a string

    existing = execute(
        con, "SELECT columns FROM FtiCache WHERE tablename=%(table)s",
        results=True, args=vars()
        )
    if len(existing) == 0:
        execute(con, """
            INSERT INTO FtiCache (tablename, columns) VALUES (
                %(table)s, %(current_columns)s
                )
            """, args=vars())
        return True

    if not options.force:
        previous_columns = existing[0][0]
        if repr(columns) == previous_columns:
            return False

    execute(con, """
        UPDATE FtiCache SET columns = %(current_columns)s
        WHERE tablename = %(table)s
        """, args=vars())

    return True


def get_pgversion(con):
    rows = execute(con, r"show server_version", results=True)
    return rows[0][0]


def get_tsearch2_sql_path(con):
    pgversion = get_pgversion(con)
    if pgversion.startswith('8.0.'):
        path = os.path.join(PGSQL_BASE, '8.0', 'contrib', 'tsearch2.sql')
    elif pgversion.startswith('7.4.'):
        path = os.path.join(PGSQL_BASE, '7.4', 'contrib', 'tsearch2.sql')
        if not os.path.exists(path):
            path = os.path.join(PGSQL_BASE, 'contrib', 'tsearch2.sql')
    else:
        raise RuntimeError('Unknown version %s' % pgversion)

    assert os.path.exists(path), '%s does not exist'
    return path


def update_dicts(con):
    '''Fix paths to the stop word lists.
    
    The PostgreSQL 7.4 installation had absolute paths to the stop words
    lists. This path changed with breezy. Update the paths to the
    newer relative paths.
    '''
    execute(con, '''
        UPDATE pg_ts_dict SET dict_initoption='contrib/english.stop'
        WHERE dict_initoption like '/%/english.stop'
        ''')
    execute(con, '''
        UPDATE pg_ts_dict SET dict_initoption='contrib/russian.stop'
        WHERE dict_initoption like '/%/russian.stop'
        ''')


def main():
    con = connect(lp.dbuser)
    setup(con)
    if not options.setup:
        for table, columns in ALL_FTI:
            if needs_refresh(con, table, columns):
                log.info("Rebuilding full text index on %s", table)
                fti(con, table, columns)
            else:
                log.info("No need to rebuild full text index on %s", table)


if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option(
            "-s", "--setup-only", dest="setup",
            action="store_true", default=False,
            help="Only install tsearch2 - don't build the indexes.",
            )
    parser.add_option(
            "-f", "--force", dest="force",
            action="store_true", default=False,
            help="Force a rebuild of all full text indexes.",
            )
    db_options(parser)
    logger_options(parser)

    (options, args) = parser.parse_args()

    log = logger(options)

    main()

