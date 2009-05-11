#!/usr/bin/python2.4
# Copyright 2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=C0103,W0403

"""Script to export ShipIt orders into csv files."""

import _pythonpath

from zope.component import getUtility

from canonical.config import config
from canonical.database.sqlbase import ISOLATION_LEVEL_READ_COMMITTED
from lp.services.scripts.base import (
    LaunchpadCronScript, LaunchpadScriptFailure)
from canonical.shipit.interfaces.shipit import (
    IShippingRequestSet, ShipItConstants, ShipItDistroSeries,
    ShippingRequestPriority)


class ShipitExports(LaunchpadCronScript):
    usage = '%prog --priority=normal|high'
    def add_my_options(self):
        self.parser.add_option(
            '--priority',
            dest='priority',
            default=None,
            action='store',
            help='Export only requests with the given priority'
            )
        self.parser.add_option(
            '--distroseries',
            dest='distroseries',
            default=None,
            action='store',
            help='Export only requests for CDs of the given distroseries'
            )

    def main(self):
        self.txn.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)
        self.logger.info('Exporting %s priority ShipIt orders'
            % self.options.priority)

        if self.options.priority == 'normal':
            priority = ShippingRequestPriority.NORMAL
        elif self.options.priority == 'high':
            priority = ShippingRequestPriority.HIGH
        else:
            raise LaunchpadScriptFailure('Wrong value for argument --priority: %s'
                % self.options.priority)

        distroseries = ShipItConstants.current_distroseries
        if self.options.distroseries is not None:
            try:
                distroseries = ShipItDistroSeries.items[
                    self.options.distroseries.upper()]
            except KeyError:
                valid_names = ", ".join(
                    series.name for series in ShipItDistroSeries.items)
                raise LaunchpadScriptFailure(
                    'Invalid value for argument --distroseries: %s. Valid '
                    'values are: %s' % (self.options.distroseries, valid_names))

        requestset = getUtility(IShippingRequestSet)
        requestset.exportRequestsToFiles(priority, self.txn, distroseries)

        self.logger.info('Done.')


if __name__ == '__main__':
    script = ShipitExports('shipit-export-orders', dbuser=config.shipit.dbuser)
    script.lock_and_run()

