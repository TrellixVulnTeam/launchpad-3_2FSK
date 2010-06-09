#!/usr/bin/python -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# Update the type of all Feisty requests since these are the only ones we can
# still infer.

import _pythonpath

from canonical.database.sqlbase import cursor, sqlvalues
from canonical.launchpad.database import ShippingRequest
from canonical.launchpad.scripts import execute_zcml_for_scripts
from canonical.lp import initZopeless
from shipit.interfaces.shipit import (
    ShipItDistroSeries, ShipItFlavour, ShippingRequestType)


execute_zcml_for_scripts()
ztm = initZopeless(implicitBegin=False)

ztm.begin()
query = """
    SELECT DISTINCT ShippingRequest.id
    FROM ShippingRequest
    WHERE ShippingRequest.type IS NULL
        AND ShippingRequest.id IN (
            SELECT request FROM RequestedCDs WHERE distrorelease = %s)
    """ % sqlvalues(ShipItDistroSeries.FEISTY)
cur = cursor()
cur.execute(query)
ids = cur.fetchall()
ztm.abort()

for [id] in ids:
    ztm.begin()

    request = ShippingRequest.get(id)
    requested_cds = request.getAllRequestedCDs()
    is_custom = False
    for flavour in ShipItFlavour.items:
        if request.containsCustomQuantitiesOfFlavour(flavour):
            is_custom = True
    if is_custom:
        request.type = ShippingRequestType.CUSTOM
        print "Updated type of request #%d to CUSTOM" % request.id
    else:
        request.type = ShippingRequestType.STANDARD
        print "Updated type of request #%d to STANDARD" % request.id

    ztm.commit()
