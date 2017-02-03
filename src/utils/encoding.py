# -*- coding: utf-8 -*-
#
# codimension - graphics python two-way code editor and analyzer
# Copyright (C) 2010-2017 Sergey Satskiy <sergey.satskiy@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""Encoding related functions"""

import re
import encodings
import logging
from codecs import BOM_UTF8, BOM_UTF16, BOM_UTF32
from cdmbriefparser import getBriefModuleInfoFromMemory
from .diskvaluesrelay import getFileEncoding
from .fileutils import isPythonFile
from .globals import GlobalData
from .settings import Settings


# There is no way to query a complete list of the supported codecs at run-time.
# So there is the list below.
# Note: aliases are not included into the list (could be retrieved at run-time)
# Note: there could be user registered codecs as well
# Note: the list is copied from the python documentation:
#       https://docs.python.org/3/library/codecs.html
# Note: instead of the '_' char in the list the '-' was used: it looks nicer
STANDARD_CODECS = ['ascii', 'big5', 'big5hkscs', 'cp037', 'cp273', 'cp424',
                   'cp437', 'cp500', 'cp720', 'cp737', 'cp775', 'cp850',
                   'cp852', 'cp855', 'cp856', 'cp857', 'cp858', 'cp860',
                   'cp861', 'cp862', 'cp863', 'cp864', 'cp865', 'cp866',
                   'cp869', 'cp874', 'cp875', 'cp932', 'cp949', 'cp950',
                   'cp1006', 'cp1026', 'cp1125', 'cp1140', 'cp1250',
                   'cp1251', 'cp1252', 'cp1253', 'cp1254', 'cp1255',
                   'cp1256', 'cp1257', 'cp1258', 'cp65001', 'euc_jp',
                   'euc-jis-2004', 'euc-jisx0213', 'euc-kr', 'gb2312',
                   'gbk', 'gb18030', 'hz', 'iso2022-jp', 'iso2022-jp-1',
                   'iso2022-jp-2', 'iso2022-jp-2004', 'iso2022-jp-3',
                   'iso2022_jp-ext', 'iso2022-kr', 'latin-1', 'iso8859-2',
                   'iso8859-3', 'iso8859-4', 'iso8859-5', 'iso8859-6',
                   'iso8859-7', 'iso8859-8', 'iso8859-9', 'iso8859-10',
                   'iso8859-11', 'iso8859-13', 'iso8859-14', 'iso8859-15',
                   'iso8859-16', 'johab', 'koi8-r', 'koi8-t', 'koi8-u',
                   'kz1048', 'mac-cyrillic', 'mac-greek', 'mac-iceland',
                   'mac-latin2', 'mac-roman', 'mac-turkish', 'ptcp154',
                   'shift-jis', 'shift-jis-2004', 'shift-jisx0213',
                   'utf-32', 'utf-32-be', 'utf-32-le',
                   'utf-16', 'utf-16-be', 'utf-16-le',
                   'utf-7', 'utf-8', 'utf-8-sig']

# These codecs were introduced to support BOM signatures without loosing
# them in the read->modify->write cycle
SYNTHETIC_CODECS = ['bom-utf-8', 'bom-utf-16', 'bom-utf-32']

SUPPORTED_CODECS = STANDARD_CODECS + SYNTHETIC_CODECS


CODING_FROM_BYTES = [
    (2, re.compile(br'''coding[:=]\s*([-\w_.]+)''')),
    (1, re.compile(br'''<\?xml.*\bencoding\s*=\s*['"]([-\w_.]+)['"]\?>'''))]


def convertLineEnds(text, eol):
    """Converts the end of line characters in text to the given eol"""
    if eol == '\r\n':
        regexp = re.compile(r"(\r(?!\n)|(?<!\r)\n)")
        return regexp.sub(lambda m, eol='\r\n': eol, text)
    if eol == '\n':
        regexp = re.compile(r"(\r\n|\r)")
        return regexp.sub(lambda m, eol='\n': eol, text)
    if eol == '\r':
        regexp = re.compile(r"(\r\n|\n)")
        return regexp.sub(lambda m, eol='\r': eol, text)
    return text


def detectEolString(text):
    """Detects the eol string using the first split. It cannot detect a mix"""
    if len(text.split('\r\n', 1)) == 2:
        return '\r\n'
    if len(text.split('\r', 1)) == 2:
        return '\r'
    return '\n'


def isValidEncoding(enc):
    """Checks if it is a valid encoding"""
    norm_enc = encodings.normalize_encoding(enc).lower()
    if norm_enc in SUPPORTED_CODECS:
        return True
    if norm_enc in [encodings.normalize_encoding(supp_enc)
                    for supp_enc in SUPPORTED_CODECS]:
        return True

    # Check the aliases as well
    if norm_enc in encodings.aliases.aliases:
        return True
    return False


def getNormalizedEncoding(enc):
    """Returns a normalized encoding or throws an exception"""
    if not isValidEncoding(enc):
        raise Exception('Unsupported encoding ' + enc)
    norm_enc = encodings.normalize_encoding(enc).lower()
    return encodings.aliases.aliases.get(norm_enc, norm_enc)


def areEncodingsEqual(enc_lhs, enc_rhs):
    """True if the encodings are essentially the same"""
    return getNormalizedEncoding(enc_lhs) == getNormalizedEncoding(enc_rhs)


def getCodingFromBytes(text):
    """Tries to find an encoding spec from a binary file content"""
    lines = text.splitlines()
    for cfb in CODING_FROM_BYTES:
        head = lines[:cfb[0]]
        regexp = cfb[1]
        for line in head:
            match = regexp.search(line)
            if match:
                return str(match.group(1), 'ascii')
    return None


def encodingSanityCheck(fName, decodedText, expectedEncoding):
    """Checks if the expected encoding matches the encing in the file"""
    try:
        modInfo = getBriefModuleInfoFromMemory(decodedText)
        modEncoding = modInfo.encoding
        if modEncoding:
            if not isValidEncoding(modEncoding):
                logging.warning("Invalid encoding " + modEncoding +
                                " found in the file " + fName)
                return False
            if not areEncodingsEqual(modEncoding, expectedEncoding):
                if expectedEncoding.startswith('bom-'):
                    noBomEncoding = expectedEncoding[4:]
                    if areEncodingsEqual(modEncoding, noBomEncoding):
                        return True
                logging.warning("The expected encoding " + expectedEncoding +
                                " does not match encoding " + modEncoding +
                                " specified in the  file " + fName)
                return False
    except:
        pass
    return True


def readEncodedFile(fName):
    """Reads the encoded file"""
    # Returns: text, used encoding
    with open(fName, 'rb') as diskfile:
        text = diskfile.read()

    isPython = isPythonFile(fName)
    triedEncodings = []
    # Step 1: check for BOM
    try:
        if text.startswith(BOM_UTF8):
            text = text[len(BOM_UTF8):]
            triedEncodings.append(encodings.normalize_encoding('utf-8'))
            decodedText = str(text, 'utf-8')
            if isPython:
                encodingSanityCheck(fName, decodedText, 'bom-utf-8')
            return decodedText, 'bom-utf-8'
        if text.startswith(BOM_UTF16):
            text = text[len(BOM_UTF16):]
            triedEncodings.append(encodings.normalize_encoding('utf-16'))
            decodedText = str(text, 'utf-16')
            if isPython:
                encodingSanityCheck(fName, decodedText, 'bom-utf-16')
            return decodedText, 'bom-utf-16'
        if text.startswith(BOM_UTF32):
            text = text[len(BOM_UTF32):]
            triedEncodings.append(encodings.normalize_encoding('utf-32'))
            decodedText = str(text, 'utf-32')
            if isPython:
                encodingSanityCheck(fName, decodedText, 'bom-utf-32')
            return decodedText, 'bom-utf-32'
    except (UnicodeError, LookupError) as exc:
        logging.error("BOM signature bom-" + triedEncodings[0] +
                      " found in the file but decoding failed: " + str(exc))
        logging.error("Continue trying to decode...")

    # Check if it was a user assigned encoding
    userAssignedEncoding = getFileEncoding(fName)
    if userAssignedEncoding:
        if not isValidEncoding(userAssignedEncoding):
            logging.error("User assigned encoding " + userAssignedEncoding +
                          " is invalid. Continue trying to decode...")
        elif encodings.normalize_encoding(userAssignedEncoding) \
                                                    not in triedEncodings:
            triedEncodings.append(
                encodings.normalize_encoding(userAssignedEncoding))
            try:
                decodedText = str(text, userAssignedEncoding)
                if isPython:
                    encodingSanityCheck(fName, decodedText,
                                        userAssignedEncoding)
                return decodedText, userAssignedEncoding
            except (UnicodeError, LookupError) as exc:
                logging.error("Failed to decode using the user assigned "
                              "encoding " + userAssignedEncoding +
                              ". Continue trying...")

    # Step 3: extract encoding from the file
    encFromFile = getCodingFromBytes(text)
    if encFromFile:
        if not isValidEncoding(encFromFile):
            logging.error("Invalid encoding found in the content: " +
                          encFromFile + ". Continue trying...")
        elif encodings.normalize_encoding(encFromFile) not in triedEncodings:
            triedEncodings.append(
                encodings.normalize_encoding(encFromFile))
            try:
                decodedText = str(text, encFromFile)
                if isPython:
                    encodingSanityCheck(fName, decodedText,
                                        encFromFile)
                return decodedText, encFromFile
            except (UnicodeError, LookupError) as exc:
                logging.error("Failed to decode using encoding " +
                              encFromFile + " found in the file. "
                              "Continue trying...")

    # Step 4: check the project default encoding
    project = GlobalData().project
    if project.isLoaded():
        projectEncoding = project.props['encoding']
        if projectEncoding:
            if not isValidEncoding(projectEncoding):
                logging.error("Invalid project encoding: " +
                              projectEncoding + ". Continue trying...")
            elif encodings.normalize_encoding(projectEncoding) not in triedEncodings:
                triedEncodings.append(
                    encodings.normalize_encoding(projectEncoding))
                try:
                    decodedText = str(text, projectEncoding)
                    if isPython:
                        encodingSanityCheck(fName, decodedText,
                                            projectEncoding)
                    return decodedText, projectEncoding
                except (UnicodeError, LookupError) as exc:
                    logging.error("Failed to decode using project encoding " +
                                  projectEncoding + ". Continue trying...")

    # Step 5: checks the IDE encoding
    ideEncoding = Settings()['encoding']
    if ideEncoding:
        if not isValidEncoding(ideEncoding):
            logging.error("Invalid ide encoding: " +
                          ideEncoding + ". Continue trying...")
        elif encodings.normalize_encoding(ideEncoding) not in triedEncodings:
            triedEncodings.append(
                encodings.normalize_encoding(ideEncoding))
            try:
                decodedText = str(text, ideEncoding)
                if isPython:
                    encodingSanityCheck(fName, decodedText,
                                        ideEncoding)
                return decodedText, ideEncoding
            except (UnicodeError, LookupError) as exc:
                logging.error("Failed to decode using project encoding " +
                              ideEncoding + ". Continue trying...")

    # Step 6: default: utf-8
    if encodings.normalize_encoding('utf-8') not in triedEncodings:
        triedEncodings.append(encodings.normalize_encoding('utf-8'))
        try:
            decodedText = str(text, 'utf-8')
            if isPython:
                encodingSanityCheck(fName, decodedText,
                                    'utf-8')
            return decodedText, 'utf-8'
        except (UnicodeError, LookupError) as exc:
            logging.error("Failed to decode using default encoding "
                          "utf-8. Continue trying...")

    # Step 7: last resort utf-8 with loosing information
    logging.warning("Last try: utf-8 decoding ignoring the errors...")
    return str(text, 'utf-8', 'ignore'), 'utf-8'
