import serial
import struct

config={
    'srcPorts': ["\\\\.\\CNCA0", "\\\\.\\CNCB0"],
    'dstPort': 'COM3'
}


sConSettings={
    'baudrate': 19200,
    'parity': serial.PARITY_NONE,
    'stopbits': serial.STOPBITS_ONE,
    'bytesize': serial.EIGHTBITS,
    'timeout': 0
}

dConSettings={
    'baudrate': 19200,
    'parity': serial.PARITY_NONE,
    'stopbits': serial.STOPBITS_ONE,
    'bytesize': serial.EIGHTBITS,
    'timeout': 5
}


def dictJoin(d1,d2):
    d1.update(d2)
    return d1

# source ports, also software ports - ports listening by vision
sPorts=[serial.Serial(**dictJoin({'port':portName},sConSettings)) for portName in config['srcPorts']]
# destignation port, also device port - port of connected IT device
dPort=serial.Serial(**dictJoin({'port':config['dstPort']},dConSettings))

c=0
replyChunkSize=100

lastSport=len(sPorts)-1
while True:
    anyDataReceived=False
    for i,sPort in enumerate(sPorts):
        req = sPort.read(9999)
        if len(req) == 0:
            # not received any data from sPort
            # if i==lastSport and (not anyDataReceived):
                # print('sleeping',c)
                # c+=1  
                # time.sleep(0.1)            
            continue

        # got some data from some sSport
        anyDataReceived=True

        if req[0]!=85:
            raise Exception('got wrong answer from software')

        # send received data to device
        dPort.write(req)

        # get reply header. It contains sync byte, device id and length of following data
        replyHeader = dPort.read(4)
        print(replyHeader.hex())
        sync, devId, replyLen =  struct.unpack('<2BH',replyHeader)
        print(sync,devId,replyLen)

        if sync!=85:
            raise Exception('got wrong answer from device')

        sPort.write(replyHeader)
        
        # print('>>>>', req)
        bytesToRead=replyLen

        while bytesToRead>0:
            readNow=min(bytesToRead,replyChunkSize)
            
            replyDataChunk=dPort.read(readNow)
            sPort.write(replyDataChunk)
            
            bytesToRead-=readNow



    # endfor sports