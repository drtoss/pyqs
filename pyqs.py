#!/usr/bin/python3

import sys
import os

PBS_EXEC = os.environ.get('PBS_EXEC', '/PBS')
sys.path.append('/PBS_new/lib/site')
sys.path.append(os.path.join(PBS_EXEC, 'lib', 'site'))

import pbs_ifl as ifl
from utils import BatchUtils

def foo(a):
	def bar(g, h):
		pass
	b = a + 1
	c = str(b)
	print(repr(locals()))
	print(type(bar))

foo(20)
