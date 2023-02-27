%module pbs_ifl
%typemap(out) char ** {
  int len,i;
  len = 0;
  while ($1[len]) len++;
  $result = PyList_New(len);
  for (i = 0; i < len; i++) {
    PyList_SetItem($result,i,PyString_FromString($1[i]));
  }
}
%typemap(in) char ** {
  if (PyList_Check($input)) {
    int size = PyList_Size($input);
    int i = 0;
    $1 = (char **) malloc((size+1)*sizeof(char *));
    for (i = 0; i < size; i++) {
      PyObject *o = PyList_GetItem($input,i);
      if (PyString_Check(o))
        $1[i] = PyString_AsString(PyList_GetItem($input,i));
      else {
        PyErr_SetString(PyExc_TypeError,"list must contain strings");
        free($1);
        return NULL;
      }
    }
    $1[i] = 0;
  } else {
    PyErr_SetString(PyExc_TypeError,"not a list");
    return NULL;
  }
}
%typemap(out) struct batch_status * {
    struct batch_status *head_bs, *bs;
    struct attrl *attribs;
    char *resource;
    char *str;
    int i, j;
    int len;
    char buf[4096];
    static char *id = "id";
    head_bs = $1;
    bs = $1;
    for (len=0; bs != NULL; len++)
        bs = bs->next;
    $result = PyList_New(len);
    bs = head_bs;
    for (i=0; i < len; i++) {
        PyObject *dict;
        PyObject *a, *v, *tmpv;
        dict = PyDict_New();
        PyList_SetItem($result, i, dict);
        a = PyString_FromString(id);
        v = PyString_FromString(bs->name);
        PyDict_SetItem(dict, a, v);
        attribs = bs->attribs;
        while (attribs) {
            resource = attribs->resource;
            if (resource != NULL) {
                str = malloc(strlen(attribs->name) + strlen(resource) + 2);
                sprintf(str, "%s.%s", attribs->name, attribs->resource);
                a = PyString_FromString(str);
                free(str);
            }
            else {
                a = PyString_FromString(attribs->name);
            }
            tmpv = PyDict_GetItem(dict, a);
            if (tmpv != NULL) {
                char *s = PyString_AsString(tmpv);
                str = malloc(strlen(attribs->value) + strlen(s) + 4);
                sprintf(str, "%s,%s", attribs->value, s);
                v = PyString_FromString(str);
                free(str);
            }
            else {
                v = PyString_FromString(attribs->value);
            }
            PyDict_SetItem(dict, a, v);
            attribs = attribs->next;
        }
        bs = bs->next;
    }
}
%{
#include "pbs_ifl.h"
#include "pbs_error.h"
#include "my_pbsconf.h"
%}

/* functions to acquire values from thread specific variables */
%inline
%{
int get_pbs_errno(void)
{
    return pbs_errno;
}

const char * get_pbs_server(void)
{
    return pbs_server;
}

const char * get_pbs_version(void)
{
    return PBS_VERSION;
}
%}

%include "pbs_ifl.h"
%include "pbs_error.h"
%include "my_pbsconf.h"
