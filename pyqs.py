#!/usr/bin/python3

import sys
import os

PBS_EXEC = os.environ.get('PBS_EXEC', '/PBS')
sys.path.append('/PBS_new/lib/site')
sys.path.append(os.path.join(PBS_EXEC, 'lib', 'site'))
import layout

import pbs_ifl as ifl
from utils import BatchUtils

PBS_CONFIG = os.environ.get('PBS_CONFIG', '/etc/pbs.conf')
cfg = ifl.pbs_loadconf(0)
print(repr(cfg))

bu = BatchUtils()
conn = ifl.pbs_connect('localhost')

atl = bu.list_to_attrl(['Reserve_Name', 'Reserve_Owner', 'reserve_state',
'reserve_start', 'reserve_end', 'reserve_duration', 'queue', 'Resource_List',
'Authorized_Users', 'Authorized_Groups', 'euser', 'egroup'])
#atl = bu.list_to_attrl(['Reserve_Name'])
bs = ifl.pbs_statresv(conn, None, atl, None)
print(repr(bs))
print(ifl.pbs_Errno())
ifl.pbs_disconnect(conn)
