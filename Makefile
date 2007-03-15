# This file modified from Zope3/Makefile
# Licensed under the ZPL, (c) Zope Corporation and contributors.

PYTHON_VERSION=2.4
PYTHON=python${PYTHON_VERSION}
IPYTHON=$(PYTHON) $(shell which ipython)
PYTHONPATH:=$(shell pwd)/lib:${PYTHONPATH}

TESTFLAGS=-p -v
TESTOPTS=

SHHH=${PYTHON} utilities/shhh.py
STARTSCRIPT=runlaunchpad.py
Z3LIBPATH=$(shell pwd)/sourcecode/zope/src
HERE:=$(shell pwd)

LPCONFIG=default
CONFFILE=configs/${LPCONFIG}/launchpad.conf

# DO NOT ALTER : this should just build by default
default: inplace

schema: build
	$(MAKE) -C database/schema

newsampledata:
	$(MAKE) -C database/schema newsampledata

check_launchpad_on_merge: build dbfreeze_check check importdcheck hctcheck
	# Use the check_for_launchpad rule which runs tests over a smaller
	# set of libraries, for performance and reliability reasons.
	$(MAKE) -C sourcecode check_for_launchpad PYTHON=${PYTHON} \
		PYTHON_VERSION=${PYTHON_VERSION} PYTHONPATH=$(PYTHONPATH)

dbfreeze_check:
	[ ! -f database-frozen.txt \
	    -o `PYTHONPATH= bzr status | grep database/schema/ | wc -l` -eq 0 ]

check_not_a_ui_merge:
	[ ! -f do-not-merge-to-mainline.txt ]

check_merge: check_not_a_ui_merge build check importdcheck hctcheck
	# Work around the current idiom of 'make check' getting too long
	# because of hct and related tests. note that this is a short
	# term solution, the long term solution will need to be
	# finer grained testing anyway.
	# Run all tests. test_on_merge.py takes care of setting up the
	# database.
	$(MAKE) -C sourcecode check PYTHON=${PYTHON} \
		PYTHON_VERSION=${PYTHON_VERSION} PYTHONPATH=$(PYTHONPATH)

check_merge_ui: build check importdcheck hctcheck
	# Same as check_merge, except we don't need to do check_not_a_ui_merge.
	$(MAKE) -C sourcecode check PYTHON=${PYTHON} \
		PYTHON_VERSION=${PYTHON_VERSION} PYTHONPATH=$(PYTHONPATH)

check_merge_edge: check_no_dbupdates check_merge
	# Allow the merge if there are no database updates, including
	# database patches or datamigration scripts (which should live
	# in database/schema/pending. Used for maintaining the
	# edge.lauchpad.net branch.

check_no_dbupdates:
	[ `PYTHONPATH= bzr status | grep database/schema/ | wc -l` -eq 0 ]

hctcheck: build
	env PYTHONPATH=$(PYTHONPATH) \
	    ${PYTHON} -t ./test_on_merge.py -vv \
	        --dir hct --dir sourcerer

importdcheck: build
	env PYTHONPATH=$(PYTHONPATH) \
	${PYTHON} -t ./lib/importd/test_all.py "$$TESTFILTER"

check: build
	# Run all tests. test_on_merge.py takes care of setting up the
	# database..
	env PYTHONPATH=$(PYTHONPATH) \
	${PYTHON} -t ./test_on_merge.py -vv

lint:
	@sh ./utilities/lint.sh

#lintmerge:
#	@# Thank Stuart, not me!
#	@baz diff -s rocketfuel@canonical.com/launchpad--devel--0 | \
#		grep -v "^*" | \
#		grep -v "{arch}" | \
#		cut -c4- | \
#		xargs sh ./utilities/lint.sh

pagetests: build
	env PYTHONPATH=$(PYTHONPATH) ${PYTHON} test.py test_pages

inplace: build

build:
	${SHHH} $(MAKE) -C sourcecode build PYTHON=${PYTHON} \
	    PYTHON_VERSION=${PYTHON_VERSION} LPCONFIG=${LPCONFIG}

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

run: inplace stop bzr_version_info
	rm -f thread*.request
	LPCONFIG=${LPCONFIG} PYTHONPATH=$(Z3LIBPATH):$(PYTHONPATH) \
		 $(PYTHON) -t $(STARTSCRIPT) -C $(CONFFILE)

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
	LPCONFIG=${LPCONFIG} PYTHONPATH=$(Z3LIBPATH):$(PYTHONPATH) \
		 nohup $(PYTHON) -t $(STARTSCRIPT) -C $(CONFFILE) \
		 > ${LPCONFIG}-nohup.out 2>&1 &

# Kill launchpad last - other services will probably shutdown with it,
# so killing them after is a race condition.
stop: build
	@ LPCONFIG=${LPCONFIG} ${PYTHON} \
	    utilities/killservice.py librarian buildsequencer launchpad

harness:
	PYTHONPATH=lib $(PYTHON) -i lib/canonical/database/harness.py

iharness:
	PYTHONPATH=lib $(IPYTHON) -i lib/canonical/database/harness.py

rebuildfti:
	@echo Rebuilding FTI indexes on launchpad_dev database
	$(PYTHON) database/schema/fti.py -d launchpad_dev --force

debug:
	LPCONFIG=${LPCONFIG} PYTHONPATH=$(Z3LIBPATH):$(PYTHONPATH) \
		 $(PYTHON) -i -c \ "from zope.app import Application;\
		    app = Application('Data.fs', 'site.zcml')()"

clean:
	(cd sourcecode/pygettextpo; make clean)
	find . -type f \( -name '*.o' -o -name '*.so' \
	    -o -name '*.la' -o -name '*.lo' \
	    -o -name '*.py[co]' -o -name '*.dll' \) -exec rm -f {} \;
	rm -rf build

realclean: clean
	rm -f TAGS tags
	$(PYTHON) setup.py clean -a

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

TAGS:
	ctags -e -R lib

tags:
	ctags -R lib

.PHONY: check tags TAGS zcmldocs realclean clean debug stop start run \
		ftest_build ftest_inplace test_build test_inplace pagetests \
		check importdcheck check_merge schema default launchpad.pot \
		check_launchpad_on_merge hctcheck check_merge_ui

