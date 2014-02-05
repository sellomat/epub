#!/usr/bin/env python
'''
python/curses epub reader. Requires BeautifulSoup

Keyboard commands:
    Esc/q          - quit
    Tab/Left/Right - toggle between TOC and chapter views
    TOC view:
        Up         - up a line
        Down       - down a line
        PgUp       - up a page
        PgDown     - down a page
    Chapter view:
        Up         - up a page
        Down       - down a page
        PgUp       - up a line
        PgDown     - down a line
        i          - open images on page in web browser
'''

import curses.wrapper, curses.ascii
import formatter, htmllib, locale, os, StringIO, re, readline, tempfile, zipfile
import mimetypes
import base64, webbrowser

from BeautifulSoup import BeautifulSoup

try:
    from fabulous import image
    import PIL
except ImportError:
    images = False
else:
    images = True

locale.setlocale(locale.LC_ALL, 'en_US.utf-8')

basedir = ''

def run(screen, program, *args):
    curses.nocbreak()
    screen.keypad(0)
    curses.echo()
    pid = os.fork()
    if not pid:
        os.execvp(program, (program,) +  args)
    os.wait()[0]
    curses.noecho()
    screen.keypad(1)
    curses.cbreak()

def open_image(screen, name, s):
    ''' show images with PIL and fabulous '''
    if not images:
        screen.addstr(0, 0, "missing PIL or fabulous", curses.A_REVERSE)
        return

    ext = os.path.splitext(name)[1]

    screen.erase()
    screen.refresh()
    curses.setsyx(0, 0)
    image_file = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    image_file.write(s)
    image_file.close()
    try:
        print image.Image(image_file.name)
    except:
        print image_file.name
    finally:
        os.unlink(image_file.name)

def textify(html_snippet, img_size=(80, 45), maxcol=72):
    ''' text dump of html '''
    class Parser(htmllib.HTMLParser):
        def anchor_end(self):
            self.anchor = None
        def handle_image(self, source, alt, ismap, alight, width, height):
            global basedir
            self.handle_data(
                '[img="{0}{1}" "{2}"]'.format(basedir, source, alt)
            )

    class Formatter(formatter.AbstractFormatter):
        pass

    class Writer(formatter.DumbWriter):
        def __init__(self, fl, maxcol=72):
            formatter.DumbWriter.__init__(self, fl)
            self.maxcol = maxcol
        def send_label_data(self, data):
            self.send_flowing_data(data)
            self.send_flowing_data(' ')

    o = StringIO.StringIO()
    p = Parser(Formatter(Writer(o, maxcol)))
    p.feed(html_snippet)
    p.close()

    return o.getvalue()

def table_of_contents(fl):
    global basedir

    # find opf file
    soup = BeautifulSoup(fl.read('META-INF/container.xml'),
                         convertEntities=BeautifulSoup.HTML_ENTITIES)
    opf = dict(soup.find('rootfile').attrs)['full-path']

    basedir = os.path.dirname(opf)
    if basedir:
        basedir = '{0}/'.format(basedir)

    soup =  BeautifulSoup(fl.read(opf),
                          convertEntities=BeautifulSoup.HTML_ENTITIES)

    # title
    yield (soup.find('dc:title').text, None)

    # all files, not in order
    x, ncx = {}, None
    for item in soup.find('manifest').findAll('item'):
        d = dict(item.attrs)
        x[d['id']] = '{0}{1}'.format(basedir, d['href'])
        if d['media-type'] == 'application/x-dtbncx+xml':
            ncx = '{0}{1}'.format(basedir, d['href'])

    # reading order, not all files
    y = []
    for item in soup.find('spine').findAll('itemref'):
        y.append(x[dict(item.attrs)['idref']])

    z = {}
    if ncx:
        # get titles from the toc
        soup =  BeautifulSoup(fl.read(ncx),
                              convertEntities=BeautifulSoup.HTML_ENTITIES)

        for navpoint in soup('navpoint'):
            k = navpoint.content.get('src', None)
            # strip off any anchor text
            k = k.split('#')[0]
            if k:
                z['{0}{1}'.format(basedir, k)] = navpoint.navlabel.text

    # output
    for section in y:
        if section in z:
            yield (z[section].encode('utf-8'), section.encode('utf-8'))
        else:
            yield (u'', section.encode('utf-8').strip())

def list_chaps(screen, chaps, start, length):
    for i, (title, src) in enumerate(chaps[start:start+length]):
        try:
            if start == 0:
                screen.addstr(i, 0, '      {0}'.format(title), curses.A_BOLD)
            else:
                screen.addstr(i, 0, '{0:-5} {1}'.format(start, title))
        except:
            pass
        start += 1
    screen.refresh()
    return i

def check_epub(fl):
    return os.path.isfile(fl) and \
           mimetypes.guess_type(fl)[0] == 'application/epub+zip'

def dump_epub(fl, maxcol=float("+inf")):
    if not check_epub(fl):
        return
    fl = zipfile.ZipFile(fl, 'r')
    chaps = [i for i in table_of_contents(fl)]
    for title, src in chaps:
        print title
        print '-' * len(title)
        if src:
            soup = BeautifulSoup(fl.read(src),
                                 convertEntities=BeautifulSoup.HTML_ENTITIES)
            print textify(
                unicode(soup.find('body')).encode('utf-8'),
                maxcol=maxcol,
            )
        print '\n'

def read_chapter(fl, chaps, cur_chap, size):
    if chaps[cur_chap][1]:
        html = fl.read(chaps[cur_chap][1])
        soup = BeautifulSoup(html, convertEntities=BeautifulSoup.HTML_ENTITIES)
        cur_text = textify(
            unicode(soup.find('body')).encode('utf-8'),
            img_size = size,
            maxcol = size[1]
        ).split('\n')
    else:
        cur_text = ''
    return (len(cur_text) - 1, cur_text)

def curses_epub(screen, fl, info=True, maxcol=float("+inf")):
    if not check_epub(fl):
        return

    fl = zipfile.ZipFile(fl, 'r')
    chaps = [i for i in table_of_contents(fl)]
    chaps_pos = [0 for i in chaps]
    start = 0
    cursor_row = 0

    n_chaps = len(chaps) - 1

    cur_chap = None
    cur_text = None

    if info:
        info_cols = 2
    else:
        info_cols = 0

    # toc
    while True:
        if cur_chap is None:
            curses.curs_set(1)
            maxy, maxx = screen.getmaxyx()
            if maxcol is not None and maxcol > 0 and maxcol < maxx:
                maxx = maxcol

            if cursor_row >= maxy:
                cursor_row = maxy - 1

            len_chaps = list_chaps(screen, chaps, start, maxy)
            screen.move(cursor_row, 0)
        else:
            if cur_text is None:
                if chaps[cur_chap][1]:
                    html = fl.read(chaps[cur_chap][1])
                    soup = BeautifulSoup(html,
                                    convertEntities=BeautifulSoup.HTML_ENTITIES)
                    cur_text = textify(
                        unicode(soup.find('body')).encode('utf-8'),
                        img_size = (maxy, maxx),
                        maxcol = maxx
                    ).split('\n')
                else:
                    cur_text = ''
                n_lines = len(cur_text) - 1

            # Current status info
            # Total number of lines
            n_lines = len(cur_text) - 1
            if info:
                # Title
                title = unicode(chaps[cur_chap][0]).encode('utf-8')
                # Total number of pages
                n_pages = n_lines / (maxy - 2) + 1

                # Truncate title if too long. Add ellipsis at the end
                if len(title) > maxx - 29:
                    title = title[0:maxx - 30] + u'\u2026'.encode('utf-8')
                    spaces = ''
                else:
                    spaces = ''.join([' '] * (maxx - len(title) - 30))

            screen.clear()
            curses.curs_set(0)
            for i, line in enumerate(cur_text[chaps_pos[cur_chap]:
                                       chaps_pos[cur_chap] + maxy - info_cols]):
                try:
                    screen.addstr(i, 0, line)
                except:
                    pass

            if info:
                # Current status info
                # Current (last) line number
                cur_line = min([n_lines,chaps_pos[cur_chap]+maxy-info_cols-1])
                # Current page
                cur_page = cur_line / (maxy - 2) + 1
                # Current position (%)
                cur_pos  = 100 * (float(cur_line) / n_lines)

                try:
                    screen.addstr(maxy - 1, 0,
                                  '%s (%2d/%2d) %s Page %2d/%2d (%5.1f%%)' % (
                                    title,
                                    cur_chap,
                                    n_chaps,
                                    spaces,
                                    cur_page,
                                    n_pages,
                                    cur_pos))
                except:
                    pass
            screen.refresh()
            shown = maxy - info_cols - 1

        ch = screen.getch()

        # quit
        try:
           if ch == curses.ascii.ESC or chr(ch) == 'q':
               return
        except:
            pass

        # up/down line
        if ch in [curses.KEY_DOWN]:
            if cur_chap is None:
                if start < len(chaps) - maxy:
                    start += 1
                    screen.clear()
                elif cursor_row < maxy - 1 and cursor_row < len_chaps:
                    cursor_row += 1
            else:
                if chaps_pos[cur_chap] + shown < n_lines + 2 * (maxy / 3):
                    chaps_pos[cur_chap] += 1
                    screen.clear()
        elif ch in [curses.KEY_UP]:
            if cur_chap is None:
                if start > 0:
                    start -= 1
                    screen.clear()
                elif cursor_row > 0:
                    cursor_row -= 1
            else:
                if chaps_pos[cur_chap] > 0:
                    chaps_pos[cur_chap] -= 1
                    screen.clear()

        # up/down page
        elif ch in [curses.KEY_NPAGE]:
            if cur_chap is None:
                if start + maxy - 1 < len(chaps):
                    start += maxy - 1
                    if len_chaps < maxy:
                        start = len(chaps) - maxy
                    screen.clear()
            else:
                if chaps_pos[cur_chap] + shown < n_lines:
                    chaps_pos[cur_chap] += shown
                elif cur_chap < n_chaps:
                    cur_chap += 1
                    cur_text = None
                screen.clear()
        elif ch in [curses.KEY_PPAGE]:
            if cur_chap is None:
                if start > 0:
                    start -= maxy - 1
                    if start < 0:
                        start = 0
                    screen.clear()
            else:
                if chaps_pos[cur_chap] > 0:
                    chaps_pos[cur_chap] -= shown
                    if chaps_pos[cur_chap] < 0:
                        chaps_pos[cur_chap] = 0
                elif cur_chap > 0:
                    cur_chap -= 1
                    cur_text = None
                screen.clear()

        # to chapter
        elif ch in [curses.ascii.HT, curses.KEY_RIGHT, curses.KEY_LEFT]:
            if cur_chap is None:
                # Current chapter number
                cur_chap = start + cursor_row
                cur_text = None
            else:
                cur_chap = None
                cur_text = None
                screen.clear()

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument('-d', '--dump',
        action  = 'store_true',
        help    = 'dump EPUB to text')
    parser.add_argument('-c', '--cols',
        action  = 'store',
        type    = int,
        default = float("+inf"),
        help    = 'Number of columns to wrap; default is no wrapping.')
    parser.add_argument('-I', '--no-info',
        action  = 'store_true',
        default = False,
        help    = 'Do not display chapter/page info. Defaults to false.')
    parser.add_argument('EPUB', help='view EPUB')

    args = parser.parse_args()
    if args.EPUB:
        if args.dump:
            dump_epub(args.EPUB, args.cols)
        else:
            try:
                curses.wrapper(curses_epub,args.EPUB,not args.no_info,args.cols)
            except KeyboardInterrupt:
                pass
