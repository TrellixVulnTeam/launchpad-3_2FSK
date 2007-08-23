#!/bin/sh

# This script runs the mirror prober scripts as the
# launchpad user every two hours. Typically the output
# will be sent to an email address for inspection.

# Only run this script on forster
THISHOST=`uname -n`
if [ "forster" != "$THISHOST" ]
then
        echo "This script must be run on forster."
        exit 1
fi

# Only run this as the launchpad user
USER=`whoami`
if [ "launchpad" != "$USER" ]
then
        echo "Must be launchpad user to run this script."
        exit 1
fi


export LPCONFIG=production

LOCK=/var/lock/launchpad_mirror_prober.lock
lockfile -r0 -l 259200 $LOCK
if [ $? -ne 0 ]; then
    echo Unable to grab $LOCK lock - aborting
    ps fuxwww
    exit 1
fi

cd /srv/launchpad.net/production/launchpad/cronscripts

echo '== Distribution mirror prober (archive)' `date` ==
python distributionmirror-prober.py --content-type=archive --no-owner-notification --max-mirrors=50

echo '== Distribution mirror prober (cdimage)' `date` ==
python distributionmirror-prober.py --content-type=cdimage --no-owner-notification --max-mirrors=50

rm -f $LOCK

