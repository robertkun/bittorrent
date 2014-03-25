import hashlib
import struct
import math
import sys
import os

from bitstring import BitArray
import bencode
import requests

from peers import PeerManager
import pdb

HEADER_SIZE = 28 # This is just the pstrlen+pstr+reserved
# TODO make the parser stateless and a parser for each object 

def checkValidPeer(peer, infoHash):
    """
    Check to see if the info hash from the peer matches with the one we have 
    from the .torrent file.
    """
    peerInfoHash = peer.bufferRead[HEADER_SIZE:HEADER_SIZE+len(infoHash)]
    
    if peerInfoHash == infoHash:
        peer.bufferRead = peer.bufferRead[HEADER_SIZE+len(infoHash)+20:]
        peer.handshake = True
        print "Handshake Valid"
        return True
    else:
        return False

def convertBytesToDecimal(headerBytes, power):
    size = 0
    for ch in headerBytes:
        size += int(ord(ch))*256**power
        power -= 1
    return size

def handleHave(peer, payload):
    index = convertBytesToDecimal(payload, 3)
    print "Handling Have"
    peer.bitField[index] = True

def makeInterestedMessage():
    interested = '\x00\x00\x00\x01\x02'

    return interested

def sendRequest(index, offset, length):
    header = struct.pack('>I', 13)
    id = '\x06'
    index = struct.pack('>I', index)
    offset = struct.pack('>I', offset)
    length = struct.pack('>I', length)
    request = header + id + index + offset + length
    return request

def process_message(peer, peerMngr):
    while len(peer.bufferRead) > 3:
        if not peer.handshake:
            if not checkValidPeer(peer, peerMngr.infoHash):
                return False
            elif len(peer.bufferRead) < 4:
                return True

        msgSize = convertBytesToDecimal(peer.bufferRead[0:4], 3)
        if len(peer.bufferRead) == 4:
            if msgSize == '\x00\x00\x00\x00':
                # Keep alive
                return True
            return True 
        
        msgCode = int(ord(peer.bufferRead[4:5]))
        payload = peer.bufferRead[5:4+msgSize]
        if len(payload) < msgSize-1:
            # Message is not complete. Return
            return True
        peer.bufferRead = peer.bufferRead[msgSize+4:]
        if not msgCode:
            # Keep Alive. Keep the connection alive.
            continue
        elif msgCode == 0:
            # Choked
            peer.choked = True
            continue
        elif msgCode == 1:
            # Unchoked! send request
            print "Unchoked! Finding block",
            peer.choked = False
            nextBlock = peerMngr.findNextBlock(peer)
            if not nextBlock:
                return False
            index, offset, length = nextBlock
            peer.bufferWrite += sendRequest(index, offset, length)
        elif msgCode == 4:
            handleHave(peer, payload)
        elif msgCode == 5:
            peer.setBitField(payload)
        elif msgCode == 7:
            print ".",
            sys.stdout.flush()

            index = convertBytesToDecimal(payload[0:4], 3)
            offset = convertBytesToDecimal(payload[4:8], 3)
            data = payload[8:]
            piece = peerMngr.pieces[index]

            result = piece.addBlock(offset, data)

            # Adding a block was not successful. Disconnect from peer.
            if not result:
                return False

            nextBlock = peerMngr.findNextBlock(peer)

            if not nextBlock:
                return False

            index, offset, length = nextBlock
            peer.bufferWrite = sendRequest(index, offset, length)

        if not peer.sentInterested:
            print ("Bitfield initalized. "
                   "Sending peer we are interested...")
            peer.bufferWrite = makeInterestedMessage()
            peer.sentInterested = True
    return True

def generateMoreData(myBuffer, pieces):
    for piece in pieces:
        if piece.block:
            myBuffer += piece.block
            yield myBuffer
        else:
            raise ValueError('Pieces was corrupted. Did not download piece properly.')

def writeToMultipleFiles(files, path, pieces):
    bufferGenerator = None
    myBuffer = ''
    
    for f in files:
        fileObj = open(path + f['path'][0], 'wb')
        length = f['length']

        if not bufferGenerator:
            bufferGenerator = generateMoreData(myBuffer, pieces)

        while length > len(myBuffer):
            myBuffer = next(bufferGenerator)

        fileObj.write(myBuffer[:length])
        myBuffer = myBuffer[length:]
        fileObj.close()

def writeToFile(file, length, pieces):
    fileObj = open('./' + file, 'wb')
    myBuffer = ''
   
    bufferGenerator = generateMoreData(myBuffer, pieces)

    while length > len(myBuffer):
        myBuffer = next(bufferGenerator)

    fileObj.write(myBuffer[:length])
    fileObj.close()

def write(info, pieces):
    if 'files' in info:
        path = './'+ info['name'] + '/'
        if not os.path.exists(path):
            os.makedirs(path)
        writeToMultipleFiles(info['files'], path, pieces)    
    else:
        writeToFile(info['name'], info['length'], pieces)
