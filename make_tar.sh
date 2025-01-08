#!/bin/bash
# This script creates a tree of symlinks to the various pieces
# of nas_qstat following the normal bin, lib, man structure and
# then builds a tar file with the real files, rather than symlinks.
# Resultant tar can then be extracted in whatever directory makes
# sense (e.g., /usr/local/, /opt/pbs, /opt/pbs/unsupported)

set -e
dir=$(mktemp -d -p . bldXXXXXX)
cd $dir
chmod 755 .
mkdir -p -m 755 bin lib lib/site man man/man1 man/man3 man/man8
ln -s ../../nas_pbsfs bin/
ln -s ../../nas_qstat bin/
ln -s ../../nas_rstat bin/
ln -s ../../nas_field_format.py lib/
ln -s ../../nas_fsutil.py lib/
ln -s ../../nas_layout.py lib/
ln -s ../../nas_pbsutil.py lib/
ln -s ../../nas_xstat_config.py lib/
ln -s ../../qstat_userexits lib/
ln -s ../../pbs_ifl.py lib/
ln -s ../../_pbs_ifl.so lib/
ln -s ../../../example_new_field lib/site/
ln -s ../../../qstat_fs_exits lib/site/
ln -s ../../../qstat_userexits lib/site/
ln -s ../../../nas_qstat.1 man/man1/
ln -s ../../../nas_qstat_userexits.3 man/man3/
ln -s ../../../nas_pbsfs.8 man/man8/

tar -czf ../${1:-nas_qstat.tgz} --dereference --owner=0 --group=0 .

cd ..
echo rm -r $dir
