# This file modified from Zope3/Makefile
# Licensed under the ZPL, (c) Zope Corporation and contributors.

PYTHON_VERSION=2.4
PYTHON=python${PYTHON_VERSION}
IPYTHON=$(PYTHON) $(shell which ipython)
PYTHONPATH:=$(shell pwd)/lib:$(shell pwd)/lib/mailman:${PYTHONPATH}
VERBOSITY=-vv

TESTFLAGS=-p $(VERBOSITY)
TESTOPTS=

SHHH=${PYTHON} utilities/shhh.py
STARTSCRIPT=runlaunchpad.py
HERE:=$(shell pwd)

LPCONFIG=development
CONFFILE=configs/${LPCONFIG}/launchpad.conf

MINS_TO_SHUTDOWN=15

CODEHOSTING_ROOT=/var/tmp/bazaar.launchpad.dev

XSLTPROC=xsltproc

APPSERVER_ENV = \
  LPCONFIG=${LPCONFIG} \
  PYTHONPATH=$(PYTHONPATH) \
  STORM_CEXTENSIONS=1

# DO NOT ALTER : this should just build by default
default: inplace

schema: build clean_codehosting
	$(MAKE) -C database/schema
	$(PYTHON) ./utilities/make-dummy-hosted-branches
	rm -rf /var/tmp/fatsam

newsampledata:
	$(MAKE) -C database/schema newsampledata

apidoc: compile
	LPCONFIG=$(LPCONFIG) $(PYTHON) ./utilities/create-lp-wadl.py | \
		$(XSLTPROC) ./lib/launchpadlib/wadl-to-refhtml.xsl - \
		> ./lib/canonical/launchpad/apidoc/index.html

check_launchpad_on_merge: build dbfreeze_check check check_sourcecode_dependencies

check_launchpad_storm_on_merge: check_launchpad_on_merge

check_sourcecode_dependencies:
	# Use the check_for_launchpad rule which runs tests over a smaller
	# set of libraries, for performance and reliability reasons.
	$(MAKE) -C sourcecode check_for_launchpad PYTHON=${PYTHON} \
		PYTHON_VERSION=${PYTHON_VERSION} PYTHONPATH=$(PYTHONPATH)

check_loggerhead_on_merge:
	# Loggerhead doesn't depend on anything else in rocketfuel and nothing
	# depends on it (yet).
	make -C sourcecode/loggerhead check PYTHON=${PYTHON} \
		PYTHON_VERSION=${PYTHON_VERSION} PYTHONPATH=$(PYTHONPATH)

dbfreeze_check:
	# Ignore lines starting with P as these are pending merges.
	[ ! -f database-frozen.txt -o \
	  `PYTHONPATH= bzr status -S database/schema/ | \
		grep -v "\(^P\|pending\|security.cfg\|Makefile\)" | wc -l` -eq 0 ]

check_not_a_ui_merge:
	[ ! -f do-not-merge-to-mainline.txt ]

check_merge: check_not_a_ui_merge build check
	# Work around the current idiom of 'make check' getting too long
	# because of hct and related tests. note that this is a short
	# term solution, the long term solution will need to be
	# finer grained testing anyway.
	# Run all tests. test_on_merge.py takes care of setting up the
	# database.
	$(MAKE) -C sourcecode check PYTHON=${PYTHON} \
		PYTHON_VERSION=${PYTHON_VERSION} PYTHONPATH=$(PYTHONPATH)

check_merge_ui: build check
	# Same as check_merge, except we don't need to do check_not_a_ui_merge.
	$(MAKE) -C sourcecode check PYTHON=${PYTHON} \
		PYTHON_VERSION=${PYTHON_VERSION} PYTHONPATH=$(PYTHONPATH)

check_merge_edge: dbfreeze_check check_merge
	# Allow the merge if there are no database updates, including
	# database patches or datamigration scripts (which should live
	# in database/schema/pending. Used for maintaining the
	# edge.lauchpad.net branch.

check: build
	# Run all tests. test_on_merge.py takes care of setting up the
	# database..
	env PYTHONPATH=$(PYTHONPATH) \
	${PYTHON} -t ./test_on_merge.py $(VERBOSITY)

lint:
	@bash ./utilities/lint.sh

lint-verbose:
	@bash ./utilities/lint.sh -v

xxxreport:
	${PYTHON} -t ./utilities/xxxreport.py -f csv -o xxx-report.csv ./

check-configs:
	${PYTHON} utilities/check-configs.py

pagetests: build
	env PYTHONPATH=$(PYTHONPATH) ${PYTHON} test.py test_pages

inplace: build

build: bzr_version_info compile apidoc

compile:
	${SHHH} $(MAKE) -C sourcecode build PYTHON=${PYTHON} \
	    PYTHON_VERSION=${PYTHON_VERSION} LPCONFIG=${LPCONFIG}
	${SHHH} LPCONFIG=${LPCONFIG} PYTHONPATH=$(PYTHONPATH) \
		 $(PYTHON) -t buildmailman.py

runners:
	echo "#!/bin/sh" > bin/runzope;
	echo "exec $(PYTHON) $(STARTSCRIPT) -C $(CONFFILE)" >> bin/runzope;
	chmod +x bin/runzope
	echo "#!/bin/sh" > bin/zopectl;
	echo "$(PYTHON) $(PWD)/src/zdaemon/zdctl.py \
	      -S schema.xml \
	      -C zdaemon.conf -d \$$*" >> bin/zopectl
	chmod +x bin/zopectl 

test_build: build
	$(PYTHON) test.py $(TESTFLAGS) $(TESTOPTS)

test_inplace: inplace
	$(PYTHON) test.py $(TESTFLAGS) $(TESTOPTS)

ftest_build: build
	env PYTHONPATH=$(PYTHONPATH) \
	    $(PYTHON) test.py -f $(TESTFLAGS) $(TESTOPTS)

ftest_inplace: inplace
	env PYTHONPATH=$(PYTHONPATH) \
	    $(PYTHON) test.py -f $(TESTFLAGS) $(TESTOPTS)

run: inplace stop
	rm -f thread*.request
	$(APPSERVER_ENV) $(PYTHON) -t $(STARTSCRIPT) \
		 -r librarian,google-webservice -C $(CONFFILE)

start-gdb: inplace stop bzr_version_info
	rm -f thread*.request
	$(APPSERVER_ENV) nohup gdb -x run.gdb --args $(PYTHON) -t $(STARTSCRIPT) \
		-r librarian,google-webservice -C $(CONFFILE) \
		> ${LPCONFIG}-nohup.out 2>&1 &

run_all: inplace stop sourcecode/launchpad-loggerhead/sourcecode/loggerhead
	rm -f thread*.request
	$(APPSERVER_ENV) $(PYTHON) -t $(STARTSCRIPT) \
		 -r librarian,buildsequencer,authserver,sftp,mailman,codebrowse,google-webservice \
		 -C $(CONFFILE)

pull_branches: bzr_version_info
	# Mirror the hosted branches in the development upload area to the
	# mirrored area.
	$(PYTHON) cronscripts/supermirror-pull.py upload

rewritemap:
	# Build rewrite map that maps friendly branch names to IDs. Necessary
	# for http access to branches and for the branch scanner.
	mkdir -p $(CODEHOSTING_ROOT)/config
	$(PYTHON) cronscripts/supermirror_rewritemap.py $(CODEHOSTING_ROOT)/config/launchpad-lookup.txt

scan_branches: rewritemap
	# Scan branches from the filesystem into the database.
	$(PYTHON) cronscripts/branch-scanner.py

sync_branches: pull_branches scan_branches

bzr_version_info:
	rm -f bzr-version-info.py bzr-version-info.pyc
	if which bzr > /dev/null  && test -x `which bzr`; \
		then PYTHONPATH= bzr version-info --format=python > bzr-version-info.py 2>/dev/null; \
	fi

# Run as a daemon - hack using nohup until we move back to using zdaemon
# properly. We also should really wait until services are running before 
# exiting, as running 'make stop' too soon after running 'make start'
# will not work as expected.
start: inplace stop bzr_version_info
	$(APPSERVER_ENV) nohup $(PYTHON) -t $(STARTSCRIPT) -C $(CONFFILE) \
		 > ${LPCONFIG}-nohup.out 2>&1 &

# Kill launchpad last - other services will probably shutdown with it,
# so killing them after is a race condition.
stop: build
	@ $(APPSERVER_ENV) ${PYTHON} \
	    utilities/killservice.py librarian buildsequencer launchpad mailman

shutdown: scheduleoutage stop
	rm -f +maintenancetime.txt

scheduleoutage:
	echo Scheduling outage in ${MINS_TO_SHUTDOWN} mins
	date --iso-8601=minutes -u -d +${MINS_TO_SHUTDOWN}mins > +maintenancetime.txt
	echo Sleeping ${MINS_TO_SHUTDOWN} mins
	sleep ${MINS_TO_SHUTDOWN}m

harness:
	$(APPSERVER_ENV) $(PYTHON) -i lib/canonical/database/harness.py

iharness:
	$(APPSERVER_ENV) $(IPYTHON) -i lib/canonical/database/harness.py

rebuildfti:
	@echo Rebuilding FTI indexes on launchpad_dev database
	$(PYTHON) database/schema/fti.py -d launchpad_dev --force

debug:
	$(APPSERVER_ENV) \
		 $(PYTHON) -i -c \ "from zope.app import Application;\
		    app = Application('Data.fs', 'site.zcml')()"

clean:
	(cd sourcecode/pygettextpo; make clean)
	find . -type f \( -name '*.o' -o -name '*.so' \
	    -o -name '*.la' -o -name '*.lo' \
	    -o -name '*.py[co]' -o -name '*.dll' \) -exec rm -f {} \;
	rm -rf build
	rm -rf lib/mailman /var/tmp/mailman/* /var/tmp/fatsam.appserver
	rm -rf $(CODEHOSTING_ROOT)

realclean: clean
	rm -f TAGS tags
	$(PYTHON) setup.py clean -a

clean_codehosting:
	rm -rf $(CODEHOSTING_ROOT)
	mkdir -p $(CODEHOSTING_ROOT)/mirrors
	mkdir -p $(CODEHOSTING_ROOT)/push-branches
	mkdir -p $(CODEHOSTING_ROOT)/config
	touch $(CODEHOSTING_ROOT)/config/launchpad-lookup.txt

zcmldocs:
	PYTHONPATH=`pwd`/src:$(PYTHONPATH) $(PYTHON) \
	    ./sourcecode/zope/configuration/stxdocs.py \
	    -f ./src/zope/app/meta.zcml -o ./doc/zcml/namespaces.zope.org

potemplates: launchpad.pot

# Generate launchpad.pot by extracting message ids from the source
launchpad.pot:
	$(PYTHON) sourcecode/zope/utilities/i18nextract.py \
	    -d launchpad -p lib/canonical/launchpad \
	    -o locales

sourcecode/launchpad-loggerhead/sourcecode/loggerhead:
	ln -s ../../loggerhead sourcecode/launchpad-loggerhead/sourcecode/loggerhead

install: reload-apache

/etc/apache2/sites-available/local-launchpad: configs/development/local-launchpad-apache
	cp configs/development/local-launchpad-apache $@

/etc/apache2/sites-enabled/local-launchpad: /etc/apache2/sites-available/local-launchpad
	a2ensite local-launchpad

reload-apache: /etc/apache2/sites-enabled/local-launchpad
	/etc/init.d/apache2 reload

static:
	$(PYTHON) scripts/make-static.py

TAGS:
	ctags -e -R lib/canonical && ctags --exclude=lib/canonical -a -e -R lib/

tags:
	ctags -R lib

.PHONY: check tags TAGS zcmldocs realclean clean debug stop start run \
		ftest_build ftest_inplace test_build test_inplace pagetests \
		check check_merge schema default launchpad.pot \
		check_launchpad_on_merge check_merge_ui pull rewritemap scan \
		sync_branches check_loggerhead_on_merge reload-apache \
		check_launchpad_storm_on_merge

