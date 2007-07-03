# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Helpers for doing natural language phrase search using the
full text index.
"""

__metaclass__ = type

__all__ = ['nl_phrase_search']

import re

from canonical.database.sqlbase import cursor, quote, sqlvalues

# Regular expression to extract terms from the printout of a ts_query
TS_QUERY_TERM_RE = re.compile(r"'([^']+)'")


def nl_term_candidates(phrase):
    """Returns in an array the candidate search terms from phrase.
    Stop words are removed from the phrase and every term is normalized
    according to the full text rules (lowercased and stemmed).

    :phrase: a search phrase
    """
    cur = cursor()
    cur.execute("SELECT ftq(%(phrase)s)" % sqlvalues(phrase=phrase))
    rs = cur.fetchall()
    assert len(rs) == 1, "ftq() returned more than one row"
    terms = rs[0][0]
    if not terms:
        # Only stop words
        return []
    return TS_QUERY_TERM_RE.findall(terms)


def nl_phrase_search(phrase, table, constraints='',
                     extra_constraints_tables=None):
    """Return the tsearch2 query that should be use to do a phrase search.

    This function implement an algorithm similar to the one used by MySQL
    natural language search (as documented at
    http://dev.mysql.com/doc/refman/5.0/en/fulltext-search.html).

    It eliminates stop words from the phrase and normalize each terms
    according to the full text indexation rules (lowercasing and stemming).

    Each term that is present in more than 50% of the candidate rows is also
    eliminated from the query.

    The remaining terms are then ORed together. One should use the rank() or
    rank_cd() function to order the results from running that query. This will
    make rows that use more of the terms and for which the terms are found
    closer in the text at the top of the list, while still returning rows that
    use only some of the terms.

    :phrase: A search phrase.

    :table: This should be the SQLBase class representing the base type.

    :constraints: Additional SQL clause that limits the rows to a
    subset of the table.

    :extra_constraints_tables: A list of additional table names that are
    needed by the constraints clause.

    Caveat: The SQLBase class must define a 'fti' column .
    This is the column that is used for full text searching.
    """

    # Create a temporary table containing the IDs of the rows representing
    # the search space. This is done in order to improve performance with
    # complex extra constraints (like used in some bugs query).
    cur = cursor()
    temp_tablename = '%s_nl_search_candidates' % table._table
    cur.execute('DROP TABLE IF EXISTS %s' % temp_tablename)
    from_tables = [table._table]
    if extra_constraints_tables:
        from_tables.extend(extra_constraints_tables)
    where_clause = ''
    if constraints:
        where_clause = 'WHERE %s' % constraints
    cur.execute(
        '''CREATE TEMPORARY TABLE %s ON COMMIT DROP
        AS SELECT %s.id FROM %s %s''' % (
            temp_tablename, table._table, ', '.join(from_tables),
            where_clause))

    # Total number of possible matching rows.
    cur.execute('SELECT count(*) FROM %s' % temp_tablename)
    total = cur.fetchall()[0][0]

    # Find the possible terms.
    terms = []
    term_candidates = nl_term_candidates(phrase)
    if total == 0:
        return '|'.join(term_candidates)

    # Eliminate terms that are too common to be useful.
    for term in term_candidates:
        replacements = dict(
            tablename=table._table,
            temp_tablename=temp_tablename,
            search=quote(term))
        matches = table.select(
            '''%(tablename)s.id = %(temp_tablename)s.id
            AND %(tablename)s.fti @@ ftq(%(search)s)''' % replacements,
            clauseTables=[temp_tablename]).count()
        if float(matches) / total < 0.5:
            terms.append(term)
    return '|'.join(terms)
