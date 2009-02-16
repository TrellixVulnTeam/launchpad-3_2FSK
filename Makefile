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

BZR_VERSION_INFO = bzr-version-info.py

XSLTPROC=xsltproc
WADL_FILE = lib/canonical/launchpad/apidoc/wadl-$(LPCONFIG).xml
WADL_XSL = lib/launchpadlib/wadl-to-refhtml.xsl
API_INDEX = lib/canonical/launchpad/apidoc/index.html

APPSERVER_ENV = \
  LPCONFIG=${LPCONFIG} \
  PYTHONPATH=$(PYTHONPATH) \
  STORM_CEXTENSIONS=1

EXTRA_JS_FILES=lib/canonical/launchpad/icing/MochiKit.js \
				$(shell $(HERE)/utilities/yui-deps.py) \
				lib/canonical/launchpad/icing/lazr/build/lazr.js

# DO NOT ALTER : this should just build by default
default: inplace

schema: build clean_codehosting
	$(MAKE) -C database/schema
	$(PYTHON) ./utilities/make-dummy-hosted-branches
	$(RM) -r /var/tmp/fatsam

newsampledata:
	$(MAKE) -C database/schema newsampledata

$(WADL_FILE): $(BZR_VERSION_INFO)
	LPCONFIG=$(LPCONFIG) $(PYTHON) ./utilities/create-lp-wadl.py > $@

$(API_INDEX): $(WADL_FILE) $(WADL_XSL)
	$(XSLTPROC) $(WADL_XSL) $(WADL_FILE) > $@

apidoc: compile $(API_INDEX)

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

build: $(BZR_VERSION_INFO) compile apidoc

compile:
	${SHHH} $(MAKE) -C sourcecode build PYTHON=${PYTHON} \
	    PYTHON_VERSION=${PYTHON_VERSION} LPCONFIG=${LPCONFIG}
	${SHHH} LPCONFIG=${LPCONFIG} PYTHONPATH=$(PYTHONPATH) \
		 $(PYTHON) -t buildmailman.py
	${SHHH} sourcecode/lazr-js/tools/build.py \
		-n launchpad -s lib/canonical/launchpad/javascript \
		-b lib/canonical/launchpad/icing/build $(EXTRA_JS_FILES)

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
	$(RM) thread*.request
	$(APPSERVER_ENV) $(PYTHON) -t $(STARTSCRIPT) \
		 -r librarian,google-webservice -C $(CONFFILE)

start-gdb: inplace stop support_files
	$(RM) thread*.request
	$(APPSERVER_ENV) nohup gdb -x run.gdb --args $(PYTHON) -t $(STARTSCRIPT) \
		-r librarian,google-webservice -C $(CONFFILE) \
		> ${LPCONFIG}-nohup.out 2>&1 &

run_all: inplace stop
	$(RM) thread*.request
	$(APPSERVER_ENV) $(PYTHON) -t $(STARTSCRIPT) \
		 -r librarian,buildsequencer,sftp,mailman,codebrowse,google-webservice \
		 -C $(CONFFILE)

run_codebrowse: build
	BZR_PLUGIN_PATH=bzrplugins PYTHONPATH=lib $(PYTHON) sourcecode/launchpad-loggerhead/start-loggerhead.py -f

start_codebrowse: build
	BZR_PLUGIN_PATH=$(shell pwd)/bzrplugins PYTHONPATH=lib $(PYTHON) sourcecode/launchpad-loggerhead/start-loggerhead.py

stop_codebrowse:
	PYTHONPATH=lib $(PYTHON) sourcecode/launchpad-loggerhead/stop-loggerhead.py

pull_branches: support_files
	# Mirror the hosted branches in the development upload area to the
	# mirrored area.
	$(PYTHON) cronscripts/supermirror-pull.py upload

scan_branches:
	# Scan branches from the filesystem into the database.
	$(PYTHON) cronscripts/branch-scanner.py

sync_branches: pull_branches scan_branches

$(BZR_VERSION_INFO):
	scripts/update-bzr-version-info.sh

support_files: $(WADL_FILE) $(BZR_VERSION_INFO)

# Run as a daemon - hack using nohup until we move back to using zdaemon
# properly. We also should really wait until services are running before
# exiting, as running 'make stop' too soon after running 'make start'
# will not work as expected.
start: inplace stop support_files
	$(APPSERVER_ENV) nohup $(PYTHON) -t $(STARTSCRIPT) -C $(CONFFILE) \
		 > ${LPCONFIG}-nohup.out 2>&1 &

# This is a stripped down version of the "start" target for use on
# production servers - removes running 'make build' because we already
# run this as part of our initscripts, so not needed here. Likewise we
# don't want to run 'make stop' because it takes unnecessary time
# even if the service is already stopped, and bzr_version_info is not
# needed either because it's run as part of 'make build'.
initscript-start:
	$(APPSERVER_ENV) nohup $(PYTHON) -t $(STARTSCRIPT) -C $(CONFFILE) \
		 > ${LPCONFIG}-nohup.out 2>&1 &

# Kill launchpad last - other services will probably shutdown with it,
# so killing them after is a race condition.
stop: build
	@ $(APPSERVER_ENV) ${PYTHON} \
	    utilities/killservice.py librarian buildsequencer launchpad mailman

shutdown: scheduleoutage stop
	$(RM) +maintenancetime.txt

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
	$(MAKE) -C sourcecode/pygettextpo clean
	find . -type f \( \
	    -name '*.o' -o -name '*.so' -o -name '*.la' -o \
	    -name '*.lo' -o -name '*.py[co]' -o -name '*.dll' \) \
	    -print0 | xargs -r0 $(RM)
	$(RM) -r build
	$(RM) thread*.request
	$(RM) -r lib/mailman /var/tmp/mailman/* /var/tmp/fatsam.appserver
	$(RM) -rf lib/canonical/launchpad/icing/build/*
	$(RM) -r $(CODEHOSTING_ROOT)
	$(RM) $(WADL_FILE) $(API_INDEX)
	$(RM) $(BZR_VERSION_INFO)

realclean: clean
	$(RM) TAGS tags

clean_codehosting:
	$(RM) -r $(CODEHOSTING_ROOT)
	mkdir -p $(CODEHOSTING_ROOT)/mirrors
	mkdir -p $(CODEHOSTING_ROOT)/push-branches
	mkdir -p $(CODEHOSTING_ROOT)/config
	touch $(CODEHOSTING_ROOT)/config/launchpad-lookup.txt

zcmldocs:
	mkdir -p doc/zcml/namespaces.zope.org
	PYTHONPATH=$(shell pwd)/src:$(PYTHONPATH) $(PYTHON) \
	    ./sourcecode/zope/src/zope/configuration/stxdocs.py \
	    -f sourcecode/zope/src/zope/app/zcmlfiles/meta.zcml \
	    -o doc/zcml/namespaces.zope.org

potemplates: launchpad.pot

# Generate launchpad.pot by extracting message ids from the source
launchpad.pot:
	$(PYTHON) sourcecode/zope/utilities/i18nextract.py \
	    -d launchpad -p lib/canonical/launchpad \
	    -o locales

install: reload-apache

copy-certificates:
	mkdir -p /etc/apache2/ssl
	cp configs/development/launchpad.crt /etc/apache2/ssl/
	cp configs/development/launchpad.key /etc/apache2/ssl/

copy-apache-config:
	# We insert the absolute path to the branch-rewrite script
	# into the Apache config as we copy the file into position.
	sed -e 's,%BRANCH_REWRITE%,$(shell pwd)/scripts/branch-rewrite.py,' configs/development/local-launchpad-apache > /etc/apache2/sites-available/local-launchpad

enable-apache-launchpad: copy-apache-config copy-certificates
	a2ensite local-launchpad

reload-apache: enable-apache-launchpad
	/etc/init.d/apache2 reload

static:
	$(PYTHON) scripts/make-static.py

TAGS:
	ctags -e -R --exclude='*yui/2.6.0*' --exclude='*-min.js' lib/canonical && \
		ctags -e --exclude=lib/canonical -a -R lib/

tags:
	ctags -R --exclude='*yui/2.6.0*' --exclude='*-min.js' lib/canonical && \
		ctags --exclude=lib/canonical -a -R lib/

.PHONY: apidoc check tags TAGS zcmldocs realclean clean debug stop	\
	start run ftest_build ftest_inplace test_build test_inplace	\
	pagetests check check_merge schema default launchpad.pot	\
	check_launchpad_on_merge check_merge_ui pull scan		\
	sync_branches check_loggerhead_on_merge reload-apache		\
	check_launchpad_storm_on_merge
