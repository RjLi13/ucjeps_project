from PIL import Image
from PIL.ExifTags import TAGS
import csv
import codecs
import re
import json
import logging
from xml.sax.saxutils import escape

from common import cspace  # we use the config file reading function
from cspace_django_site import settings
from os import path, listdir
from os.path import isfile, isdir, join

config = cspace.getConfig(path.join(settings.BASE_PARENT_DIR, 'config'), 'uploadmedia')
TEMPIMAGEDIR = config.get('files', 'directory')
POSTBLOBPATH = config.get('info', 'postblobpath')
JOBDIR = path.join(TEMPIMAGEDIR, '%s')
SERVERINFO = {
    'serverlabelcolor': config.get('info', 'serverlabelcolor'),
    'serverlabel': config.get('info', 'serverlabel')
}
INSTITUTION = config.get('info', 'institution')

if isdir(TEMPIMAGEDIR):
    print "Using %s as working directory for images and metadata files" % TEMPIMAGEDIR
else:
    raise Exception("working directory %s does not exist. this webapp will not work!" % TEMPIMAGEDIR)

# Get an instance of a logger, log some startup info
logger = logging.getLogger(__name__)


def getJobfile(jobnumber):
    return JOBDIR % jobnumber


def jobsummary(jobstats):
    result = [0, 0, 0, []]
    for jobname, status, count, imagefilenames in jobstats:
        if 'pending' in status:
            result[0] = count - 1
        if 'submitted' in status:
            result[0] = count - 1
            inputimages = imagefilenames
        if 'ingested' in status:
            result[1] = count
            try:
                result[2] = result[0] - result[1]
                result[3] = [image for image in inputimages if image not in imagefilenames and image != 'name']
            except:
                pass
    return result


def getJoblist():
    jobpath = JOBDIR % ''
    filelist = [f for f in listdir(jobpath) if isfile(join(jobpath, f)) and ('.csv' in f or 'trace.log' in f)]
    jobdict = {}
    errors = []
    for f in sorted(filelist):
        linecount, imagefilenames = checkFile(join(jobpath, f))
        parts = f.split('.')
        if 'original' in parts[1]:
            status = 'submitted'
        elif 'processed' in parts[1]:
            status = 'ingested'
        elif 'inprogress' in parts[1]:
            status = 'job started'
        elif 'step1' in parts[1]:
            status = 'pending'
        elif 'step2' in parts[1]:
            continue
        # we are in fact keeping the step2 files for now, but let's not show them...
        # elif 'step2' in parts[1]: status = 'blobs in progress'
        elif 'step3' in parts[1]:
            status = 'media in progress'
        elif 'trace' in parts[1]:
            status = 'run log'
        else:
            status = 'unknown'
        jobkey = parts[0]
        if not jobkey in jobdict: jobdict[jobkey] = []
        jobdict[jobkey].append([f, status, linecount, imagefilenames])
    joblist = [[jobkey, True, jobdict[jobkey], jobsummary(jobdict[jobkey])] for jobkey in sorted(jobdict.keys(), reverse=True)]
    for ajob in joblist:
        for image in ajob[3][3]:
            errors.append([ajob[0], image])
        for state in ajob[2]:
            if state[1] in ['ingested', 'pending', 'job started']: ajob[1] = False
    return joblist[0:500], errors, len(joblist), len(errors)


def checkFile(filename):
    file_handle = open(filename)
    lines = file_handle.read().splitlines()
    images = [f.split("\t")[0] for f in lines]
    images = [f.split("|")[0] for f in images]
    return len(lines), images


def loginfo(infotype, line, request):
    logdata = ''
    # user = getattr(request, 'user', None)
    if request.user and not request.user.is_anonymous():
        username = request.user.username
    else:
        username = '-'
    logger.info('%s :: %s :: %s' % (infotype, line, logdata))


def getQueue(jobtypes):
    return [x for x in listdir(JOBDIR % '') if '%s.csv' % jobtypes in x]


def getDropdowns():
    allowintervention = config.get('info', 'allowintervention')
    creators = config.get('info', 'creators')
    creators = json.loads(creators)
    rightsholders = config.get('info', 'rightsholders')
    rightsholders = json.loads(rightsholders)
    return {
        'allowintervention': allowintervention,
        'creators': creators,
        'rightsholders': rightsholders
    }


# following function taken from stackoverflow and modified...thanks!
def get_exif(fn):
    ret = {}
    i = Image.open(fn)
    try:
        info = i._getexif()
        for tag, value in info.items():
            decoded = TAGS.get(tag, tag)
            ret[decoded] = value
    except:
        pass
    return ret


objectnumberpattern = re.compile('([a-z]+)\.([a-zA-Z0-9]+)')


def getNumber(filename):
    imagenumber = ''
    # the following is only for bampfa filenames...
    # input is something like: bampfa_1995-46-194-a-199.jpg, output should be: 1995.46.194.a-199
    if INSTITUTION == 'bampfa':
        objectnumber = filename.replace('bampfa_', '')
        try:
            objectnumber, imagenumber, imagetype = objectnumber.split('_')
        except:
            imagenumber = '1'
        # these legacy statement retained, just in case...
        # numHyphens = objectnumber.count("-") - 1
        #objectnumber = objectnumber.replace('-', '.', numHyphens)
        objectnumber = objectnumber.replace('-', '.')
        objectnumber = objectnumberpattern.sub(r'\1-\2', objectnumber)
    elif INSTITUTION == 'ucjeps':
        # typically, UC1107670.JPG
        filenameparts = filename.split('.')
        objectnumber = filenameparts[0]
        imagenumber = ''
    elif INSTITUTION == 'cinefiles':
        # e.g. 56306.p3.300gray.tif
        filenameparts = filename.split('.')
        objectnumber = filenameparts[0]
        imagenumber = filenameparts[1].replace('p','')
    # for pahma it suffices to split on underscore...
    elif INSTITUTION == 'pahma':
        objectnumber = filename
        objectnumber = objectnumber.split('_')[0]
    # the following is a last ditch attempt to get an object number from a filename...
    objectnumber = objectnumber.replace('.JPG', '').replace('.jpg', '').replace('.TIF', '').replace('.tif', '')
    return filename, objectnumber, imagenumber


def getCSID(objectnumber):
    # dummy function, for now
    objectCSID = objectnumber
    return objectCSID


def writeCsv(filename, items, writeheader):
    filehandle = codecs.open(filename, 'w', 'utf-8')
    writer = csv.writer(filehandle, delimiter='|')
    writer.writerow(writeheader)
    for item in items:
        row = []
        for x in writeheader:
            if x in item.keys():
                cell = str(item[x])
                cell = cell.strip()
                cell = cell.replace('"', '')
                cell = cell.replace('\n', '')
                cell = cell.replace('\r', '')
            else:
                cell = ''
            row.append(cell)
        writer.writerow(row)
    filehandle.close()


# following function borrowed from Django docs, w modifications
def handle_uploaded_file(f):
    destination = open(path.join(TEMPIMAGEDIR, '%s') % f.name, 'wb+')
    with destination:
        for chunk in f.chunks():
            destination.write(chunk)
    destination.close()


def assignValue(defaultValue, override, imageData, exifvalue, refnameList):
    if override == 'always':
        return defaultValue, refnameList.get(defaultValue, defaultValue)
    elif exifvalue in imageData:
        imageValue = imageData[exifvalue]
        # a bit of cleanup
        imageValue = imageValue.strip()
        imageValue = imageValue.replace('"', '')
        imageValue = imageValue.replace('\n', '')
        imageValue = imageValue.replace('\r', '')
        imageValue = escape(imageValue)
        return imageValue, refnameList.get(imageValue, imageValue)
    elif override == 'ifblank':
        return defaultValue, refnameList.get(defaultValue, defaultValue)
    else:
        return '', ''


# this function not currently in use. Copied from another script, it's not Django-compatible
def viewFile(logfilename, numtodisplay):
    print '<table width="100%">\n'
    print ('<tr>' + (4 * '<th class="ncell">%s</td>') + '</tr>\n') % (
        'locationDate,objectNumber,objectStatus,handler'.split(','))
    try:
        file_handle = open(logfilename)
        file_size = file_handle.tell()
        file_handle.seek(max(file_size - 9 * 1024, 0))

        lastn = file_handle.read().splitlines()[-numtodisplay:]
        for i in lastn:
            i = i.replace('urn:cspace:bampfa.cspace.berkeley.edu:personauthorities:name(person):item:name', '')
            line = ''
            if i[0] == '#': pass
        for l in [i.split('\t')[x] for x in [0, 1, 2, 5]]:
            line += ('<td>%s</td>' % l)
            # for l in i.split('\t') : line += ('<td>%s</td>' % l)
            print '<tr>' + line + '</tr>'

    except:
        print '<tr><td colspan="4">failed. sorry.</td></tr>'

    print '</table>'
