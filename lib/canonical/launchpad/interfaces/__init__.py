# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the GNU
# Affero General Public License version 3 (see the file LICENSE).

"""Interface definitions for bits of Launchpad that don't fit anywhere else.

See also `canonical.launchpad.database` for implementations of these
interfaces.

DEPRECATED: This package is deprecated.  Do not add any new modules to this
package.  Where possible, move things out of this package into better
locations under the 'lp' package.  See the `lp` docstring for more details.
"""

# XXX henninge 2010-11-12: This is needed by the file
# +inbound-email-config.zcml which resides outside of the LP tree and can
# only be safely updated at roll-out time. The import can be removed again
# after the 10.11 roll-out.
from canonical.launchpad.interfaces.mail import IMailHandler

