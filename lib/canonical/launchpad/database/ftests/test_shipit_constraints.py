# Copyright 2006 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import unittest
import psycopg

from canonical.launchpad.ftests.harness import LaunchpadFunctionalTestCase

class ShipitConstraintsTestCase(LaunchpadFunctionalTestCase):
    dbuser = 'testadmin'

    def shipped(self, cur, id):
        cur.execute("""
            SELECT shipped FROM ShippingRequest WHERE id=%(id)s
            """, vars()
            )
        return cur.fetchone()[0]

    def insert(self, cur, owner='stub'):
        cur.execute("""
            INSERT INTO ShippingRequest (
                recipient, recipientdisplayname, addressline1, city,
                country)
            VALUES (
                (SELECT id FROM Person WHERE name=%(owner)s),
                'whatever', 'whatever', 'whatever', 66
                )
            """, vars())
        cur.execute("SELECT currval('shippingrequest_id_seq')")
        return cur.fetchone()[0]

    def testDupeAdminRequests(self):
        # Duplicate shipments are ignored if the recipient is shipit-admins
        cur = self.connect().cursor()
        for i in range(0, 3):
            self.insert(cur, 'shipit-admins')

    def testDupes(self):
        # Only one uncancelled, possibly approved unshipped order
        # per user.
        con = self.connect()
        cur = con.cursor()

        # Clear out any existing requests for user stub
        cur.execute("""
            DELETE FROM RequestedCDs USING ShippingRequest, Person
            WHERE recipient = Person.id and Person.name = 'stub'
                AND RequestedCDs.request = ShippingRequest.id
            """)
        cur.execute("""
            DELETE FROM ShippingRequest USING Person
            WHERE recipient = Person.id and Person.name = 'stub'
            """)

        # Create some disallowed orders
        for i in range(0, 3):
            disallowed_id = self.insert(cur)
            cur.execute("""
                UPDATE ShippingRequest SET approved=FALSE
                WHERE id = %(disallowed_id)s
                """, vars())

        # Create some cancelled orders
        for i in range(0, 3):
            cancelled_id = self.insert(cur)
            cur.execute("""
                UPDATE ShippingRequest SET cancelled=TRUE
                WHERE id = %(cancelled_id)s
                """, vars())

        # Try to create two orders, neither approved. The second should fail.
        cur.execute("SAVEPOINT attempt1")
        self.insert(cur)
        self.failUnlessRaises(psycopg.Error, self.insert, cur)
        cur.execute("ROLLBACK TO SAVEPOINT attempt1")

        # Try to create two orders, the first explicitly approved. The
        # second should still fail.
        cur.execute("SAVEPOINT attempt2")
        req1_id = self.insert(cur)
        cur.execute("""
            UPDATE ShippingRequest SET approved=TRUE, whoapproved=1
            WHERE id = %(req1_id)s
            """, vars())
        self.failUnlessRaises(psycopg.Error, self.insert, cur)
        cur.execute("ROLLBACK TO SAVEPOINT attempt2")

    def testShippedFlag(self):
        # The shipped flag on the ShippingRequest table is maintained by
        # triggers.
        cur = self.connect().cursor()
        shippingrequest_id = self.insert(cur, 'shipit-admins')
        shipped = self.shipped(cur, shippingrequest_id)
        self.failUnlessEqual(shipped, False)

        # Adding a Shipment record will set ShippingRequest.shipped to True
        cur.execute("""
            INSERT INTO Shipment (
                logintoken, shippingrun, shippingservice, request
                )
            VALUES (
                'whatever', 1, 1, %(shippingrequest_id)s
                )
            """, vars())
        shipped = self.shipped(cur, shippingrequest_id)
        self.failUnlessEqual(shipped, True)

        # Changing a Shipment record also works
        cur.execute("""
            UPDATE Shipment SET request=1
            WHERE request = %(shippingrequest_id)s
            """, vars())
        self.failUnlessEqual(self.shipped(cur, 1), True)
        self.failUnlessEqual(self.shipped(cur, shippingrequest_id), False)

        # As does deleting a Shipment record
        cur.execute("DELETE FROM Shipment WHERE request=1")
        self.failUnlessEqual(self.shipped(cur, 1), False)


def test_suite():
    return unittest.makeSuite(ShipitConstraintsTestCase)

