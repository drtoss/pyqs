#!/usr/bin/python3
"""
"""
def layout(config, rows, skip = 0, no_hdr = False):
    '''Layout data for printing

    Given a configuration and a list of rows of field values,
    create a list of lines ready for output containing headers
    followed by one line for each row, where the values are
    aligned within their columns.

    Args:
        config = described below
        rows = list of row values, each row is a list of field
            values.
        skip = number of leading rows to ignore
        no_hdr = True to skip headers

    Returns:
        A list of lines of formatted data

    The config is built from calls to the add_field() routine.

    Example:
        c = Config()
        c.add_field('fld1')
        c.add_field('fld2', maxw = 3, hj = 'r', hs = '|', rf = '0')
        c.add_field(['fld3', 'cont'], df = '+=', hj = 'r', hs = '')
        layout(c, [['tom', '0', 'one'], ['dick', '1', 'two'],
            ['harry', 1234, 'three']])

      produces:
        [
        ]
'''
    # Figure out how many header lines we'll need.
    hdrrows = config.bottom_just_titles()
    hdrcnt = len(hdrrows)
    print(repr(hdrrows))
    # And how many fields
    fldcnt = len(config.config)
    # Compute maximum widths of title/dash/data values for
    # each column.
    dashrows = [x['df'] for x in config.config]
    maxw = list()
    maxw = config.layout_max(maxw, hdrrows)
    maxw = config.layout_max(maxw, dashrows)
    maxw = config.layout_max(maxw, rows, skip)

class Config(object):
    def __init__(self):
        self.config = list()

    class fieldspec(object):
        def __init__(self, title, df='-', dj=None, ds=None,
            hf=' ', hj='l', hs=None, maxw=-1, minw=0,
            rf=None, rj=None, rs=None):

            # Set contingent defaults
            if hs == None:
                if maxw == 0:
                    hs = ''
                else:
                    hs = ' '
            if dj == None:
                dj = hj
            if ds == None:
                ds = hs
            if rf == None:
                rf = hf
            if rj == None:
                rj = hj
            if rs == None:
                rs = hs
            self.title = title
            self.df = df
            self.dj = dj
            self.ds = ds
            self.hf = hf
            self.hj = hj
            self.hs = hs
            self.maxw = maxw
            self.minw = minw
            self.rf = rf
            self.rj = rj
            self.rs = rs
    def add_field(self, title, **kwargs):
        '''Add settings for one field to config.

        The settings are contained in a _fieldspec object.

        Args:
            title = title of field. If the title is a list,
            it will be split across multiple lines in the
            headers.
            df = dashfill   String to repeat to form horizontal
                            separater between headers and data
                            (default -)
            dj = dashjust   Justification for dashfill
                            (default, hj)
            ds = dashseparator Character between this file and
                            the next
                            (default, hs)
            hf = headerfill String to fill header text to width
                            of column
                            (default space)
            hj = headerjust Header justification (l, c, r, lr)
                            (default l)
            hs = headerseparator Character between the field
                            header and the next
                            (default, space, unless maxw == 0)
            maxw            Maximum width of column, -1 implies
                            no maximum
            minw            Minimum width of column
            rf = rowfill    String to fill data values to width
                            of column
                            (default, hf)
            rj = rowjust    Data justification
                            (default, hj)
            rs = rowseparator Character between this data field
                            and the next
                            (default, hs)
        '''
        c = self.fieldspec(title, **kwargs)
        self.config.append(c)

    def bottom_just_titles(self):
        '''Bottom justify titles

        Adjust titles so they are all lists with the same
        number of elements, prepending short lists with
        empty strings.

        Returns: A list of title pieces in same structure
        as data rows.
        '''
        cnt = max([1 if isinstance(x.title, str) else len(x.title) for x in self.config])
        for fs in self.config:
            if isinstance(fs.title, str):
                fs.title = [fs.title]
            while len(fs.title) < cnt:
                fs.title.insert(0, '')
        rows = list()
        for i in range(cnt):
            flds = [x.title[i] for x in self.config]
            rows.append(flds)
        return rows

    def layout_max(self, maxw, rows, skip = 0):
        '''Compute max widths needed for each column

        Args:
            maxw = list to contain column widths
            rows = list of lists of column values
            skip = number of fields to skip in rows
        Exit:
            maxw updated
        '''
        fldcnt = len(rows[0])
        if len(maxw) == 0:
            maxw = [0 for x in range(fldcnt)]
        for row in rows:
            for i in range(fldcnt):
                maxw[i] = max([len(x) for x in row[skip:])

def test():
    c = Config()
    c.add_field('fld1')
    c.add_field('fld2', maxw = 3, hj = 'r', hs = '|', rf = '0')
    c.add_field(['fld3', 'cont'], df = '+=', hj = 'r', hs = '')
    layout(c, [['tom', '0', 'one'], ['dick', '1', 'two'],
        ['harry', 1234, 'three']])


if __name__ == '__main__':
    import sys
    sys.exit(test())

# vi:ts=4:sw=4:expandtab
