For many years, NASA’s Advanced Supercomputing (NAS) Division has taken
advantage of the “TCL\_QSTAT” compilation option to build a version
of qstat that uses TCL scripts to format the output. The scripts NAS
developed allow the system admins and users to customize qstat output
without needing to build special versions of qstat. For example, on
systems with GPUs, the number of GPUs requested by a job is included
in the default display, but not on clusters with no GPUs. Similarly,
users can add or remove fields using command line options or with a
$HOME/.qstatrc configuration file. Field widths automatically adjust
to accommodate requested information, or users can specify min and max
widths for individual fields.

Now, however, Altair wants to remove the TCL option from qstat to simplify
maintenance. This is going to be disruptive for NAS users. So, I have
been working on a python version of qstat. If there is enough interest,
I’ll propose adding it to the unsupported portion of OpenPBS. Having
a user-customizable version of qstat could reduce demand for yet more
features in the base qstat.

(I considered a script that starts with qstat -f -F json output, but
rejected it as too inefficient. Also, qstat -f grabs all info about a
job from the server, which takes more than twice as long as asking just
for the attributes of interest.)

The current python qstat (called “nas\_qstat”) recognizes the
following fields:

Acct Aoe Comment Cnt Cpct Cpus Cput Ctime Eff ElapWallt EligStart
EligTime EstEnd EstStart Exechost ExitStatus Gpus Group JobID Jobname
Lifetime MaxWallt Memory MinWallt Mission Model Nds Place Pmem Pri Qtime
Queue Rank0 Reqid ReqMem RemWallt ReqdWallt Runs S Sessid SeqNo SS Stime
User Vmem

Some of the fields are sourced directly from the pbs\_statjob results
and others are computed (e.g., eff = CPU efficiency).

So, for example, where the normal qstat gives:
```
Job id            Name             User              Time Use S Queue
----------------  ---------------- ----------------  -------- - -----
8.server2         STDIN            dtalcott                 0 H playq           
21.server2        STDIN            dtalcott                 0 Q playq           
22.server2        STDIN            dtalcott                 0 Q playq           
30.server2        STDIN            dtalcott          00:15:45 R workq           
31.server2        longish_name_5   dtalcott          00:00:10 R workq           
```
With no options, nas\_qstat gives:
```
                                                 Req'd     Elap
JobID      User     Queue Jobname        TSK Nds wallt S  wallt  Eff
---------- -------- ----- -------------- --- --- ----- - ------ ----
30.server2 dtalcott workq STDIN            1   1 00:33 R  00:16  99%
31.server2 dtalcott workq longish_name_5   1   1 00:33 R  00:00 100%
21.server2 dtalcott playq STDIN            1   1 00:33 Q 213:56   --
22.server2 dtalcott playq STDIN            1   1 00:33 Q 113:46   --
8.server2  dtalcott playq STDIN            1   1 00:03 H  00:00   --
```
You can add the remaining walltime to the list with
```
nas_qstat -W o=+remwallt
                                                 Req'd     Elap       Rem
JobID      User     Queue Jobname        TSK Nds wallt S  wallt Eff wallt
---------- -------- ----- -------------- --- --- ----- - ------ --- -----
30.server2 dtalcott workq STDIN            1   1 00:33 R  00:17 99% 00:17
31.server2 dtalcott workq longish_name_5   1   1 00:33 R  00:01 99% 00:32
21.server2 dtalcott playq STDIN            1   1 00:33 Q 213:56  -- 00:33
22.server2 dtalcott playq STDIN            1   1 00:33 Q 113:47  -- 00:33
8.server2  dtalcott playq STDIN            1   1 00:03 H  00:00  -- 00:00
```
If your users like long job names, you can limit them via
```
nas_qstat -W fmt_jobname=maxw:10
                                             Req'd     Elap
JobID      User     Queue Jobname    TSK Nds wallt S  wallt Eff
---------- -------- ----- ---------- --- --- ----- - ------ ---
30.server2 dtalcott workq STDIN        1   1 00:33 R  00:17 99%
31.server2 dtalcott workq longish_na   1   1 00:33 R  00:02 99%
21.server2 dtalcott playq STDIN        1   1 00:33 Q 213:57  --
22.server2 dtalcott playq STDIN        1   1 00:33 Q 113:47  --
8.server2  dtalcott playq STDIN        1   1 00:03 H  00:00  --
```
Sometimes, the beginnings and ends of job names are important. You can get that by specifying "end" justification with a truncation character of "#":
```
nas_qstat -W fmt_jobname='maxw:10 hj:e rt:#'
                                             Req'd     Elap
JobID      User     Queue Jobname    TSK Nds wallt S  wallt Eff
---------- -------- ----- ---------- --- --- ----- - ------ ---
30.server2 dtalcott workq STDIN        1   1 00:33 R  00:22 99%
31.server2 dtalcott workq long#ame_5   1   1 00:33 R  00:06 99%
21.server2 dtalcott playq STDIN        1   1 00:33 Q 214:02  --
22.server2 dtalcott playq STDIN        1   1 00:33 Q 113:52  --
8.server2  dtalcott playq STDIN        1   1 00:03 H  00:00  --
```
The -a option of nas\_qstat includes node information in a summarized format:
```
nas_qstat -a -r
server2:     Sat May  1 08:54:47 2021
 Server reports 4 jobs total (T:0 Q:2 H:1 W:0 R:1 E:0 B:0)

           CPUs/
  Host     used/free Tasks Jobs Info
  -------- ----/---- ----- ---- -----------------
  node3       1/   1     1    1
   3 hosts    0/   0     0    0 offline down
  node4       0/   1     0    0 vmac offline down
                                                 Req'd    Elap
JobID      User     Queue Jobname        TSK Nds wallt S wallt Eff
---------- -------- ----- -------------- --- --- ----- - ----- ---
31.server2 dtalcott workq longish_name_5   1   1 00:33 R 00:24 98%
```
It’s tricky, but admins and users can add new fields (perhaps computed
on the fly) without modifying the base code.

So, if you are interested, you can fetch the work in progress
here. For now, you’ll need to modify the ‘build\_pbs\_ifl’ script to tell
it where to find swig and where to find the OpenPBS source tree. This
script builds the pbs\_ifl module to give python access to PBS's IFL
routines.

Pieces:
* example\_new\_field -- Example defining new field for nas\_qstat (in this case, expansion factor)
* make\_tar.sh -- Script to build tar file for installation
* nas\_field\_format.py -- Functions to compute string values for fields
* nas\_fsutil.py -- Utility functions for fairshare data
* nas\_layout.py -- The layout engine that handles field justification, widths, headers, etc.
* nas\_pbsfs -- Python command to display fairshare information
* nas\_pbsfs.8 -- Man page for nasi\_pbsfs
* nas\_pbsutil.py -- Interfaces to PBS not supplied by pbs\_ifl.i
* nas\_qstat -- Main routine of python qstat
* nas\_qstat.1 -- Man page for nas\_qstat
* nas\_qstat\_userexits.3 -- Man page for nas\_qstat user exit callouts
* nas\_rstat -- Python version of pbs\_rstat (used as prototype for nas\_qstat)
* nas\_xstat\_config.py -- Global variables for nas\_qstat and nas\_rstat
* pbs\_ifl.i -- Slightly modified version of OpenPBS's swig input file to build pbs\_ifl module
* qstat\_fs\_exits -- Example site userexits for adding fairshare info to nas\_qstat
* qstat\_userexits -- Example site userexits, including GPU handling

The build\_pbs\_ifl script creates these files:
* pbs\_ifl.py -- Python module for access to PBS IFL library
* \_pbs\_ifl.so -- Loadable code for pbs\_ifl.py

I am particularly interested in suggestions for code speedups. For
example, on the host with 38k jobs (active and in history), OpenPBS
qstat takes 0.75 second, whereas python qstat takes 2.5 seconds. (The
TCL qstat takes ~20 seconds, so this version is already better than what
NAS has been using.)

# INSTALLATION #
Assume you want to install this under PBS\_EXEC/unsupported.  Run
```
 ./make_tar.sh
```
It creates a dummy install directory in TMPDIR and then tars that up
into nas\_qstat.tgz.  You can install that where you want. For example,
to install in $PBS\_EXEC/unsupported/, run (as root)

```
 tar -C PBS_EXEC/unsupported -xzf nas_qstat.tgz
```
You will want to edit PBS\_EXEC/unsupported/lib/site/qstat\_userexits to
suit your local site. Or remove it entirely to get default nas\_qstat 
behavior.

You can experiment with nas\_qstat as a normal user without installing it.
Create the .tgz file as above and extract it in some directory of your
choosing.  Set the NAS\_QSTAT\_EXEC environment variable to the path
where you extracted the files and run nas\_qstat from there:

```
 export NAS_QSTAT_EXEC=/some/place/of/your/choosing
 tar -C $NAS_QSTAT_EXEC -xzf nas_qstat.tgz
 $NAS_QSTAT_EXEC/bin/nas_qstat ...
```
