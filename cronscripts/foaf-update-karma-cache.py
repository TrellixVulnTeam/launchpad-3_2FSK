#!/usr/bin/env python
# Copyright 2005-2007 Canonical Ltd.  All rights reserved.

import _pythonpath

from zope.component import getUtility

from canonical.config import config
from canonical.lp import AUTOCOMMIT_ISOLATION
from canonical.launchpad.interfaces import IKarmaCacheManager, NotFoundError
from canonical.launchpad.scripts.base import LaunchpadScript


class KarmaCacheUpdater(LaunchpadScript):
    def main(self):
        """Update the KarmaCache table for all valid Launchpad users.

        For each Launchpad user with a preferred email address, calculate his
        karmavalue for each category of actions we have and update his entry
        in the KarmaCache table. If a user doesn't have an entry for that
        category in KarmaCache a new one will be created.
        """
        self.logger.info("Updating Launchpad karma caches")

        # We use the autocommit transaction isolation level to minimize
        # contention. It also allows us to not bother explicitly calling
        # COMMIT all the time. However, if we interrupt this script mid-run
        # it will need to be re-run as the data will be inconsistent (only
        # part of the caches will have been recalculated).
        self.txn.set_isolation_level(AUTOCOMMIT_ISOLATION)

        self.cur = self.txn.conn().cursor()
        self.karmacachemanager = getUtility(IKarmaCacheManager)

        # This method ordering needs to be preserved. In particular,
        # C_add_summed_totals method is called last because we don't want to
        # include the values added in our calculation in A_update_karmacache.
        self.A_update_karmacache()
        self.B_update_karmatotalcache()
        self.C_add_karmacache_sums()

        self.logger.info("Finished updating Launchpad karma caches")

    def A_update_karmacache(self):
        self.logger.info("Step A: Calculating individual KarmaCache entries")

        # Calculate everyones karma. Karma degrades each day, becoming
        # worthless after karma_expires_after. This query produces odd results
        # when datecreated is in the future, but there is really no point
        # adding the extra WHEN clause.
        karma_expires_after = '1 year'
        self.cur.execute("""
            SELECT person, category, product, distribution, Product.project,
                ROUND(SUM(
                CASE WHEN karma.datecreated + %s::interval
                    <= CURRENT_TIMESTAMP AT TIME ZONE 'UTC' THEN 0
                ELSE points * (1 - extract(
                    EPOCH FROM CURRENT_TIMESTAMP AT TIME ZONE 'UTC' -
                    karma.datecreated
                    ) / extract(EPOCH FROM %s::interval))
                END
                ))
            FROM Karma
            JOIN KarmaAction ON action = KarmaAction.id
            LEFT JOIN Product ON product = Product.id
            GROUP BY person, category, product, distribution, Product.project
            """, (karma_expires_after, karma_expires_after))

        # Suck into RAM to avoid tieing up resources on the DB.
        results = list(self.cur.fetchall())
        self.logger.debug("Got %d (person, category) scores", len(results))

        # Note that we don't need to commit each iteration because we are
        # running in autocommit mode.
        scaling = self.calculate_scaling(results)
        for entry in results:
            self.update_one_karma_cache_entry(entry, scaling)

        # Delete the entries we're going to replace.
        self.cur.execute("DELETE FROM KarmaCache WHERE category IS NULL")
        self.cur.execute("""
            DELETE FROM KarmaCache
             WHERE project IS NOT NULL AND product IS NULL""")

        # Don't allow our table to bloat with inactive users
        self.cur.execute("DELETE FROM KarmaCache WHERE karmavalue <= 0")

        # VACUUM KarmaCache since we have just touched every record in it
        self.cur.execute("""VACUUM KarmaCache""")

    def B_update_karmatotalcache(self):
        self.logger.info("Step B: Rebuilding KarmaTotalCache")
        # Trash old records
        self.cur.execute("""
            DELETE FROM KarmaTotalCache
            WHERE person NOT IN (SELECT person FROM KarmaCache)
            """)
        # Update existing records
        self.cur.execute("""
            UPDATE KarmaTotalCache SET karma_total=sum_karmavalue
            FROM (
                SELECT person AS sum_person, SUM(karmavalue) AS sum_karmavalue
                FROM KarmaCache
                GROUP BY person
                ) AS sums
            WHERE KarmaTotalCache.person = sum_person
            """)

        # VACUUM KarmaTotalCache since we have just touched every row in it.
        self.cur.execute("""VACUUM KarmaTotalCache""")

        # Insert new records into the KarmaTotalCache table. 
        
        # XXX: If deadlocks ever become a problem, first LOCK the
        # corresponding rows in the Person table so the bulk insert cannot
        # fail. We don't bother at the moment as this would involve granting
        # UPDATE rights on the Person table to the karmacacheupdater user.
        ## cur.execute("BEGIN")
        ## cur.execute("""
        ##     SELECT * FROM Person
        ##     WHERE id NOT IN (SELECT person FROM KarmaTotalCache)
        ##     FOR UPDATE
        ##     """)

        self.cur.execute("""
            INSERT INTO KarmaTotalCache (person, karma_total)
            SELECT person, SUM(karmavalue) FROM KarmaCache
            WHERE person NOT IN (SELECT person FROM KarmaTotalCache)
            GROUP BY person
            """)

        ## self.cur.execute("COMMIT")

    def C_add_karmacache_sums(self):
        self.logger.info("Step C: Calculating KarmaCache sums")
        # We must issue some SUM queries to insert the karma totals for: 
        # - All actions of a person on a given product
        # - All actions of a person on a given distribution
        # - All actions of a person on a given project
        # - All actions with a specific category of a person on a given project

        # - All actions of a person on a given product
        self.cur.execute("""
            INSERT INTO KarmaCache 
                (person, category, karmavalue, product, distribution,
                 sourcepackagename, project)
            SELECT person, NULL, SUM(karmavalue), product, NULL, NULL, NULL
            FROM KarmaCache
            WHERE product IS NOT NULL
            GROUP BY person, product
            """)

        # - All actions of a person on a given distribution
        self.cur.execute("""
            INSERT INTO KarmaCache 
                (person, category, karmavalue, product, distribution,
                 sourcepackagename, project)
            SELECT person, NULL, SUM(karmavalue), NULL, distribution, NULL, NULL
            FROM KarmaCache
            WHERE distribution IS NOT NULL
            GROUP BY person, distribution
            """)

        # - All actions of a person on a given project
        self.cur.execute("""
            INSERT INTO KarmaCache 
                (person, category, karmavalue, product, distribution,
                 sourcepackagename, project)
            SELECT person, NULL, SUM(karmavalue), NULL, NULL, NULL, project
            FROM KarmaCache
            WHERE project IS NOT NULL
            GROUP BY person, project
            """)

        # - All actions with a specific category of a person on a given project
        # XXX: This has to be the latest step; otherwise the rows inserted here
        # will be included in the calculation of the overall karma of a person on
        # a given project.
        self.cur.execute("""
            INSERT INTO KarmaCache 
                (person, category, karmavalue, product, distribution,
                 sourcepackagename, project)
            SELECT person, category, SUM(karmavalue), NULL, NULL, NULL, project
            FROM KarmaCache
            WHERE project IS NOT NULL
                AND category IS NOT NULL
            GROUP BY person, category, project
            """)

    def calculate_scaling(self, results):
        """Return a dict of scaling factors keyed on category ID"""

        # Get a list of categories, which we will need shortly.
        categories = {}
        self.cur.execute("SELECT id, name from KarmaCategory")
        for id, name in self.cur.fetchall():
            categories[id] = name

        # Calculate normalization factor for each category. We currently have
        # category bloat, where translators dominate the top karma rankings.
        # By calculating a scaling factor automatically, this slant will be
        # removed even as more events are added or scoring tweaked.
        points_per_category = {}
        for dummy, category, dummy, dummy, dummy, points in results:
            if category not in points_per_category:
                points_per_category[category] = 0
            points_per_category[category] += points
        largest_total = max(points_per_category.values())

        scaling = {}
        for category, points in points_per_category.items():
            if points == 0:
                scaling[category] = 1
            else:
                scaling[category] = float(largest_total) / float(points)
            self.logger.debug('Scaling %s by a factor of %0.4f' % (
                categories[category], scaling[category]))
            max_scaling = config.karmacacheupdater.max_scaling
            if scaling[category] > max_scaling:
                scaling[category] = max_scaling
                self.logger.debug('Reducing %s scaling to %d to avoid spikes' 
                    % (categories[category], max_scaling))
        return scaling
    
    def update_one_karma_cache_entry(self, entry, scaling):
        """Updates an individual (non-summed) KarmaCache entry.

        KarmaCache has individual entries, and then it has the summed entries
        that correspond to overall contributions across all categories. Look
        at C_add_summed_totals to see how the summed entries are generated.
        """
        (person_id, category_id, product_id, distribution_id,
                project_id, points) = entry
        points *= scaling[category_id] # Scaled. wow.
        self.logger.debug(
            "Setting person_id=%d, category_id=%d, points=%d" 
                % (person_id, category_id, points))

        points = int(points)
        context = {'product_id': product_id,
                   'project_id': project_id,
                   'distribution_id': distribution_id}

        try:
            self.karmacachemanager.updateKarmaValue(
                points, person_id, category_id, **context)
            self.logger.debug("Updated karmacache for person=%s, "
                      "points=%s, category=%s, context=%s"
                      % (person_id, points, category_id, context))
        except NotFoundError:
            # Row didn't exist; do an insert.
            self.karmacachemanager.new(
                points, person_id, category_id, **context)
            self.logger.debug("Created karmacache for person=%s, "
                      "points=%s, category=%s, context=%s"
                      % (person_id, points, category_id, context))


if __name__ == '__main__':
    script = KarmaCacheUpdater('karma-update', 
        dbuser=config.karmacacheupdater.dbuser)
    script.lock_and_run(implicit_begin=True)

