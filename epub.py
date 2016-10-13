#!/usr/bin/env python

import curses
import curses.ascii
import locale
import os
import re
import tempfile
import zipfile
from bs4 import BeautifulSoup
from html.parser import HTMLParser
from math import log10, floor
from textwrap import wrap
from time import time

try:
    from fabulous import image
except ImportError:
    images = False
else:
    images = True

locale.setlocale(locale.LC_ALL, 'en_US.utf-8')

basedir = ''
parser = None


class Parser(HTMLParser):
    def __init__(self, html_file=None, maxcol=72):
        HTMLParser.__init__(self)
        self.html_file = html_file
        self.data = ''

    def anchor_end(self):
        self.anchor = None

    def handle_startendtag(self, tag, attrs):
        if tag == 'img':
            for name, val in attrs:
                if name == 'src':
                    source = val
                elif name == 'alt':
                    alt = val

            if os.path.isabs(source):
                src = source
            else:
                src = os.path.normpath(
                    os.path.join(os.path.dirname(self.html_file), source)
                )

            self.data += '[img="{0}" "{1}"]'.format(src, alt)

    def handle_data(self, data):
        self.data += data

    def get_data(self):
        return self.data


def run(screen, program, *args):
    curses.nocbreak()
    screen.keypad(0)
    curses.echo()
    pid = os.fork()
    if not pid:
        os.execvp(program, (program,) + args)
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
        print(image.Image(image_file.name))
    except:
        print(image_file.name)
    finally:
        os.unlink(image_file.name)


def textify(html_snippet, img_size=(80, 45), maxcol=72, html_file=None):
    ''' text dump of html '''
    p = Parser(html_file)
    p.feed(html_snippet)
    p.close()

    text = ['\n'.join(wrap(v, maxcol)) for v in p.get_data().splitlines()]

    return '\n\n'.join(text)


def table_of_contents(fl):
    global basedir

    # find opf file
    soup = BeautifulSoup(fl.read('META-INF/container.xml'), "html.parser")
    opf = dict(soup.find('rootfile').attrs)['full-path']

    basedir = os.path.dirname(opf)
    if basedir:
        basedir = '{0}/'.format(basedir)

    soup = BeautifulSoup(fl.read(opf), "html.parser")

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
        soup = BeautifulSoup(fl.read(ncx), "html.parser")

        for navpoint in soup('navpoint'):
            k = navpoint.content.get('src', None)
            # strip off any anchor text
            k = k.split('#')[0]
            if k:
                z['{0}{1}'.format(basedir, k)] = navpoint.navlabel.text

    # output
    for section in y:
        if section in z:
            yield (z[section].strip(), section)
        else:
            yield (u'', section.strip())


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
    return os.path.isfile(fl)


def dump_epub(fl, maxcol=float("+inf")):
    if not check_epub(fl):
        return
    fl = zipfile.ZipFile(fl, 'r')
    chaps = [i for i in table_of_contents(fl)]
    for title, src in chaps:
        print(title)
        print('-' * len(title))
        if src:
            soup = BeautifulSoup(fl.read(src), "html.parser")
            txt = str(soup.find('body'))
            print(textify(
                txt,
                maxcol=maxcol,
                html_file=src
            ))
        print('\n')


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

    maxy, maxx = screen.getmaxyx()
    if maxcol is not None and maxcol > 0 and maxcol < maxx:
        maxx = maxcol

    # toc
    while True:
        if cur_chap is None:
            curses.curs_set(1)

            if cursor_row >= maxy:
                cursor_row = maxy - 1

            len_chaps = list_chaps(screen, chaps, start, maxy)
            screen.move(cursor_row, 0)
        else:
            if cur_text is None:
                if chaps[cur_chap][1]:
                    html = fl.read(chaps[cur_chap][1])
                    soup = BeautifulSoup(html, "html.parser")
                    txt = str(soup.find('body'))
                    cur_text = textify(
                        txt,
                        img_size=(maxy, maxx),
                        maxcol=maxx,
                        html_file=chaps[cur_chap][1]
                    ).split('\n')
                else:
                    cur_text = ''

            images = []
            # Current status info
            # Total number of lines
            n_lines = len(cur_text)
            if info:
                # Title
                title = chaps[cur_chap][0]
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
            for i, line in enumerate(
                cur_text[chaps_pos[cur_chap]:
                         chaps_pos[cur_chap] + maxy - info_cols]
            ):
                try:
                    screen.addstr(i, 0, line)
                    mch = re.search('\[img="([^"]+)" "([^"]*)"\]', line)
                    if mch:
                        images.append(mch.group(1))
                except:
                    pass

            if info:
                # Current status info
                # Current (last) line number
                cur_line = min([n_lines, chaps_pos[cur_chap]+maxy-info_cols])
                # Current page
                cur_page = (cur_line - 1) / (maxy - 2) + 1
                # Current position (%)
                cur_pos = 100 * (float(cur_line) / n_lines)

                try:
                    screen.addstr(maxy - 1, 0,
                                  '%s (%2d/%2d) %s Page %2d/%2d (%5.1f%%)' % (
                                      title,
                                      cur_chap,
                                      n_chaps,
                                      spaces,
                                      cur_page,
                                      n_pages,
                                      cur_pos
                                  ))
                except:
                    pass
            screen.refresh()

        ch = screen.getch()

        if cur_chap is None:
            try:
                # Set getch to non-blocking
                screen.nodelay(1)
                # Get int from input
                n = int(chr(ch))
                # Maximim number one can compute with the same number of digits
                # as the number of chapters
                # Ex.: for 80 chapters, max_n = 99
                max_n = int(10 ** floor(log10(n_chaps) + 1) - 1)

                # Break on non-digit input
                while chr(ch).isdigit():
                    delay = time()
                    ch = -1
                    # Wait for next character for 0.35 seconds
                    while ch == -1 and time() - delay < 0.35:
                        ch = screen.getch()

                    # If user has input a digit
                    if ch != -1 and chr(ch).isdigit():
                        n = n * 10 + int(chr(ch))
                    # User requested a non-existent chapter, bail
                    if n > n_chaps:
                        break
                    # When we're on the character limit, or no digit was input
                    # go to chapter
                    elif n * 10 > max_n or ch == -1:
                        cur_chap = n
                        cur_text = None

                        # Position cursor in middle of screen
                        # Adjust start acordingly
                        start = cur_chap - maxy / 2
                        if start > n_chaps - maxy + 1:
                            start = n_chaps - maxy + 1
                        if start < 0:
                            start = 0

                        cursor_row = cur_chap - start
                        break
            except:
                pass
            finally:
                screen.nodelay(0)

        # help
        try:
            if chr(ch) == 'h':
                curses.curs_set(0)
                screen.clear()
                for i, line in enumerate(parser.format_help().split('\n')):
                    screen.addstr(i, 0, line)
                screen.refresh()
                screen.getch()
                screen.clear()

        # quit
            if ch == curses.ascii.ESC or chr(ch) == 'q':
                return

            if chr(ch) == 'i':
                for img in images:
                    err = open_image(screen, img, fl.read(img))
                    if err:
                        screen.addstr(0, 0, err, curses.A_REVERSE)

            # edit html
            elif chr(ch) == 'e':

                tmpfl = tempfile.NamedTemporaryFile(delete=False)
                tmpfl.write(html)
                tmpfl.close()
                run(screen, 'vim', tmpfl.name)
                with open(tmpfl.name) as changed:
                    new_html = changed.read()
                    os.unlink(tmpfl.name)
                    if new_html != html:
                        pass
                        # write to zipfile?

                # go back to TOC
                screen.clear()

        except (ValueError, IndexError):
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
                if chaps_pos[cur_chap] + maxy - info_cols < \
                        n_lines + maxy - info_cols - 1:
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
                if chaps_pos[cur_chap] + maxy - info_cols < n_lines:
                    chaps_pos[cur_chap] += maxy - info_cols
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
                    chaps_pos[cur_chap] -= maxy - info_cols
                    if chaps_pos[cur_chap] < 0:
                        chaps_pos[cur_chap] = 0
                elif cur_chap > 0:
                    cur_chap -= 1
                    cur_text = None
                screen.clear()

        # Position cursor in first chapter / go to first page
        elif ch in [curses.KEY_HOME]:
            if cur_chap is None:
                start = 0
                cursor_row = 0
            else:
                chaps_pos[cur_chap] = 0
            screen.clear()
        # Position cursor in last chapter / go to last page
        elif ch in [curses.KEY_END]:
            if cur_chap is None:
                cursor_row = min(n_chaps, maxy)
                start = max(0, n_chaps - cursor_row)
            else:
                chaps_pos[cur_chap] = n_lines - n_lines % (maxy - info_cols)
                cur_text = None
            screen.clear()

        # to chapter
        elif ch in [curses.ascii.HT, curses.KEY_RIGHT, curses.KEY_LEFT]:
            if cur_chap is None and start + cursor_row != 0:
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
    parser.add_argument(
        '-d', '--dump',
        action='store_true',
        help='dump EPUB to text'
    )
    parser.add_argument(
        '-c', '--cols',
        action='store',
        type=int,
        default=float("+inf"),
        help='Number of columns to wrap; default is no wrapping.'
    )
    parser.add_argument(
        '-I', '--no-info',
        action='store_true',
        default=False,
        help='Do not display chapter/page info. Defaults to false.'
    )
    parser.add_argument('EPUB', help='view EPUB')

    args = parser.parse_args()
    if args.EPUB:
        if args.dump:
            dump_epub(args.EPUB, args.cols)
        else:
            try:
                curses.wrapper(
                    curses_epub,
                    args.EPUB,
                    not args.no_info,
                    args.cols
                )
            except KeyboardInterrupt:
                pass
