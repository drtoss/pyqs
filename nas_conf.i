%module nas_conf

%{
#include "pbs_ifl.h"
#include "pbs_error.h"
#include "my_pbsconf.h"
%}

%include "my_pbsconf.h"
%pythoncode %{
pbs_conf = _nas_conf.cvar.pbs_conf
__all__ = ['pbs_conf']
%}
